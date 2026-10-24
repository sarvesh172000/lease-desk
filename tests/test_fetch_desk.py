"""The ASI:One desk's conversation, against a fake API and the keyword reader.

No network and no uagents: fetch/desk.py and fetch/intent.py only need httpx.
"""

import pytest

from fetch.api import DeskError
from fetch.desk import Desk
from fetch.intent import by_keywords

OPEN = [
    {"exception_id": "exc_4", "lease_id": "LEASE-01", "clinic_id": "CLINIC-01", "period": "2026-01-01",
     "charge_type": "cam_estimate", "expected": 5941.67, "actual": 6458.33, "delta": 516.66,
     "status": "pending_review", "confidence": None},
    {"exception_id": "exc_7", "lease_id": "LEASE-03", "clinic_id": "CLINIC-03", "period": "2026-01-01",
     "charge_type": "base_rent", "expected": 16726.5, "actual": 17270.11, "delta": 543.61,
     "status": "pending_review", "confidence": None},
]


class FakeAPI:
    def __init__(self, refuse=None):
        self.actor = {"name": "Priya Raghunathan"}
        self.calls = []
        self.refuse = refuse

    def exceptions(self):
        return OPEN

    def exception(self, exc_id):
        e = next(x for x in OPEN if x["exception_id"] == exc_id)
        return dict(e, proposal="hold", payable=e["expected"], disputed=e["delta"],
                    reason="CAM billed above the lease's estimate",
                    lease_citation={"label": "LEASE-01 · §4.1", "quote": "Tenant shall pay its share."})

    def investigate(self, exc_id):
        yield {"stage": "searching", "message": "Searching 214 documents…"}
        yield {"stage": "found", "source": "email", "quote": "Amendment No. 2 extends the term.",
               "trust_rank": 2}
        yield {"stage": "remeasured", "liability_delta": 443255.70, "rou_delta": 443255.70}
        yield {"stage": "complete", "entries": 4, "balanced": True}

    def approve(self, exc_id, reason=None):
        if self.refuse:
            raise DeskError("approve needs the controller", self.refuse)
        self.calls.append(("approve", exc_id))
        return {"state": "POSTED", "posting": {"status": "posted", "amount": 5941.67, "disputed": 516.66}}

    def hold(self, exc_id, reason=None):
        self.calls.append(("hold", exc_id))
        return {"state": "HELD", "posting": None}


def desk(api=None):
    return Desk(api=api or FakeAPI(), read=by_keywords)


def test_lists_whats_open_with_the_api_figures():
    reply = desk().handle("a", "what's open?")
    assert "2 charges on hold" in reply
    assert "$6,458.33" in reply and "+$516.66" in reply
    assert "$1,060.27" in reply        # the two over-bills, as listed


def test_approve_waits_for_a_yes_and_says_what_posts():
    api = FakeAPI()
    d = desk(api)
    reply = d.handle("a", "approve exc_4")
    assert api.calls == []
    assert "$5,941.67" in reply and "$516.66" in reply and "yes" in reply
    done = d.handle("a", "yes")
    assert api.calls == [("approve", "exc_4")]
    assert "POSTED" in done and "Priya Raghunathan" in done


def test_without_payable_the_preview_makes_no_claim_about_money():
    api = FakeAPI()
    api.exception = lambda exc_id: dict(OPEN[1])      # an older API: no proposal, no payable
    reply = desk(api).handle("a", "approve exc_7")
    assert "$17,270.11" not in reply and "didn't say" in reply


def test_no_cancels_and_nothing_is_called():
    api = FakeAPI()
    d = desk(api)
    d.handle("a", "approve exc_4")
    assert "nothing changed" in d.handle("a", "no").lower()
    assert d.handle("a", "yes").startswith("Nothing is waiting")
    assert api.calls == []


def test_a_new_question_drops_the_pending_approval():
    api = FakeAPI()
    d = desk(api)
    d.handle("a", "approve exc_4")
    d.handle("a", "what's open?")
    d.handle("a", "yes")
    assert api.calls == []


def test_it_refers_to_the_last_exception_discussed():
    api = FakeAPI()
    d = desk(api)
    d.handle("a", "show LEASE-03")
    d.handle("a", "hold it")
    d.handle("a", "yes")
    assert api.calls == [("hold", "exc_7")]


def test_conversations_are_kept_per_sender():
    api = FakeAPI()
    d = desk(api)
    d.handle("a", "approve exc_4")
    assert d.handle("b", "yes").startswith("Nothing is waiting")
    assert api.calls == []


def test_investigation_reports_what_it_found_and_posts_nothing():
    api = FakeAPI()
    seen = []
    reply = desk(api).handle("a", "why is exc_4 off?", progress=seen.append)
    assert seen and "214 documents" in seen[0]
    assert "Amendment No. 2" in reply
    assert "+$443,255.70" in reply and "4 adjusting entries proposed, balanced" in reply
    assert api.calls == []


def test_a_refusal_is_relayed_not_hidden():
    d = desk(FakeAPI(refuse=403))
    d.handle("a", "approve exc_4")
    assert "refused" in d.handle("a", "yes")


def test_ambiguous_target_asks_which_one():
    assert desk().handle("a", "approve it").startswith("Which one?")


@pytest.mark.parametrize("text,intent,exc", [
    ("any problems this month?", "list", None),
    ("show me what's open", "list", None),
    ("why is the LEASE-01 charge off", "investigate", "exc_4"),
    ("exc_7", "show", "exc_7"),
    ("yes please", "confirm", None),
    ("hello", "help", None),
])
def test_keyword_reader(text, intent, exc):
    got = by_keywords(text, OPEN, None)
    assert (got.name, got.exception_id) == (intent, exc)
