"""The live mirror: committed work-item state, pushed to SpacetimeDB.

Every open screen subscribes to the `leasedesk-live` module (spacetime/), so
when one person approves an exception, every other window's queue row and
tiles change with no refresh. This is a mirror, never the books: Postgres
holds the state, nothing reads the mirror back to decide anything, and an
approval never waits on it, fails because of it, or rolls back for it.

How a change gets out, and why it cannot block an approval:

1. In the caller's transaction, transition() / create_item() call stage().
   With the mirror off that is one `is None` test. With it on, stage() reads
   `pg_current_xact_id_if_assigned()` (a pure function that cannot fail once
   the event row is written) and puts (engine, item, xid) on an in-memory
   queue without blocking. Nothing is sent from inside the transaction.
2. A daemon thread drains the queue in order. For each job it asks Postgres
   `pg_xact_status(xid)` on a connection of its own: `committed` -> it reads
   the item's *committed* row the way GET /api/exceptions does and calls the
   `upsert_status` reducer; `aborted` -> it drops the job; `in progress` ->
   it waits. So a rolled-back approval, or a gateway posting whose deferred
   balance check fails at COMMIT, is never mirrored, and what is mirrored is
   exactly what the API would answer at that moment.
3. Any failure on the thread (SpacetimeDB down or slow, a 4xx, the read) is
   logged now and again and dropped. The queue is bounded; when full, new
   jobs are dropped rather than waiting.

SQLAlchemy Core has no after-commit hook (its `commit` event fires *before*
the COMMIT), which is why the commit is confirmed from Postgres instead.

    SPACETIME_HOST    default https://maincloud.spacetimedb.com
    SPACETIME_DB      the module's name, e.g. leasedesk-live (unset: mirror off)
    SPACETIME_TOKEN   an authorized publisher's token (spacetime/README.md)

Only CHARGE_CHECK items are mirrored, as `exc_<work_item.id>`: that is what
the queue and the dashboard show. Other kinds are skipped on the thread.
"""

import logging
import os
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

log = logging.getLogger(__name__)

DEFAULT_HOST = "https://maincloud.spacetimedb.com"

# How long the thread waits for a transaction to finish before giving up on
# it. Requests commit in milliseconds; a month run's transaction can be long.
COMMIT_WAIT_SECONDS = 600.0

Job = Tuple[Engine, int, str, str]       # engine, work item id, xid, actor id


def xact_status(engine: Engine, xid: str) -> Optional[str]:
    """'committed', 'aborted', 'in progress', or None when Postgres no longer
    knows the transaction (far too old to matter)."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT pg_xact_status(CAST(:x AS xid8))"), {"x": xid}).scalar()


def read_status(engine: Engine, item_id: int) -> Optional[List[Any]]:
    """The `upsert_status` arguments for a charge check's committed row, or
    None for any other kind. The figures are flattened by the same code that
    answers GET /api/exceptions, so the mirror cannot disagree with the API."""
    from ..api.exceptions import _SELECT, _flatten  # lazy: the API imports this layer

    with engine.connect() as conn:
        row = conn.execute(text(_SELECT + " AND w.id = :id"), {"id": item_id}).mappings().first()
    if row is None:
        return None
    flat = _flatten(row)
    return [flat["exception_id"], flat["lease_id"] or "", flat["charge_type"] or "",
            float(flat["actual"] or 0.0), float(flat["expected"] or 0.0), flat["status"]]


class Mirror:
    """A running mirror: one bounded queue, one daemon thread, one HTTP client."""

    def __init__(self, host: str, database: str, token: str, http: Optional[httpx.Client] = None, *,
                 status_of: Callable[[Engine, str], Optional[str]] = xact_status,
                 read: Callable[[Engine, int], Optional[List[Any]]] = read_status,
                 commit_wait: float = COMMIT_WAIT_SECONDS):
        self.url = "%s/v1/database/%s/call/" % (host.rstrip("/"), database)
        self.http = http or httpx.Client(timeout=5.0, headers={"Authorization": "Bearer %s" % token})
        self.status_of = status_of
        self.read = read
        self.commit_wait = commit_wait
        self.q: "queue.Queue[Optional[Job]]" = queue.Queue(maxsize=1000)
        self.failures = 0
        self.sent = 0
        self.thread = threading.Thread(target=self._drain, name="spacetime-mirror", daemon=True)
        self.thread.start()

    def stage(self, conn: Connection, item_id: int, actor_id: str) -> None:
        """Called inside the caller's transaction. Never raises, never blocks."""
        try:
            xid = conn.execute(text("SELECT CAST(pg_current_xact_id_if_assigned() AS text)")).scalar()
        except Exception:     # noqa: BLE001 - the mirror must never reach the desk
            log.warning("live mirror: could not read the transaction id; item %s not mirrored", item_id)
            return
        if xid is None:       # nothing was written, so nothing will commit
            return
        try:
            self.q.put_nowait((conn.engine, int(item_id), xid, actor_id))
        except queue.Full:
            log.warning("live mirror queue full; dropped work item %s", item_id)

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until everything queued so far has been handled. For tests and
        scripts; the desk never calls it."""
        deadline = time.monotonic() + timeout
        while self.q.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        return not self.q.unfinished_tasks

    def close(self, timeout: float = 5.0) -> None:
        self.q.put(None)
        self.thread.join(timeout)

    def _drain(self) -> None:
        while True:
            job = self.q.get()
            try:
                if job is None:
                    return
                self._handle(job)
            except Exception as exc:     # noqa: BLE001 - a mirror failure must never reach the desk
                self.failures += 1
                # Say so the first time and then now and again, not on every line.
                if self.failures == 1 or self.failures % 50 == 0:
                    log.warning("live mirror: failed (%d so far): %s", self.failures, exc)
            finally:
                self.q.task_done()

    def _handle(self, job: Job) -> None:
        engine, item_id, xid, actor_id = job
        if not self._committed(engine, xid):
            return
        args = self.read(engine, item_id)
        if args is None:
            return
        r = self.http.post(self.url + "upsert_status", json=args + [actor_id])
        if r.status_code >= 400:
            raise RuntimeError("upsert_status %d %s" % (r.status_code, r.text[:200]))
        self.sent += 1

    def _committed(self, engine: Engine, xid: str) -> bool:
        deadline = time.monotonic() + self.commit_wait
        pause = 0.005
        while True:
            status = self.status_of(engine, xid)
            if status != "in progress":
                return status == "committed"
            if time.monotonic() > deadline:
                log.warning("live mirror: transaction %s still open after %.0fs; not mirrored",
                            xid, self.commit_wait)
                return False
            time.sleep(pause)
            pause = min(pause * 2, 0.5)


def from_env() -> Optional[Mirror]:
    database = os.environ.get("SPACETIME_DB")
    if not database:
        return None
    token = os.environ.get("SPACETIME_TOKEN")
    if not token:
        log.warning("SPACETIME_DB is set but SPACETIME_TOKEN is not; the live mirror is off")
        return None
    return Mirror(os.environ.get("SPACETIME_HOST", DEFAULT_HOST), database, token)


# The process's mirror, made on first use (after any fork) from the
# environment. `_UNSET` until then, None when off.
_UNSET: Any = object()
_mirror: Any = _UNSET
_lock = threading.Lock()


def get() -> Optional[Mirror]:
    global _mirror
    if _mirror is _UNSET:
        with _lock:
            if _mirror is _UNSET:
                _mirror = from_env()
    return _mirror


def use(mirror: Optional[Mirror]) -> Dict[str, Any]:
    """Install a mirror (or None for off) for this process; returns a token
    for reset(). For tests."""
    global _mirror
    previous = {"mirror": _mirror}
    _mirror = mirror
    return previous


def reset(previous: Dict[str, Any]) -> None:
    global _mirror
    _mirror = previous["mirror"]


def stage(conn: Connection, item_id: int, actor_id: str) -> None:
    """transition()'s and create_item()'s one line. Off: nothing at all."""
    mirror = get()
    if mirror is not None:
        mirror.stage(conn, item_id, actor_id)
