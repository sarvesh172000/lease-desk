"""The live feed: each agent's steps, sent to SpacetimeDB as they happen.

Browsers subscribed to the `leasedesk-live` module (spacetime/) see each step
the moment an agent records it, which is what makes four agents working on
one chat message visible. Every step of one message carries the same run id
(the front desk picks it and hands it to the specialist), and each agent
records its own steps under its own name.

The feed is decoration on top of the work, never part of it: sends happen on
one background thread in the order they were made, a failed send is logged
and dropped, and with SPACETIME_DB or SPACETIME_TOKEN unset the feed is off
and costs nothing. A chat reply never waits on it.

The agents write `agent_step` only. `desk_status` (the state of each item) is
published by the backend after every transition, so it is never out of step
with Postgres because an agent guessed.

    SPACETIME_HOST    default https://maincloud.spacetimedb.com
    SPACETIME_DB      the module's name, e.g. leasedesk-live (unset: feed off)
    SPACETIME_TOKEN   this publisher's token (python -m agents_fetch.live identity)

Setting up a publisher, once:

    python -m agents_fetch.live identity                           # an identity and its token
    spacetime call leasedesk-live authorize_publisher <identity>   # as the module's owner
"""

import logging
import os
import queue
import sys
import threading
from typing import Any, List, Optional

import httpx

log = logging.getLogger(__name__)

DEFAULT_HOST = "https://maincloud.spacetimedb.com"
MAX_DETAIL = 500


class Feed:
    """What the agents write to. This base class is the feed switched off."""

    enabled = False

    def step(self, run_id: str, agent: str, kind: str, detail: str, exception_id: str = "") -> None:
        pass

    def close(self, timeout: float = 5.0) -> None:
        pass


class LiveFeed(Feed):
    enabled = True

    def __init__(self, host: str, database: str, token: str, http: Optional[httpx.Client] = None):
        self.url = "%s/v1/database/%s/call/" % (host.rstrip("/"), database)
        self.http = http or httpx.Client(timeout=5.0, headers={"Authorization": "Bearer %s" % token})
        self.q: "queue.Queue[Optional[tuple]]" = queue.Queue(maxsize=1000)
        self.failures = 0
        self.thread = threading.Thread(target=self._drain, name="spacetime-feed", daemon=True)
        self.thread.start()

    def step(self, run_id: str, agent: str, kind: str, detail: str, exception_id: str = "") -> None:
        self.send("record_step", [run_id or "", agent, kind, (detail or "")[:MAX_DETAIL], exception_id or ""])

    def send(self, reducer: str, args: List[Any]) -> None:
        """Queue one reducer call. Never blocks and never raises."""
        try:
            self.q.put_nowait((reducer, args))
        except queue.Full:
            # The feed is behind by a thousand lines: drop rather than slow the desk.
            log.warning("live feed queue full; dropped %s", reducer)

    def close(self, timeout: float = 5.0) -> None:
        """Send what is queued, then stop. For scripts and tests; the agents never call it."""
        self.q.put(None)
        self.thread.join(timeout)

    def _drain(self) -> None:
        while True:
            job = self.q.get()
            if job is None:
                return
            reducer, args = job
            try:
                r = self.http.post(self.url + reducer, json=args)
                if r.status_code >= 400:
                    raise RuntimeError("%d %s" % (r.status_code, r.text[:200]))
            except Exception as exc:     # noqa: BLE001 - a feed failure must never reach the desk
                self.failures += 1
                # Say so the first time and then now and again, not on every line.
                if self.failures == 1 or self.failures % 50 == 0:
                    log.warning("live feed: %s failed (%d so far): %s", reducer, self.failures, exc)


def record_step(feed: Optional[Feed], run_id: str, agent: str, command: Any, reply: Any) -> None:
    """A specialist's one step for one request: what it was asked and how it
    came out. Never the free text (a reason, an answer, a question): the
    agent_step table is public, and the words are on the audit trail."""
    if feed is None or not feed.enabled:
        return
    item = getattr(command, "item_id", None)
    what = getattr(command, "verb", None) or getattr(command, "name", "?")
    target = "#%d" % item if item else (getattr(command, "lease_ref", None) or "")
    seq = getattr(reply, "audit_seq", None)
    feed.step(run_id, agent, getattr(command, "name", "?"),
              "%s %s: %s%s" % (what, target, getattr(reply, "outcome", "?"),
                               " (audit event #%d)" % seq if seq is not None else ""),
              "exc_%d" % item if item else "")


def from_env() -> Feed:
    database = os.environ.get("SPACETIME_DB", "").strip()
    if not database:
        return Feed()
    token = os.environ.get("SPACETIME_TOKEN", "").strip()
    if not token:
        log.warning("SPACETIME_DB is set but SPACETIME_TOKEN is not; the live feed is off")
        return Feed()
    return LiveFeed(os.environ.get("SPACETIME_HOST", DEFAULT_HOST), database, token)


def _new_identity(host: str) -> None:  # pragma: no cover - talks to SpacetimeDB
    r = httpx.post("%s/v1/identity" % host.rstrip("/"), timeout=15.0)
    r.raise_for_status()
    data = r.json()
    print("identity: %s" % data["identity"])
    print("token:    %s" % data["token"])
    print()
    print("Keep the token secret: put it in SPACETIME_TOKEN. Then, as the module's owner:")
    print("    spacetime call <database> authorize_publisher %s" % data["identity"])


if __name__ == "__main__":  # pragma: no cover
    if sys.argv[1:] != ["identity"]:
        raise SystemExit("usage: python -m agents_fetch.live identity")
    _new_identity(os.environ.get("SPACETIME_HOST", DEFAULT_HOST))
