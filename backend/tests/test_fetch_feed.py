"""The SpacetimeDB step feed and the investigation's formatting, without a server.

LiveFeed is driven through httpx's MockTransport. The feed is decoration: it
sends in order on its own thread, drops what fails, never reaches the desk,
and is off without SPACETIME_DB and SPACETIME_TOKEN.
"""

import os

import httpx

from agents_fetch.grammar import parse
from agents_fetch.investigation_agent import frame_line, summarize
from agents_fetch.live import Feed, LiveFeed, from_env, record_step
from agents_fetch.protocol import REFUSED, Reply

FRAMES = [
    {"stage": "searching", "message": "Searching 214 documents…"},
    {"stage": "found", "source": "email", "quote": "Amendment No. 2 extends the term.", "trust_rank": 2},
    {"stage": "remeasured", "liability_delta": 443255.70, "rou_delta": 443255.70},
    {"stage": "complete", "entries": 4, "balanced": True},
]


class Recorder(Feed):
    """A feed that keeps what it was given. Shared with the platform tests."""

    enabled = True

    def __init__(self):
        self.steps = []

    def step(self, run_id, agent, kind, detail, exception_id=""):
        self.steps.append((run_id, agent, kind, detail, exception_id))


def test_live_feed_calls_record_step_in_order_with_positional_args():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers["authorization"], request.read()))
        return httpx.Response(200)

    http = httpx.Client(transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer tok"})
    feed = LiveFeed("http://stdb.test", "leasedesk-live", "tok", http=http)
    feed.step("run1", "investigation", "found", "Amendment No. 2", "exc_4")
    feed.step("run1", "approvals", "act", "approve #4: ok")
    feed.close()

    assert [p for p, _, _ in seen] == ["/v1/database/leasedesk-live/call/record_step"] * 2
    assert all(auth == "Bearer tok" for _, auth, _ in seen)
    assert seen[0][2] == b'["run1","investigation","found","Amendment No. 2","exc_4"]'
    assert seen[1][2] == b'["run1","approvals","act","approve #4: ok",""]'


def test_a_failing_feed_is_counted_and_dropped():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(530, text="no publisher")))
    feed = LiveFeed("http://stdb.test", "leasedesk-live", "tok", http=http)
    for i in range(3):
        feed.step("r", "front_desk", "typed", "inbox %d" % i)     # never raises
    feed.close()
    assert feed.failures == 3


def test_the_feed_is_off_without_a_database_or_a_token(monkeypatch):
    monkeypatch.delenv("SPACETIME_DB", raising=False)
    assert not from_env().enabled
    monkeypatch.setenv("SPACETIME_DB", "leasedesk-live")
    monkeypatch.delenv("SPACETIME_TOKEN", raising=False)
    assert not from_env().enabled


def test_a_specialist_step_never_carries_the_persons_words():
    feed = Recorder()
    record_step(feed, "run1", "approvals", parse("answer 17 my bank details are 1234"),
                Reply("Refused", outcome=REFUSED, audit_seq=9))
    [(run_id, agent, kind, detail, exc)] = feed.steps
    assert (run_id, agent, kind, exc) == ("run1", "approvals", "act", "exc_17")
    assert detail == "answer #17: refused (audit event #9)" and "1234" not in detail
    record_step(Feed(), "run1", "approvals", parse("review 1"), Reply("x"))     # off: nothing, no error


def test_investigation_frames_as_feed_lines_and_as_a_reply():
    assert [frame_line(f) for f in FRAMES] == [
        "Searching 214 documents…", "email: Amendment No. 2 extends the term.",
        "liability +$443,255.70, ROU +$443,255.70", "4 entries proposed, balanced"]
    text = summarize(42, FRAMES)
    assert "**Investigation · #42**" in text and "Amendment No. 2" in text and "(trust rank 2)" in text
    assert "liability +$443,255.70" in text and "4 adjusting entries proposed, balanced." in text
    assert "Nothing has been posted" in text


def test_the_runner_reads_dotenv_without_overriding_the_shell(tmp_path, monkeypatch):
    from agents_fetch.run import load_dotenv

    env = tmp_path / ".env"
    env.write_text('# comment\nexport S2_TEST_A="from file"\nS2_TEST_B=from file\nS2_TEST_C=\nnot a line\n')
    monkeypatch.setenv("S2_TEST_B", "from shell")
    monkeypatch.setenv("S2_TEST_C", "from shell")
    monkeypatch.delenv("S2_TEST_A", raising=False)
    load_dotenv(env)
    assert (os.environ["S2_TEST_A"], os.environ["S2_TEST_B"], os.environ["S2_TEST_C"]) == (
        "from file", "from shell", "from shell")
    monkeypatch.delenv("S2_TEST_A")


def test_an_unexplained_variance_says_so_and_an_error_is_shown():
    text = summarize(7, [{"stage": "searching"}, {"stage": "not_found"},
                         {"stage": "error", "message": "No model configured."}, {"stage": "complete", "entries": 0}])
    assert "Nothing in the mailbox explains this variance" in text and "No model configured." in text
    assert "entries proposed" not in text
