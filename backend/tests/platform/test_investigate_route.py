"""POST /api/exceptions/{id}/investigate — §16 #5, the stream behind the timeline.

The agent itself is covered in test_modification.py. What matters here is the
wiring: that the four stages go out in order, that what was found is recorded
on the work item so the screen still has it after a reload, and that a run
which cannot reach a model says so on the stream rather than 500ing.

The model is a fake throughout. A test that needed the network would be a test
that stopped working on a train.
"""

import json
import sys
from pathlib import Path

import pytest
from test_api_read import (  # noqa: F401 — fixtures
    client,
    generated,
    insert_work_item,
    seeded,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fakes import FakeClient, FakeResponse  # noqa: E402

from app.agents import investigation_run  # noqa: E402
from app.agents.modification import AmendmentSearch, Candidate  # noqa: E402
from app.llm.cache import ResponseCache  # noqa: E402
from app.llm.client import LLM  # noqa: E402
from app.llm.registry import PromptRegistry  # noqa: E402
from app.llm.usage import UsageLog  # noqa: E402

THE_AMENDMENT = AmendmentSearch(
    none_explain=False,
    note="Searched the mailbox.",
    candidates=[Candidate(
        source_id="eml-20260618-amend", explains_variance=True,
        claim="Base rent reduced to $17,400 from 1 July 2026",
        quote="Base rent reduced to $17,400 per month effective July 1, 2026.",
        effective="2026-07-01", new_monthly_rent=17_400.00,
        new_expiration="2031-12-31", new_escalation_pct=0.025)],
)

NOTHING_FOUND = AmendmentSearch(
    none_explain=True, note="Nothing in the corpus accounts for it.", candidates=[])


@pytest.fixture
def fake_model(monkeypatch, tmp_path):
    """Point the route's model at a fake, with a cache of its own."""
    def use(result):
        monkeypatch.setattr(
            investigation_run, "build_llm",
            lambda: LLM(registry=PromptRegistry(), cache=ResponseCache(tmp_path / "c"),
                        usage=UsageLog(), client=FakeClient(lambda kw: FakeResponse(result))))
    return use


@pytest.fixture
def july_variance(seeded):
    """The July amendment variance, as the checker would have left it."""
    return insert_work_item(
        seeded["owner"], state="PROPOSED", subject_id="jul", clinic_id="CLINIC-01",
        period="2026-07-01",
        evidence={"lease_id": "LEASE-01", "charge_type": "base_rent",
                  "billed": 17_400.00, "supported": 19_626.65})


def stages(response) -> list:
    """The parsed `data:` events of an SSE body, in order."""
    out = []
    for block in response.text.split("\n\n"):
        line = block.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[len("data:"):].strip()))
    return out


# --- the stream -------------------------------------------------------------------

def test_streams_the_four_stages_in_order(client, july_variance, fake_model):
    fake_model(THE_AMENDMENT)
    res = client.post("/api/exceptions/exc_%d/investigate" % july_variance)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert [e["stage"] for e in stages(res)] == ["searching", "found", "remeasured", "complete"]


def test_the_stages_carry_what_the_screen_draws(client, july_variance, fake_model):
    fake_model(THE_AMENDMENT)
    found, remeasured, complete = stages(
        client.post("/api/exceptions/exc_%d/investigate" % july_variance))[1:]

    assert found["doc_id"] == "eml-20260618-amend"
    assert "17,400" in found["quote"]
    assert 0.0 < found["confidence"] <= 1.0
    # The engine's numbers, not the agent's: a remeasurement of this lease
    # raises the liability, and the entries balance.
    assert remeasured["liability_delta"] > 0
    assert complete["entries"] >= 2 and complete["balanced"] is True


def test_nothing_found_is_a_short_stream_not_an_error(client, july_variance, fake_model):
    """Unexplained is a valid outcome: searched, found nothing, proposed nothing."""
    fake_model(NOTHING_FOUND)
    found = stages(client.post("/api/exceptions/exc_%d/investigate" % july_variance))
    assert [e["stage"] for e in found] == ["searching"]
    body = client.get("/api/exceptions/exc_%d" % july_variance).json()
    assert body["investigation"]["explains_variance"] is False
    assert body["investigation"]["entries"] == []
    assert body["investigation"]["root_cause"] == "unexplained"


# --- what it leaves behind --------------------------------------------------------

def test_the_finding_is_recorded_on_the_item(client, july_variance, fake_model):
    """After the stream, the detail endpoint carries the investigation: the
    screen survives a reload and the approval is against the same figures."""
    before = client.get("/api/exceptions/exc_%d" % july_variance).json()
    assert before["investigation"] is None

    fake_model(THE_AMENDMENT)
    client.post("/api/exceptions/exc_%d/investigate" % july_variance)

    inv = client.get("/api/exceptions/exc_%d" % july_variance).json()["investigation"]
    assert inv["root_cause"] == "amendment"
    assert inv["explains_variance"] is True
    assert inv["balanced"] is True
    assert len(inv["evidence"]) == 1
    assert inv["evidence"][0]["trust_rank"] == 1
    assert inv["liability_after"] > inv["liability_before"]
    assert sum(e["debit"] for e in inv["entries"]) == pytest.approx(
        sum(e["credit"] for e in inv["entries"]), abs=0.01)


def test_recording_does_not_discard_the_checker_s_evidence(client, july_variance, fake_model,
                                                           seeded):
    fake_model(THE_AMENDMENT)
    client.post("/api/exceptions/exc_%d/investigate" % july_variance)
    with seeded["owner"].connect() as conn:
        from sqlalchemy import text
        evidence = conn.execute(
            text("SELECT evidence FROM work_item WHERE id = :id"),
            {"id": july_variance}).scalar_one()
    assert evidence["lease_id"] == "LEASE-01", "the checker's own findings survive"
    assert evidence["billed"] == 17_400.00
    assert "investigation" in evidence


# --- when it cannot run -----------------------------------------------------------

def test_no_model_is_a_stage_not_a_500(client, july_variance, monkeypatch):
    def no_model():
        raise investigation_run.NoModel("nothing cached and no key")
    monkeypatch.setattr(investigation_run, "build_llm", no_model)
    res = client.post("/api/exceptions/exc_%d/investigate" % july_variance)
    assert res.status_code == 200
    [event] = stages(res)
    assert event["stage"] == "error" and "cached" in event["message"]


def test_a_cold_cache_reads_as_missing_credentials(client, july_variance, monkeypatch):
    """A 401 from the API means the question was never cached, not that the
    investigation is broken; the message has to say which."""
    def unauthorized():
        raise RuntimeError("ANTHROPIC_API_KEY missing or rejected: Error code: 401")
    monkeypatch.setattr(investigation_run, "build_llm", unauthorized)
    [event] = stages(client.post("/api/exceptions/exc_%d/investigate" % july_variance))
    assert event["stage"] == "error"
    assert "ANTHROPIC_API_KEY" in event["message"]


def test_unknown_exception_is_404(client):
    assert client.post("/api/exceptions/exc_99999/investigate").status_code == 404
    assert client.post("/api/exceptions/nonsense/investigate").status_code == 404
