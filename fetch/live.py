"""The live feed: what the agents are doing, sent to SpacetimeDB as they do it.

Browsers subscribed to the `leasedesk-live` module (spacetime/) see each step
the moment it is recorded. The feed is decoration on top of the work, never
part of it: sends happen on a background thread in the order they were made,
a failed send is logged and dropped, and with SPACETIME_DB unset the feed is
off and costs nothing. A chat reply never waits on it.

    SPACETIME_HOST    default https://maincloud.spacetimedb.com
    SPACETIME_DB      the module's name, e.g. leasedesk-live (unset: feed off)
    SPACETIME_TOKEN   this publisher's token (python -m fetch.live identity)

Setting up a publisher, once:

    python -m fetch.live identity          # prints an identity and its token
    spacetime call leasedesk-live authorize_publisher <identity>   # as the owner
"""

import logging
import os
import queue
import sys
import threading
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

DEFAULT_HOST = "https://maincloud.spacetimedb.com"


class Feed:
    """The interface the desk writes to. This base class is the feed switched off."""

    enabled = False

    def step(self, run_id: str, agent: str, kind: str, detail: str, exception_id: str = "") -> None:
        pass

    def status(self, item: Dict[str, Any], status: str, by: str) -> None:
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
        self._send("record_step", [run_id, agent, kind, detail, exception_id or ""])

    def status(self, item: Dict[str, Any], status: str, by: str) -> None:
        self._send("upsert_status", [
            item["exception_id"], item.get("lease_id") or "", item.get("charge_type") or "",
            float(item.get("actual") or 0.0), float(item.get("expected") or 0.0), status, by])

    def close(self, timeout: float = 5.0) -> None:
        """Send what is queued, then stop. For scripts and tests; the agent never calls it."""
        self.q.put(None)
        self.thread.join(timeout)

    def _send(self, reducer: str, args: List[Any]) -> None:
        try:
            self.q.put_nowait((reducer, args))
        except queue.Full:
            # The feed is behind by a thousand lines: drop rather than slow the desk.
            log.warning("live feed queue full; dropped %s", reducer)

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


def from_env() -> Feed:
    database = os.environ.get("SPACETIME_DB")
    if not database:
        return Feed()
    token = os.environ.get("SPACETIME_TOKEN")
    if not token:
        log.warning("SPACETIME_DB is set but SPACETIME_TOKEN is not; the live feed is off")
        return Feed()
    return LiveFeed(os.environ.get("SPACETIME_HOST", DEFAULT_HOST), database, token)


def _new_identity(host: str) -> None:
    r = httpx.post("%s/v1/identity" % host.rstrip("/"), timeout=15.0)
    r.raise_for_status()
    data = r.json()
    print("identity: %s" % data["identity"])
    print("token:    %s" % data["token"])
    print()
    print("Keep the token secret: put it in SPACETIME_TOKEN. Then, as the module's owner:")
    print("    spacetime call <database> authorize_publisher %s" % data["identity"])


if __name__ == "__main__":
    if sys.argv[1:] != ["identity"]:
        raise SystemExit("usage: python -m fetch.live identity")
    _new_identity(os.environ.get("SPACETIME_HOST", DEFAULT_HOST))
