"""The SpacetimeDB live feed: what the desk records, and what goes over the wire.

No SpacetimeDB server: LiveFeed is driven through httpx's MockTransport.
"""

import httpx

from fetch.desk import Desk
from fetch.intent import by_keywords
from fetch.live import Feed, LiveFeed, from_env
from tests.test_fetch_desk import OPEN, FakeAPI


class Recorder(Feed):
    enabled = True

    def __init__(self):
        self.steps = []
        self.statuses = []

    def step(self, run_id, agent, kind, detail, exception_id=""):
        self.steps.append((run_id, agent, kind, detail, exception_id))

    def status(self, item, status, by):
        self.statuses.append((item["exception_id"], status, by))


def test_an_investigation_is_recorded_step_by_step_under_one_run():
    feed = Recorder()
    Desk(api=FakeAPI(), read=by_keywords, live=feed).handle("a", "why is exc_4 off?")
    kinds = [s[2] for s in feed.steps]
    assert kinds == ["intent", "searching", "found", "remeasured", "complete"]
    assert len({s[0] for s in feed.steps}) == 1
    assert all(s[4] == "exc_4" for s in feed.steps)
    assert "Amendment No. 2" in feed.steps[2][3]
    assert feed.steps[3][3] == "liability +$443,255.70, ROU +$443,255.70"


def test_each_message_is_its_own_run():
    feed = Recorder()
    d = Desk(api=FakeAPI(), read=by_keywords, live=feed)
    d.handle("a", "show exc_4")
    d.handle("a", "show exc_7")
    assert feed.steps[0][0] != feed.steps[1][0]


def test_an_approval_updates_the_status_with_who_did_it():
    feed = Recorder()
    d = Desk(api=FakeAPI(), read=by_keywords, live=feed)
    d.handle("a", "approve exc_4")
    assert feed.statuses == []           # proposing changes nothing
    d.handle("a", "yes")
    assert feed.statuses == [("exc_4", "", "Priya Raghunathan")]
    assert feed.steps[-1][2] == "action" and "POSTED" in feed.steps[-1][3]


def test_listing_syncs_every_open_status():
    feed = Recorder()
    Desk(api=FakeAPI(), read=by_keywords, live=feed).handle("a", "what's open?")
    assert feed.statuses == [("exc_4", "pending_review", "sync"), ("exc_7", "pending_review", "sync")]


def test_live_feed_calls_the_reducers_in_order_with_positional_args():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers["authorization"], request.read()))
        return httpx.Response(200)

    http = httpx.Client(transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer tok"})
    feed = LiveFeed("http://stdb.test", "leasedesk-live", "tok", http=http)
    feed.step("run1", "investigation", "found", "Amendment No. 2", "exc_4")
    feed.status(OPEN[0], "balanced", "Priya")
    feed.close()

    assert [p for p, _, _ in seen] == ["/v1/database/leasedesk-live/call/record_step",
                                       "/v1/database/leasedesk-live/call/upsert_status"]
    assert all(auth == "Bearer tok" for _, auth, _ in seen)
    assert seen[0][2] == b'["run1","investigation","found","Amendment No. 2","exc_4"]'
    assert seen[1][2] == b'["exc_4","LEASE-01","cam_estimate",6458.33,5941.67,"balanced","Priya"]'


def test_a_failing_feed_never_reaches_the_desk():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(530, text="no publisher")))
    feed = LiveFeed("http://stdb.test", "leasedesk-live", "tok", http=http)
    reply = Desk(api=FakeAPI(), read=by_keywords, live=feed).handle("a", "why is exc_4 off?")
    feed.close()
    assert "Amendment No. 2" in reply
    assert feed.failures == 5


def test_the_feed_is_off_without_a_database_or_a_token(monkeypatch):
    monkeypatch.delenv("SPACETIME_DB", raising=False)
    assert not from_env().enabled
    monkeypatch.setenv("SPACETIME_DB", "leasedesk-live")
    monkeypatch.delenv("SPACETIME_TOKEN", raising=False)
    assert not from_env().enabled
