"""POST /api/exceptions/{id}/investigate — §16 #5, the stream behind the timeline.

The agent itself is covered in test_modification.py. What matters here is the
wiring: that the four stages go out in order, that what was found is recorded
on the work item so the screen still has it after a reload, and that a run
which cannot reach a model says so on the stream rather than 500ing.

The model is a fake throughout. A test that needed the network would be a test
that stopped working on a train.
"""

import copy
import json
import sys
import threading
from datetime import date
from pathlib import Path

import lease_world as lw
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
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
from app.api.exceptions import investigation_runner, sse_delay  # noqa: E402
from app.jobs.lease_versions import confirmed_rules  # noqa: E402
from app.llm.cache import ResponseCache  # noqa: E402
from app.llm.client import LLM  # noqa: E402
from app.llm.registry import PromptRegistry  # noqa: E402
from app.llm.usage import UsageLog  # noqa: E402
from app.work.roles import load_actor  # noqa: E402
from app.work.transitions import transition  # noqa: E402

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

EXTENSION_ONLY = AmendmentSearch(
    none_explain=False,
    note="Found an executed extension with no rent change.",
    candidates=[Candidate(
        source_id="eml-20260618-amend", explains_variance=True,
        claim="Lease term extended through 2031 with existing rent unchanged",
        quote="The lease term is extended through December 31, 2031.",
        effective="2026-07-01", new_expiration="2031-12-31")],
)

MIXED_SOURCES = AmendmentSearch(
    none_explain=False,
    note="Found the instrument and two conflicting messages.",
    candidates=[
        THE_AMENDMENT.candidates[0].model_copy(deep=True),
        Candidate(
            source_id="eml-20260622-pm-claim", explains_variance=True,
            claim="Rent adjusted to $10,400", quote="Rent is now $10,400 per month.",
            effective="2026-07-01", new_monthly_rent=10_400.00,
        ),
        Candidate(
            source_id="eml-20260701-forged", explains_variance=True,
            claim="Rent adjusted to $1,400", quote="Rent is now $1,400 per month.",
            effective="2026-07-01", new_monthly_rent=1_400.00,
        ),
    ],
)


@pytest.fixture(autouse=True)
def unpaced(client):
    """No pause between frames: the pacing is for people, not tests."""
    client.app.dependency_overrides[sse_delay] = lambda: 0.0


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
        seeded["owner"], state="PROPOSED", subject_id="jul", clinic_id="STORE-01",
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


def test_the_detail_links_the_lease_change_it_proposed(
        client, july_variance, seeded, generated, fake_model):
    """The page needs the controller's approval item and its state, read fresh."""
    lw.draft_and_confirm(seeded, generated)
    fake_model(THE_AMENDMENT)
    stages(client.post("/api/exceptions/exc_%d/investigate" % july_variance))
    link = client.get("/api/exceptions/exc_%d" % july_variance).json()["modification"]
    assert link is not None and link["state"] == "PROPOSED"
    assert link["version"] >= 2 and link["item_id"] != july_variance
    with seeded["lease_reader"].connect() as conn:
        kind = conn.execute(text("SELECT kind FROM work_item WHERE id = :id"),
                            {"id": link["item_id"]}).scalar_one()
    assert kind == "LEASE_MODIFICATION"


def test_nothing_found_is_a_short_stream_not_an_error(client, july_variance, fake_model):
    """Unexplained is a valid outcome: searched, found nothing, proposed nothing."""
    fake_model(NOTHING_FOUND)
    found = stages(client.post("/api/exceptions/exc_%d/investigate" % july_variance))
    assert [e["stage"] for e in found] == ["searching", "not_found", "complete"]
    assert found[-1] == {"stage": "complete", "entries": 0, "balanced": None}
    body = client.get("/api/exceptions/exc_%d" % july_variance).json()
    assert body["investigation"]["explains_variance"] is False
    assert body["investigation"]["entries"] == []
    assert body["investigation"]["root_cause"] == "unexplained"
    assert body["modification"] is None


def test_nothing_found_can_open_the_resolvers_question(
        client, seeded, fake_model):
    item_id = insert_work_item(
        seeded["owner"], state="PROPOSED", subject_id="ask-only",
        clinic_id="STORE-01", period="2026-07-01",
        evidence={"lease_id": "LEASE-01", "charge_type": "base_rent", "billed": 100.0},
    )
    with seeded["owner"].begin() as conn:
        conn.execute(text("""
            UPDATE work_item SET entity_id = 'ENT-CA', region_id = 'REG-BAY'
             WHERE id = :id
        """), {"id": item_id})
    fake_model(NOTHING_FOUND)
    first = stages(client.post("/api/exceptions/exc_%d/investigate" % item_id))

    with seeded["lease_reader"].connect() as conn:
        item = conn.execute(text(
            "SELECT state, evidence FROM work_item WHERE id = :id"),
            {"id": item_id}).mappings().one()
        question = conn.execute(text("""
            SELECT asked_to, asked_by, body, due_at FROM question WHERE work_item_id = :id
        """), {"id": item_id}).mappings().one()
        event = conn.execute(text("""
            SELECT actor_id, action, diff FROM audit_event
             WHERE subject_type = 'work_item' AND subject_id = :id
             ORDER BY seq DESC LIMIT 1
        """), {"id": str(item_id)}).mappings().one()
    assert item["state"] == "NEEDS_INFO"
    assert item["evidence"]["decision"]["action"] == "ask"
    assert (question["asked_to"], question["asked_by"]) == (
        "PER-RM-BAY", "agent:investigation")
    assert question["body"] and question["due_at"] is not None
    assert (event["actor_id"], event["action"]) == ("agent:investigation", "ask")

    # Once recorded, NEEDS_INFO does not block deterministic replay.
    assert stages(client.post("/api/exceptions/exc_%d/investigate" % item_id)) == first


@pytest.mark.parametrize("state", ["HELD", "NEEDS_INFO"])
def test_an_unrecordable_state_is_rejected_before_agent_work(
        client, july_variance, seeded, state):
    with seeded["owner"].begin() as conn:
        conn.execute(text("UPDATE work_item SET state = :state WHERE id = :id"),
                     {"state": state, "id": july_variance})
    calls = []

    def should_not_run(**kwargs):
        calls.append(kwargs)
        raise AssertionError("agent should not run")

    client.app.dependency_overrides[investigation_runner] = lambda: should_not_run
    response = client.post("/api/exceptions/exc_%d/investigate" % july_variance)
    assert response.status_code == 409
    assert "only while it awaits review" in response.json()["detail"]
    assert calls == []


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
        evidence = conn.execute(
            text("SELECT evidence FROM work_item WHERE id = :id"),
            {"id": july_variance}).scalar_one()
        event = conn.execute(text("""
            SELECT actor_id, action, allowed, diff, evidence
              FROM audit_event
             WHERE subject_type = 'work_item' AND subject_id = :id
             ORDER BY seq DESC LIMIT 1
        """), {"id": str(july_variance)}).mappings().one()
    assert evidence["lease_id"] == "LEASE-01", "the checker's own findings survive"
    assert evidence["billed"] == 17_400.00
    assert evidence["investigation"]["root_cause"] == "amendment"
    source = next(s for s in evidence["sources"] if s["kind"] == "amendment")
    assert (source["rank"], source["value"]) == (1, 17_400.00)
    assert evidence["decision"]["trusted"] == "eml-20260618-amend"
    assert evidence["decision"]["action"] == "proceed"
    assert evidence["route"]["role"] == "controller"
    assert (event["actor_id"], event["action"], event["allowed"]) == (
        "agent:investigation", "propose", True)
    assert event["diff"]["from"] == event["diff"]["to"] == "PROPOSED"
    assert event["diff"]["set"]["evidence"] == evidence
    assert event["evidence"]["trusted_source"] == "eml-20260618-amend"


def test_resolver_refresh_keeps_every_ranked_investigation_source(
        client, july_variance, fake_model, seeded):
    fake_model(MIXED_SOURCES)
    response = client.post("/api/exceptions/exc_%d/investigate" % july_variance)
    assert response.status_code == 200
    with seeded["lease_reader"].connect() as conn:
        evidence = conn.execute(text(
            "SELECT evidence FROM work_item WHERE id = :id"),
            {"id": july_variance}).scalar_one()

    sources = {source["source_id"]: source for source in evidence["sources"]}
    assert sources["eml-20260618-amend"]["value"] == 17_400.00
    assert sources["eml-20260622-pm-claim"]["value"] == 10_400.00
    assert sources["eml-20260701-forged"]["value"] == 1_400.00
    assert sources["eml-20260701-forged"]["suspect"] is True
    decision = evidence["decision"]
    assert decision["trusted"] == "eml-20260618-amend"
    assert "eml-20260622-pm-claim" in decision["contradicting"]
    assert "eml-20260701-forged" in decision["set_aside"]
    assert any("set aside" in reason.lower()
               for reason in evidence["confidence_reasons"])


# --- when it cannot run -----------------------------------------------------------

def test_no_model_is_a_stage_not_a_500(client, july_variance, monkeypatch):
    def no_model():
        raise investigation_run.NoModel("nothing cached and no key")
    monkeypatch.setattr(investigation_run, "build_llm", no_model)
    res = client.post("/api/exceptions/exc_%d/investigate" % july_variance)
    assert res.status_code == 200
    got = stages(res)
    # The checker's own evidence (no clause cited on this item), then why the
    # mailbox was not searched; no remeasurement is made up.
    assert [e["stage"] for e in got] == ["searching", "not_found", "error"]
    assert "cached" in got[-1]["message"]


def test_a_cold_cache_reads_as_missing_credentials(client, july_variance, monkeypatch):
    """A 401 from the API means the question was never cached, not that the
    investigation is broken; the message has to say which."""
    def unauthorized():
        raise RuntimeError("ANTHROPIC_API_KEY missing or rejected: Error code: 401")
    monkeypatch.setattr(investigation_run, "build_llm", unauthorized)
    event = stages(client.post("/api/exceptions/exc_%d/investigate" % july_variance))[-1]
    assert event["stage"] == "error"
    assert "ANTHROPIC_API_KEY" in event["message"]


def test_a_second_run_replays_what_was_recorded(client, july_variance, fake_model, monkeypatch):
    """Once recorded, the investigation is replayed, not asked again: the same
    frames, with no model at all."""
    fake_model(THE_AMENDMENT)
    first = stages(client.post("/api/exceptions/exc_%d/investigate" % july_variance))

    def no_model():
        raise investigation_run.NoModel("must not be asked")
    monkeypatch.setattr(investigation_run, "build_llm", no_model)
    again = stages(client.post("/api/exceptions/exc_%d/investigate" % july_variance))
    assert again == first


def test_concurrent_investigations_both_stream_the_persisted_winner(
        client, july_variance, seeded, generated, fake_model):
    lw.draft_and_confirm(seeded, generated)
    fake_model(THE_AMENDMENT)
    base, _ = investigation_run.run(
        lease_id="LEASE-01", period=date(2026, 7, 1),
        expected=19_626.65, actual=17_400.00, delta=-2_226.65,
    )
    first, second = copy.deepcopy(base), copy.deepcopy(base)
    first.searched = 101
    first.reasons.append("race candidate one")
    second.searched = 202
    second.reasons.append("race candidate two")
    candidates = [first, second]
    lock = threading.Lock()
    both_finished_model_work = threading.Barrier(2)

    def run(**kwargs):
        with lock:
            result = candidates.pop(0)
        both_finished_model_work.wait(timeout=10)
        return result, result.searched

    client.app.dependency_overrides[investigation_runner] = lambda: run
    responses, errors = [], []

    def request():
        try:
            with TestClient(client.app) as peer:
                responses.append(stages(peer.post(
                    "/api/exceptions/exc_%d/investigate" % july_variance)))
        except Exception as exc:  # noqa: BLE001 - surfaced below with both threads joined
            errors.append(exc)

    threads = [threading.Thread(target=request) for _ in range(2)]
    [thread.start() for thread in threads]
    [thread.join(20) for thread in threads]
    assert not any(thread.is_alive() for thread in threads), "investigation race deadlocked"
    assert errors == []
    assert len(responses) == 2 and responses[0] == responses[1]

    with seeded["lease_reader"].connect() as conn:
        evidence = conn.execute(text(
            "SELECT evidence FROM work_item WHERE id = :id"),
            {"id": july_variance}).scalar_one()
        events = conn.execute(text("""
            SELECT count(*) FROM audit_event
             WHERE subject_type = 'work_item' AND subject_id = :id
               AND actor_id = 'agent:investigation' AND action = 'propose' AND allowed
        """), {"id": str(july_variance)}).scalar_one()
        versions = conn.execute(text("""
            SELECT count(*) FROM lease_version
             WHERE lease_id = 'LEASE-01' AND version = 2
        """)).scalar_one()
        items = conn.execute(text("""
            SELECT count(*) FROM work_item WHERE kind = 'LEASE_MODIFICATION'
        """)).scalar_one()
    winner = evidence["investigation"]["searched"]
    assert winner in (101, 202)
    assert responses[0][0]["message"] == "Searching %d documents…" % winner
    loser = 202 if winner == 101 else 101
    assert '"searched": %d' % loser not in json.dumps(evidence, sort_keys=True)
    assert (events, versions, items) == (1, 1, 1)


def test_a_stale_investigation_result_is_not_recorded(
        client, july_variance, seeded, fake_model):
    # Real checker-created items already have an event sequence. Give this
    # lightweight raw fixture the same baseline before the route snapshots it.
    with seeded["lease_agent"].begin() as conn:
        transition(conn, load_actor(conn, "agent:checker"), july_variance, "propose",
                   reason="Initial checker result.")
    fake_model(THE_AMENDMENT)
    result, searched = investigation_run.run(
        lease_id="LEASE-01", period=date(2026, 7, 1),
        expected=19_626.65, actual=17_400.00, delta=-2_226.65,
    )

    def run(**kwargs):
        with seeded["lease_agent"].begin() as conn:
            transition(conn, load_actor(conn, "agent:checker"), july_variance, "propose",
                       reason="A newer checker result arrived.")
        return result, searched

    client.app.dependency_overrides[investigation_runner] = lambda: run
    stream = stages(client.post("/api/exceptions/exc_%d/investigate" % july_variance))
    assert stream[-1]["stage"] == "error"
    assert "could not be recorded" in stream[-1]["message"]
    assert client.get(
        "/api/exceptions/exc_%d" % july_variance).json()["investigation"] is None
    with seeded["lease_reader"].connect() as conn:
        recorded = conn.execute(text("""
            SELECT count(*) FROM audit_event
             WHERE subject_type = 'work_item' AND subject_id = :id
               AND actor_id = 'agent:investigation' AND action = 'propose'
        """), {"id": str(july_variance)}).scalar_one()
        versions = conn.execute(text(
            "SELECT count(*) FROM lease_version WHERE version > 1")).scalar_one()
    assert (recorded, versions) == (0, 0)


def test_a_non_rent_amendment_does_not_invent_a_monetary_source(
        client, july_variance, seeded, generated, fake_model):
    lw.draft_and_confirm(seeded, generated)
    fake_model(EXTENSION_ONLY)
    response = client.post("/api/exceptions/exc_%d/investigate" % july_variance)
    assert response.status_code == 200

    with seeded["lease_reader"].connect() as conn:
        evidence = conn.execute(text(
            "SELECT evidence FROM work_item WHERE id = :id"),
            {"id": july_variance}).scalar_one()
        modification = conn.execute(text("""
            SELECT id, subject_id, evidence FROM work_item
             WHERE kind = 'LEASE_MODIFICATION'
        """)).mappings().one()
        versions = conn.execute(text("""
            SELECT v.version, t.value
              FROM lease_version v JOIN lease_term t ON t.lease_version_id = v.id
             WHERE v.lease_id = 'LEASE-01' AND t.field = 'base_rent_monthly'
             ORDER BY v.version
        """)).all()
    amendment = next(source for source in evidence["sources"]
                     if source["kind"] == "amendment")
    assert amendment["value"] is None
    assert evidence["decision"]["trusted"].startswith("lease:LEASE-01")
    assert evidence["decision"]["action"] == "hold"
    assert "base_rent_monthly" not in modification["evidence"]["changed_terms"]
    assert [row.version for row in versions] == [1, 2]
    assert float(versions[0].value) == float(versions[1].value) == 18_500.00
    schedule = client.get("/api/leases/LEASE-01/schedule", params={"version": 2}).json()
    july = next(row for row in schedule["rows"] if row["period"] == "2026-07-01")
    january = next(row for row in schedule["rows"] if row["period"] == "2027-01-01")
    assert (july["payment"], january["payment"]) == (19_626.65, 20_215.45)

    # Mark the synthetic fixture as gateway-posted to isolate checker rule
    # composition. An expiration-only v2 must preserve the same anniversaries.
    with seeded["owner"].begin() as conn:
        conn.execute(text("""
            UPDATE lease_version SET confirmed_by = 'PER-CTRL', confirmed_at = now()
             WHERE id = :version
        """), {"version": int(modification["subject_id"])})
        conn.execute(text("UPDATE work_item SET state = 'POSTED' WHERE id = :item"),
                     {"item": modification["id"]})
    with seeded["lease_reader"].connect() as conn:
        rule = confirmed_rules(conn, "ENT-CA", as_of=date(2027, 1, 1)).rules["LEASE-01"]
    assert rule.rent_for(date(2026, 7, 1)) == 19_626.65
    assert rule.rent_for(date(2027, 1, 1)) == 20_215.45
    assert rule.expiration == date(2031, 12, 31)


def test_unknown_exception_is_404(client):
    assert client.post("/api/exceptions/exc_99999/investigate").status_code == 404
    assert client.post("/api/exceptions/nonsense/investigate").status_code == 404
