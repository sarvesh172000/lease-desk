"""The specialists and the coordinator's view of them, without uAgents.

`RemoteDesk` is wired straight to `specialists.handle` here, standing in for
the agent-to-agent messages agents.py sends; everything else is the real code.
"""

from fetch import specialists
from fetch.desk import Desk
from fetch.intent import by_keywords
from fetch.remote import RemoteDesk
from tests.test_fetch_desk import FakeAPI
from tests.test_fetch_live import Recorder


def wired(api=None, feed=None):
    """A desk whose API is the three specialists, as the coordinator sees them."""
    api = api or FakeAPI()
    feed = feed or Recorder()
    asked = []

    def call(agent, op, args):
        asked.append((agent, op))
        return specialists.handle(agent, api, feed, op, args)

    desk = Desk(api=RemoteDesk(call), read=by_keywords, live=feed)
    return desk, api, feed, asked


def test_each_question_goes_to_the_specialist_for_it():
    desk, _, _, asked = wired()
    desk.handle("a", "what's open?")
    desk.handle("a", "why is exc_4 off?")
    desk.handle("a", "approve it")
    desk.handle("a", "yes")
    assert [a for a in asked if a != ("reconciliation", "open")] == [
        ("investigation", "investigate"),
        ("reconciliation", "detail"),
        ("approvals", "approve"),
    ]


def test_the_investigation_agent_records_its_own_frames_once():
    desk, _, feed, _ = wired()
    seen = []
    reply = desk.handle("a", "why is exc_4 off?", progress=seen.append)
    assert "Investigation agent" in seen[0]
    assert "Amendment No. 2" in reply
    by_agent = [(s[1], s[2]) for s in feed.steps]
    assert by_agent == [("coordinator", "intent"), ("investigation", "searching"), ("investigation", "found"),
                        ("investigation", "remeasured"), ("investigation", "complete")]
    assert len({s[0] for s in feed.steps}) == 1     # one run, across two agents


def test_the_approvals_agent_records_the_action_and_status():
    desk, api, feed, _ = wired()
    desk.handle("a", "approve exc_4")
    reply = desk.handle("a", "yes")
    assert api.calls == [("approve", "exc_4")]
    assert "Priya Raghunathan" in reply and "POSTED" in reply
    assert feed.steps[-1][1:3] == ("approvals", "action")
    assert feed.statuses == [("exc_4", "", "Priya Raghunathan")]


def test_a_refusal_keeps_its_status_across_agents():
    desk, _, _, _ = wired(api=FakeAPI(refuse=403))
    desk.handle("a", "approve exc_4")
    assert "refused" in desk.handle("a", "yes")


def test_a_specialist_only_does_its_own_job():
    reply = specialists.handle("reconciliation", FakeAPI(), Recorder(), "approve", {"exception_id": "exc_4"})
    assert reply == {"ok": False, "status": 400, "error": "the reconciliation agent does not do 'approve'"}


def test_a_bad_request_is_answered_not_raised():
    reply = specialists.handle("reconciliation", FakeAPI(), Recorder(), "detail", {})
    assert reply["ok"] is False and reply["status"] == 400
