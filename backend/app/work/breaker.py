"""A circuit breaker for calls to a model provider.

When the provider is down, every call would otherwise wait out the SDK's own
retries and then fail, lease after lease, and the work it was doing would be
failed or, worse, quietly finished some other way. The breaker turns an outage
into a *hold*: after `failure_threshold` provider failures in a row it opens,
and while open no call goes out at all (CircuitOpen is raised at once). After
`reset_after` seconds it lets exactly one probe through (half-open); a probe
that succeeds closes it, a probe that fails opens it again for another
`reset_after`.

Only provider-side failures count (connection errors, timeouts, rate limits,
5xx). A 400 is a bug in the request, not an outage; it is re-raised and the
breaker does not move. A cached answer never reaches the provider, so it is
served whatever the breaker's state: `guard_client()` wraps the *client* the
LLM layer calls on a cache miss, not the LLM layer itself, which belongs to
`app/llm` and is not changed here.

What the abstraction job does with an open breaker is in
`jobs/lease_versions.py`: the job is held (put back in the queue until the
breaker will next probe, its attempt not spent), never failed and never
finished from a fallback.

State is visible two ways:

  states()                in-process, every breaker by name
  read_published(conn)    what a worker last published to `sync_cursor`
                          under `breaker:<name>` (the ops page reads this;
                          the worker publishes whenever a breaker changed)
"""

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"
LLM = "llm"
FAILURE_THRESHOLD = 5
RESET_AFTER = 60.0
CURSOR_PREFIX = "breaker:"


class CircuitOpen(RuntimeError):
    """The breaker is open (or a half-open probe is already out): no call was made."""

    def __init__(self, name: str, retry_in: float, last_error: Optional[str] = None):
        self.name = name
        self.retry_in = retry_in
        self.last_error = last_error
        super().__init__("circuit %r is open; next probe in %.0fs (last error: %s)"
                         % (name, retry_in, last_error or "-"))


def is_outage(exc: BaseException) -> bool:
    """True for a failure that says the provider is unavailable, not that the
    request was wrong."""
    try:
        import anthropic
    except ImportError:          # pragma: no cover - the SDK is a requirement
        anthropic = None
    if anthropic is not None:
        if isinstance(exc, (anthropic.APIConnectionError, anthropic.RateLimitError,
                            anthropic.InternalServerError)):
            return True
        if isinstance(exc, anthropic.APIStatusError):
            return getattr(exc, "status_code", 0) >= 500
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


class CircuitBreaker:
    def __init__(self, name: str, *, failure_threshold: int = FAILURE_THRESHOLD,
                 reset_after: float = RESET_AFTER,
                 clock: Callable[[], float] = time.monotonic):
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if reset_after < 0:
            raise ValueError("reset_after cannot be negative")
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_after = reset_after
        self._clock = clock
        self._lock = threading.Lock()
        self._state = CLOSED
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._opened_wall: Optional[str] = None
        self._probe_out = False
        self._last_error: Optional[str] = None
        self.calls = self.failures_total = self.rejected = self.opens = 0
        self.version = 0                     # bumped on every state change

    # ------------------------------------------------------------- state

    @property
    def state(self) -> str:
        with self._lock:
            return self._current()

    def _current(self) -> str:
        if self._state == OPEN and self._clock() - self._opened_at >= self.reset_after:
            self._state = HALF_OPEN
            self._probe_out = False
            self.version += 1
        return self._state

    def retry_in(self) -> float:
        """Seconds until the next probe may go out (0 when closed or half-open)."""
        with self._lock:
            if self._current() != OPEN:
                return 0.0
            return max(0.0, self.reset_after - (self._clock() - self._opened_at))

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            state = self._current()
            retry = (max(0.0, self.reset_after - (self._clock() - self._opened_at))
                     if state == OPEN else 0.0)
            return {"name": self.name, "state": state, "consecutive_failures": self._failures,
                    "failure_threshold": self.failure_threshold, "reset_after": self.reset_after,
                    "retry_in": round(retry, 1), "opened_at": self._opened_wall,
                    "last_error": self._last_error, "calls": self.calls,
                    "failures": self.failures_total, "rejected": self.rejected,
                    "opens": self.opens}

    # ------------------------------------------------------------- calls

    def before_call(self) -> None:
        """Raise CircuitOpen unless a call may go out now."""
        with self._lock:
            state = self._current()
            if state == OPEN or (state == HALF_OPEN and self._probe_out):
                self.rejected += 1
                retry = (self.reset_after - (self._clock() - self._opened_at)) if state == OPEN else 0
                raise CircuitOpen(self.name, max(0.0, retry), self._last_error)
            if state == HALF_OPEN:
                self._probe_out = True
            self.calls += 1

    def record_success(self) -> None:
        with self._lock:
            changed = self._state != CLOSED
            self._state, self._failures, self._probe_out = CLOSED, 0, False
            self._opened_at = self._opened_wall = None
            if changed:
                self.version += 1

    def record_failure(self, exc: BaseException) -> None:
        with self._lock:
            state = self._current()
            self._failures += 1
            self.failures_total += 1
            self._last_error = ("%s: %s" % (type(exc).__name__, exc))[:300]
            if state == HALF_OPEN or self._failures >= self.failure_threshold:
                self._state = OPEN
                self._opened_at = self._clock()
                self._opened_wall = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._probe_out = False
                self.opens += 1
                self.version += 1

    def call(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        """Run fn through the breaker. A provider failure that opens the
        breaker is raised as CircuitOpen (chained from it), so a caller only
        has to look for one exception to know the provider is down."""
        self.before_call()
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            if not is_outage(exc):
                with self._lock:              # a bad request says nothing about the provider
                    self._probe_out = False
                raise
            self.record_failure(exc)
            if self.state == OPEN:
                raise CircuitOpen(self.name, self.retry_in(), self._last_error) from exc
            raise
        self.record_success()
        return result

    def reset(self) -> None:
        self.record_success()
        with self._lock:
            self._last_error = None


# ------------------------------------------------------------ registry

_REGISTRY: Dict[str, CircuitBreaker] = {}
_REGISTRY_LOCK = threading.Lock()


def breaker(name: str = LLM, **kwargs) -> CircuitBreaker:
    """The process's breaker of this name, created on first use."""
    with _REGISTRY_LOCK:
        if name not in _REGISTRY:
            _REGISTRY[name] = CircuitBreaker(name, **kwargs)
        return _REGISTRY[name]


def states() -> Dict[str, Dict[str, Any]]:
    """Every breaker in this process, by name."""
    with _REGISTRY_LOCK:
        items = list(_REGISTRY.values())
    return {b.name: b.snapshot() for b in items}


# ------------------------------------------------------- client wrapper

class _GuardedMessages:
    def __init__(self, messages, guard: CircuitBreaker):
        self._messages = messages
        self._guard = guard

    def parse(self, **kwargs):
        return self._guard.call(self._messages.parse, **kwargs)

    def __getattr__(self, name):
        return getattr(self._messages, name)


class GuardedClient:
    """An Anthropic-shaped client whose `messages.parse` goes through a
    breaker. Hand it to `app.llm.client.LLM(client=...)`."""

    def __init__(self, client, guard: CircuitBreaker):
        self._client = client
        self.breaker = guard
        self.messages = _GuardedMessages(client.messages, guard)

    def __getattr__(self, name):
        return getattr(self._client, name)


def guard_client(client, guard: Optional[CircuitBreaker] = None) -> GuardedClient:
    return GuardedClient(client, guard or breaker(LLM))


def open_in_chain(exc: Optional[BaseException]) -> Optional[CircuitOpen]:
    """The CircuitOpen behind an exception (the LLM layer wraps what the
    client raises), or None."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, CircuitOpen):
            return exc
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return None


# ----------------------------------------------------------- publishing

_published: Dict[str, int] = {}


def publish(conn: Connection, names=None) -> int:
    """Write each breaker's snapshot to `sync_cursor` as `breaker:<name>`.
    Works on a lease_agent connection. Returns how many were written."""
    snaps = states()
    written = 0
    for name, snap in sorted(snaps.items()):
        if names is not None and name not in names:
            continue
        conn.execute(text("""
            INSERT INTO sync_cursor (source, cursor, at) VALUES (:s, :c, now())
            ON CONFLICT (source) DO UPDATE SET cursor = EXCLUDED.cursor, at = now()
        """), {"s": CURSOR_PREFIX + name, "c": json.dumps(snap, sort_keys=True)})
        written += 1
    return written


def publish_if_changed(eng: Engine) -> int:
    """Publish only the breakers whose state moved since the last publish
    from this process. Normal operation therefore writes nothing."""
    with _REGISTRY_LOCK:
        changed = [b.name for b in _REGISTRY.values() if _published.get(b.name) != b.version]
        versions = {b.name: b.version for b in _REGISTRY.values()}
    if not changed:
        return 0
    with eng.begin() as conn:
        written = publish(conn, set(changed))
    _published.update({n: versions[n] for n in changed})
    return written


def read_published(conn: Connection) -> Dict[str, Dict[str, Any]]:
    """What workers last published, by breaker name, with `published_at`."""
    out = {}
    for source, cursor, at in conn.execute(text(
            "SELECT source, cursor, at FROM sync_cursor WHERE source LIKE :p ORDER BY source"),
            {"p": CURSOR_PREFIX + "%"}):
        try:
            snap = json.loads(cursor)
        except (TypeError, ValueError):
            continue
        snap["published_at"] = at.isoformat() if at is not None else None
        out[source[len(CURSOR_PREFIX):]] = snap
    return out
