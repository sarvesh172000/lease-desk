"""work/live.py without a database: the queue, the commit check, the HTTP
call and the switch. The Postgres side (xid status, the committed read) is
faked here and real in test_live_mirror_db.py.
"""

import json
import threading
import time

import httpx
import pytest

from app.work import live

ARGS = ["exc_7", "LEASE-01", "cam_estimate", 6458.33, 5941.67, "balanced"]


class FakeConn:
    """Just enough of a Connection for stage(): one scalar and an engine."""

    def __init__(self, xid="1234"):
        self.xid = xid
        self.engine = object()
        self.calls = 0

    def execute(self, *_args, **_kwargs):
        self.calls += 1
        return self

    def scalar(self):
        return self.xid


def recorder(status=200, fail=None):
    sent = []

    def handle(request: httpx.Request) -> httpx.Response:
        if fail is not None:
            raise fail
        sent.append(request)
        return httpx.Response(status, text="ok")
    return sent, httpx.Client(transport=httpx.MockTransport(handle),
                              headers={"Authorization": "Bearer tok"})


def mirror(http, statuses=None, read=lambda engine, item_id: list(ARGS), **kw):
    statuses = statuses if statuses is not None else {}
    return live.Mirror("https://st.example/", "leasedesk-live", "tok", http,
                       status_of=lambda engine, xid: statuses.get(xid, "committed"),
                       read=read, **kw)


@pytest.fixture(autouse=True)
def _no_process_mirror():
    token = live.use(None)
    yield
    live.reset(token)


def test_a_committed_change_is_sent_as_upsert_status_with_positional_args():
    sent, http = recorder()
    m = mirror(http)
    m.stage(FakeConn(), 7, "RM-BAY")
    assert m.flush()
    [req] = sent
    assert req.method == "POST"
    assert str(req.url) == "https://st.example/v1/database/leasedesk-live/call/upsert_status"
    assert req.headers["Authorization"] == "Bearer tok"
    assert json.loads(req.content) == ARGS + ["RM-BAY"]
    assert m.sent == 1 and m.failures == 0
    m.close()


def test_nothing_is_sent_while_the_transaction_is_open_and_it_goes_once_committed():
    sent, http = recorder()
    statuses = {"1234": "in progress"}
    m = mirror(http, statuses)
    m.stage(FakeConn("1234"), 7, "RM-BAY")
    time.sleep(0.1)
    assert sent == []
    statuses["1234"] = "committed"
    assert m.flush()
    assert len(sent) == 1
    m.close()


def test_a_rolled_back_or_forgotten_transaction_is_never_sent():
    sent, http = recorder()
    m = mirror(http, {"1": "aborted", "2": None})
    m.stage(FakeConn("1"), 7, "RM-BAY")
    m.stage(FakeConn("2"), 7, "RM-BAY")
    m.stage(FakeConn(None), 7, "RM-BAY")       # nothing written: not even queued
    assert m.flush()
    assert sent == [] and m.failures == 0
    m.close()


def test_a_transaction_that_never_finishes_is_given_up_on():
    sent, http = recorder()
    m = mirror(http, {"1": "in progress"}, commit_wait=0.05)
    m.stage(FakeConn("1"), 7, "RM-BAY")
    assert m.flush()
    assert sent == []
    m.close()


def test_other_kinds_are_skipped():
    sent, http = recorder()
    m = mirror(http, read=lambda engine, item_id: None)
    m.stage(FakeConn(), 7, "RM-BAY")
    assert m.flush()
    assert sent == []
    m.close()


@pytest.mark.parametrize("http_status,fail", [(530, None), (200, httpx.ConnectError("down"))])
def test_spacetimedb_failing_never_raises_and_the_next_change_still_goes(http_status, fail):
    sent, http = recorder(http_status, fail)
    m = mirror(http)
    m.stage(FakeConn(), 7, "RM-BAY")            # returns at once, whatever happens next
    m.stage(FakeConn(), 8, "RM-BAY")
    assert m.flush()
    assert m.failures == 2 and m.sent == 0
    m.close()


def test_a_failing_read_is_dropped_too():
    sent, http = recorder()

    def boom(engine, item_id):
        raise RuntimeError("database gone")
    m = mirror(http, read=boom)
    m.stage(FakeConn(), 7, "RM-BAY")
    assert m.flush()
    assert m.failures == 1 and sent == []
    m.close()


def test_a_slow_spacetimedb_never_slows_stage_and_a_full_queue_drops():
    gate = threading.Event()

    def slow(request):
        gate.wait(5)
        return httpx.Response(200)
    m = mirror(httpx.Client(transport=httpx.MockTransport(slow)))
    started = time.monotonic()
    for i in range(1100):                       # the queue holds 1000
        m.stage(FakeConn(), i, "RM-BAY")
    assert time.monotonic() - started < 1.0
    gate.set()
    assert m.flush(10)
    m.close()


def test_off_without_env_no_thread_no_sql(monkeypatch):
    monkeypatch.delenv("SPACETIME_DB", raising=False)
    monkeypatch.setenv("SPACETIME_TOKEN", "tok")
    live.use(live._UNSET)
    threads = threading.active_count()
    conn = FakeConn()
    live.stage(conn, 7, "RM-BAY")
    assert live.get() is None
    assert conn.calls == 0
    assert threading.active_count() == threads


def test_off_with_a_database_but_no_token(monkeypatch):
    monkeypatch.setenv("SPACETIME_DB", "leasedesk-live")
    monkeypatch.delenv("SPACETIME_TOKEN", raising=False)
    assert live.from_env() is None


def test_on_with_both(monkeypatch):
    monkeypatch.setenv("SPACETIME_DB", "leasedesk-live")
    monkeypatch.setenv("SPACETIME_TOKEN", "tok")
    monkeypatch.delenv("SPACETIME_HOST", raising=False)
    m = live.from_env()
    try:
        assert m is not None
        assert m.url == "https://maincloud.spacetimedb.com/v1/database/leasedesk-live/call/"
        assert m.http.headers["Authorization"] == "Bearer tok"
    finally:
        m.close()
