"""The moment, end to end, with no model: the demo's whole story replays from
the answers committed in data/reference/llm_cache.

The world is built the way `make demo-data` builds it: January generated,
seeded, the leases confirmed and checked; then July generated, seeded and
checked. STORE-01's amendment takes effect in July, so July's rent is billed
$2,226.65 under the schedule and held. Investigating that hold, with no key
and an empty cache of its own, must find the amendment in the mailbox and
remeasure the lease to the figures the pitch quotes.

If this fails after a change to a prompt, a schema or the documents, the
committed answers no longer match: re-run the warm-up with a key (see
data/reference/llm_cache/README.md) and commit the new files.
"""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import lease_world as lw
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import items as items_api
from app.api.deps import get_agent_engine, get_data_dir, get_engine, get_gateway_engine
from app.api.exceptions import sse_delay
from app.api.why import get_reader_engine
from app.auth.deps import current_actor
from app.auth.sessions import SessionActor
from app.jobs.lease_versions import confirmed_rules
from app.jobs.monthly import run_month
from app.jobs.worker import drain
from app.llm import client as llm_client
from app.llm.client import REPLAY_DIR
from app.main import create_app
from app.records.seed import seed
from app.work import modifications, obligations
from app.work.events import events_for, verify_chain
from app.work.gateway import post_approved, post_approved_modification
from app.work.replay import replay

ROOT = Path(__file__).resolve().parents[3]
ENTITY = "ENT-CA"
CONTROLLER = SessionActor(id="PER-CTRL", name="Priya Raghunathan", role="controller",
                          region_id=None, entity_id=None)
REGIONAL_MANAGER = SessionActor(id="PER-RM-BAY", name="Dana Whitfield",
                                role="regional_manager", region_id="REG-BAY", entity_id=None)
INVESTIGATION_AGENT = SessionActor(id="agent:investigation", name="Investigation agent",
                                   role="agent", region_id=None, entity_id=None)


def generate(out: Path, month: str) -> None:
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(out), "--month", month],
                   cwd=ROOT, check=True, capture_output=True)


def run(engines, month: str) -> None:
    with engines["lease_agent"].begin() as conn:
        run_month(conn, ENTITY, month)
    drain(engines["lease_agent"], "moment-test")


@pytest.fixture
def july(clean, tmp_path, monkeypatch):
    """January then July, as `make demo-data` runs them."""
    generated = tmp_path / "generated"
    lw.use_documents(monkeypatch, generated)
    generate(generated, "2026-01")
    seed(generated, clean["lease_agent"], clean["lease_gateway"])
    run(clean, "2026-01")
    lw.confirm(clean)
    run(clean, "2026-01")
    generate(generated, "2026-07")
    seed(generated, clean["lease_agent"], clean["lease_gateway"])
    run(clean, "2026-07")
    return clean, generated


@pytest.fixture
def client(july, tmp_path, monkeypatch):
    engines, generated = july
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # A cache of its own, empty: only the committed answers can serve.
    monkeypatch.setattr(llm_client, "_default_cache_dir", lambda: str(tmp_path / "empty-cache"))
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engines["lease_api"]
    app.dependency_overrides[get_agent_engine] = lambda: engines["lease_agent"]
    app.dependency_overrides[get_gateway_engine] = lambda: engines["lease_gateway"]
    app.dependency_overrides[get_reader_engine] = lambda: engines["lease_reader"]
    app.dependency_overrides[current_actor] = lambda: CONTROLLER
    app.dependency_overrides[get_data_dir] = lambda: Path(generated)
    app.dependency_overrides[sse_delay] = lambda: 0.0
    return TestClient(app)


def frames(response) -> list:
    return [json.loads(block.strip()[len("data:"):])
            for block in response.text.split("\n\n") if block.strip().startswith("data:")]


def test_the_committed_answers_are_in_the_repository():
    assert any(REPLAY_DIR.rglob("*.json")), "data/reference/llm_cache is empty"


def test_july_holds_exactly_the_amended_rent(client):
    july = [e for e in client.get("/api/exceptions").json() if e["period"] == "2026-07-01"]
    assert [(e["lease_id"], e["charge_type"], e["expected"], e["actual"]) for e in july] == [
        ("LEASE-01", "base_rent", 19_626.65, 17_400.00)]


def test_the_investigation_finds_the_amendment_and_remeasures_with_no_model(client):
    exc = next(e["exception_id"] for e in client.get("/api/exceptions").json()
               if e["period"] == "2026-07-01")
    stream = frames(client.post("/api/exceptions/%s/investigate" % exc))

    assert [f["stage"] for f in stream] == ["searching", "found", "remeasured", "complete"]
    found = stream[1]
    assert found["doc_id"] == "eml-20260618-amend" and found["trust_rank"] == 1
    assert "$17,400 per month effective July 1, 2026" in found["quote"]
    assert stream[2]["liability_delta"] == 443_255.70
    assert stream[3] == {"stage": "complete", "entries": 4, "balanced": True}

    detail = client.get("/api/exceptions/%s" % exc).json()["investigation"]
    assert (detail["liability_before"], detail["liability_after"]) == (559_665.35, 1_002_921.05)
    assert sum(e["debit"] for e in detail["entries"]) == pytest.approx(447_880.44)
    assert detail["balanced"] is True


def test_the_investigation_is_auditable_approvable_and_rechecks_july(client, july):
    engines, _ = july
    reader = engines["lease_reader"]
    exc = next(e["exception_id"] for e in client.get("/api/exceptions").json()
               if e["period"] == "2026-07-01")
    charge_item_id = int(exc.removeprefix("exc_"))

    stream = frames(client.post("/api/exceptions/%s/investigate" % exc))
    assert [f["stage"] for f in stream] == ["searching", "found", "remeasured", "complete"]

    with reader.connect() as conn:
        charge = conn.execute(text("SELECT * FROM work_item WHERE id = :id"),
                              {"id": charge_item_id}).mappings().one()
        versions = conn.execute(text("""
            SELECT * FROM lease_version WHERE lease_id = 'LEASE-01' ORDER BY version
        """)).mappings().all()
        modification = conn.execute(text("""
            SELECT * FROM work_item WHERE kind = 'LEASE_MODIFICATION'
             AND subject_type = 'lease_version'
        """)).mappings().one()
        events = events_for(conn, "work_item", charge_item_id)
        terms = {r.field: r for r in conn.execute(text("""
            SELECT field, value, quote, document_id, page
              FROM lease_term WHERE lease_version_id = :version
        """), {"version": versions[-1]["id"]})}

    assert [v["version"] for v in versions] == [1, 2]
    assert versions[-1]["confirmed_by"] is None
    assert (modification["state"], modification["proposal"]) == ("PROPOSED", "approve")
    assert modification["evidence"]["source_charge_item_id"] == charge_item_id
    assert terms["base_rent_monthly"].value == 17_400.00
    assert terms["expiration"].value == "2031-12-31"
    assert "17,400" in terms["base_rent_monthly"].quote
    assert terms["base_rent_monthly"].document_id is None
    assert terms["base_rent_monthly"].page is None
    draft_schedule = client.get("/api/leases/LEASE-01/schedule", params={"version": 2})
    assert draft_schedule.status_code == 200, draft_schedule.text
    assert (draft_schedule.json()["version"], draft_schedule.json()["confirmed"]) == (2, False)
    assert draft_schedule.json()["rows"][0]["payment"] == 17_400.00

    recorded = events[-1]
    assert (recorded.actor_id, recorded.action, recorded.allowed) == (
        "agent:investigation", "propose", True)
    assert recorded.diff["from"] == recorded.diff["to"] == "PROPOSED"
    assert recorded.diff["set"]["evidence"]["investigation"]["root_cause"] == "amendment"
    evidence = charge["evidence"]
    amendment = next(s for s in evidence["sources"] if s["kind"] == "amendment")
    assert (amendment["rank"], amendment["source_id"], amendment["value"]) == (
        1, "eml-20260618-amend", 17_400.00)
    assert evidence["decision"]["trusted"] == amendment["source_id"]
    assert evidence["decision"]["action"] == "proceed"
    assert evidence["route"]["role"] == "controller"

    sources = client.get("/api/items/%d/sources" % charge_item_id).json()
    assert sources["decision"]["trusted"] == "eml-20260618-amend"
    assert any(s["kind"] == "amendment" and s["rank"] == 1 for s in sources["sources"])
    why = client.get("/api/items/%d/why" % charge_item_id).json()["answer"]
    assert "Northbay Coffee" in why and "base rent" in why
    assert "amendment" in why and "rank 1" in why

    with engines["owner"].connect() as conn:
        with conn.begin() as tx:
            report = replay(conn)
            tx.rollback()
    assert report.identical, report.differences

    modification_id = modification["id"]
    client.app.dependency_overrides[current_actor] = lambda: REGIONAL_MANAGER
    assert client.post("/api/items/%d/actions/approve" % modification_id).status_code == 403
    client.app.dependency_overrides[current_actor] = lambda: INVESTIGATION_AGENT
    assert client.post("/api/items/%d/actions/approve" % modification_id).status_code == 403

    client.app.dependency_overrides[current_actor] = lambda: CONTROLLER
    for field, value in (
        ("entries", [{"account": "Lease liability", "debit": 1, "credit": 0}]),
        ("lease_version_id", versions[0]["id"]),
        ("balanced", False),
    ):
        refused = client.post(
            "/api/items/%d/actions/approve" % modification_id,
            json={"reason": "tampered proposal", "patch": {field: value}},
        )
        assert refused.status_code == 422, (field, refused.text)
        assert "proposal is immutable" in refused.json()["detail"]
    with reader.connect() as conn:
        untouched = conn.execute(text(
            "SELECT state FROM work_item WHERE id = :id"), {"id": modification_id}).scalar_one()
        confirmed = conn.execute(text(
            "SELECT confirmed_by FROM lease_version WHERE id = :id"),
            {"id": versions[-1]["id"]}).scalar_one()
        allowed_approvals = conn.execute(text("""
            SELECT count(*) FROM audit_event
             WHERE subject_type = 'work_item' AND subject_id = :id
               AND action = 'approve' AND allowed
        """), {"id": str(modification_id)}).scalar_one()
        rechecks = conn.execute(text(
            "SELECT count(*) FROM job WHERE kind = 'modification_recheck'")).scalar_one()
    assert (untouched, confirmed, allowed_approvals, rechecks) == ("PROPOSED", None, 0, 0)

    approved = client.post("/api/items/%d/actions/approve" % modification_id,
                           json={"reason": "Executed amendment and balanced entry reviewed."})
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["state"] == "POSTED" and body["posting"]["status"] == "posted"
    entry_id = body["posting"]["journal_entry_id"]

    with engines["lease_gateway"].begin() as conn:
        assert post_approved_modification(conn, modification_id) == entry_id
    with reader.connect() as conn:
        count, lines, debits, credits = conn.execute(text("""
            SELECT count(DISTINCT e.id), count(l.id), sum(l.debit), sum(l.credit)
              FROM journal_entry e JOIN journal_line l ON l.journal_entry_id = e.id
             WHERE e.work_item_id = :item
        """), {"item": modification_id}).one()
        confirmed = conn.execute(text("""
            SELECT confirmed_by FROM lease_version WHERE id = :version
        """), {"version": versions[-1]["id"]}).scalar_one()
        recheck = conn.execute(text("""
            SELECT status, payload FROM job
             WHERE kind = 'modification_recheck'
        """)).mappings().one()
        january_rules = confirmed_rules(conn, ENTITY, as_of=date(2026, 1, 1))
        july_rules = confirmed_rules(conn, ENTITY, as_of=date(2026, 7, 1))
    assert (count, lines, float(debits), float(credits)) == (1, 4, 447_880.44, 447_880.44)
    assert confirmed == CONTROLLER.id
    assert recheck["status"] == "queued"
    assert recheck["payload"]["modification_item_id"] == modification_id
    assert january_rules.versions["LEASE-01"] == versions[0]["id"]
    assert july_rules.versions["LEASE-01"] == versions[-1]["id"]

    from app.jobs.clock import set_today

    with engines["lease_agent"].begin() as conn:
        set_today(conn, date(2026, 7, 1))
    schedule = client.get("/api/leases/LEASE-01/schedule").json()
    assert (schedule["version"], schedule["confirmed"], schedule["active"]) == (2, True, True)
    assert schedule["rows"][0]["payment"] == 17_400.00

    outcomes = drain(engines["lease_agent"], "moment-modification")
    rechecks = [o for o in outcomes if o.job.kind == "modification_recheck"]
    assert len(rechecks) == 1 and rechecks[0].status == "done"
    assert rechecks[0].result["revised"] >= 1
    detail = client.get("/api/exceptions/%s" % exc).json()
    assert (detail["expected"], detail["actual"], detail["delta"], detail["proposal"]) == (
        17_400.00, 17_400.00, 0.0, "approve")
    refreshed_sources = client.get("/api/items/%d/sources" % charge_item_id).json()
    assert refreshed_sources["decision"]["trusted"] == "eml-20260618-amend"

    charge_approval = client.post("/api/exceptions/%s/approve" % exc,
                                  json={"reason": "Charge agrees with confirmed v2."})
    assert charge_approval.status_code == 200, charge_approval.text
    assert (charge_approval.json()["status"], charge_approval.json()["state"]) == (
        "balanced", "POSTED")
    assert all(e["exception_id"] != exc for e in client.get("/api/exceptions").json())

    with reader.connect() as conn:
        denied = conn.execute(text("""
            SELECT actor_id FROM audit_event
             WHERE subject_type = 'work_item' AND subject_id = :item
               AND action = 'approve' AND NOT allowed ORDER BY seq
        """), {"item": str(modification_id)}).scalars().all()
        assert denied == [REGIONAL_MANAGER.id, INVESTIGATION_AGENT.id]
        assert verify_chain(conn) is None
    with engines["owner"].connect() as conn:
        with conn.begin() as tx:
            report = replay(conn)
            tx.rollback()
    assert report.identical, report.differences


def test_modification_approval_rolls_back_when_recheck_cannot_be_scheduled(
        client, july, monkeypatch):
    engines, _ = july
    exc = next(e["exception_id"] for e in client.get("/api/exceptions").json()
               if e["period"] == "2026-07-01")
    client.post("/api/exceptions/%s/investigate" % exc)
    with engines["lease_reader"].connect() as conn:
        modification = conn.execute(text("""
            SELECT id, subject_id FROM work_item
             WHERE kind = 'LEASE_MODIFICATION'
        """)).mappings().one()

    def fail_schedule(conn, item_id):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(modifications, "schedule_recheck", fail_schedule)
    with pytest.raises(RuntimeError, match="queue unavailable"):
        client.post(
            "/api/items/%d/actions/approve" % modification["id"],
            json={"reason": "The amendment is valid."},
        )

    with engines["lease_reader"].connect() as conn:
        state = conn.execute(text(
            "SELECT state FROM work_item WHERE id = :id"), modification).scalar_one()
        confirmed = conn.execute(text(
            "SELECT confirmed_by FROM lease_version WHERE id = :id"),
            {"id": int(modification["subject_id"])}).scalar_one()
        jobs = conn.execute(text(
            "SELECT count(*) FROM job WHERE kind = 'modification_recheck'")).scalar_one()
        approvals = conn.execute(text("""
            SELECT count(*) FROM audit_event
             WHERE subject_type = 'work_item' AND subject_id = :id
               AND action = 'approve' AND allowed
        """), {"id": str(modification["id"])}).scalar_one()
        entries = conn.execute(text(
            "SELECT count(*) FROM journal_entry WHERE work_item_id = :id"),
            modification).scalar_one()
    assert (state, confirmed, jobs, approvals, entries) == ("PROPOSED", None, 0, 0, 0)


def test_pending_modification_is_inactive_and_gateway_sweep_recovers_from_events(
        client, july, monkeypatch):
    engines, _ = july
    exc = next(e["exception_id"] for e in client.get("/api/exceptions").json()
               if e["period"] == "2026-07-01")
    client.post("/api/exceptions/%s/investigate" % exc)
    with engines["lease_reader"].connect() as conn:
        versions = conn.execute(text("""
            SELECT id, version FROM lease_version
             WHERE lease_id = 'LEASE-01' ORDER BY version
        """)).mappings().all()
        modification = conn.execute(text("""
            SELECT * FROM work_item WHERE kind = 'LEASE_MODIFICATION'
        """)).mappings().one()

    monkeypatch.setattr(
        items_api, "_post",
        lambda gateway_engine, item_id: items_api.Posting(
            status="pending", error="simulated gateway outage"),
    )
    approved = client.post(
        "/api/items/%d/actions/approve" % modification["id"],
        json={"reason": "Executed amendment reviewed."},
    )
    assert approved.status_code == 200, approved.text
    assert (approved.json()["state"], approved.json()["posting"]["status"]) == (
        "APPROVED", "pending")

    # No person may close around the failed gateway post, no regional manager
    # may decide controller-routed modification work, and no later action may
    # replace the proposal the controller approved.
    assert client.post(
        "/api/items/%d/actions/close" % modification["id"]).status_code == 403
    patched_hold = client.post(
        "/api/items/%d/actions/hold" % modification["id"],
        json={"reason": "pause", "patch": {"evidence": {"entries": []}}},
    )
    assert patched_hold.status_code == 422
    assert "proposal is immutable" in patched_hold.json()["detail"]
    client.app.dependency_overrides[current_actor] = lambda: REGIONAL_MANAGER
    for action in ("hold", "reject", "resume", "close"):
        assert client.post(
            "/api/items/%d/actions/%s" % (modification["id"], action)).status_code == 403
    client.app.dependency_overrides[current_actor] = lambda: CONTROLLER

    with engines["lease_reader"].connect() as conn:
        before = confirmed_rules(conn, ENTITY, as_of=date(2026, 7, 1))
        terms, source = obligations.lease_terms(conn, "LEASE-01")
        job = conn.execute(text("""
            SELECT id, status, attempts FROM job
             WHERE kind = 'modification_recheck'
        """)).mappings().one()
    assert before.versions["LEASE-01"] == versions[0]["id"]
    assert source == "lease_term"
    assert terms["expiration"].lease_version_id == versions[0]["id"]
    assert terms["expiration"].value == "2028-12-31"
    draft = client.get("/api/leases/LEASE-01/schedule", params={"version": 2}).json()
    assert draft["confirmed"] is False

    [held] = drain(engines["lease_agent"], "pending-modification")
    assert (held.job.kind, held.status) == ("modification_recheck", "held")
    with engines["lease_reader"].connect() as conn:
        waiting = conn.execute(text(
            "SELECT status, attempts, last_error FROM job WHERE id = :id"),
            {"id": job["id"]}).mappings().one()
    assert (waiting["status"], waiting["attempts"]) == ("queued", 0)
    assert "waiting for gateway posting" in waiting["last_error"]

    # Simulate a privileged projection edit after approval. The gateway must
    # still post the immutable proposal event the controller reviewed.
    malicious = dict(modification["evidence"])
    malicious.update({
        "lease_version_id": versions[0]["id"],
        "balanced": True,
        "changed_terms": {},
        "entries": [
            {"account": "Lease liability", "debit": 1.0, "credit": 0.0},
            {"account": "ROU asset", "debit": 0.0, "credit": 1.0},
        ],
    })
    with engines["owner"].begin() as conn:
        conn.execute(text("""
            UPDATE work_item SET evidence = CAST(:evidence AS jsonb) WHERE id = :id
        """), {"id": modification["id"], "evidence": json.dumps(malicious)})

    with engines["lease_gateway"].begin() as conn:
        posted = post_approved(conn, ENTITY, modification["period"])
    assert [p.work_item_id for p in posted] == [modification["id"]]
    entry_id = posted[0].journal_entry_id
    assert entry_id is not None
    with engines["lease_reader"].connect() as conn:
        total = conn.execute(text(
            "SELECT sum(debit) FROM journal_line WHERE journal_entry_id = :id"),
            {"id": entry_id}).scalar_one()
        after = confirmed_rules(conn, ENTITY, as_of=date(2026, 7, 1))
        terms, _ = obligations.lease_terms(conn, "LEASE-01")
    assert float(total) == 447_880.44
    assert after.versions["LEASE-01"] == versions[-1]["id"]
    assert terms["expiration"].lease_version_id == versions[-1]["id"]
    assert terms["expiration"].value == "2031-12-31"
    posted_schedule = client.get(
        "/api/leases/LEASE-01/schedule", params={"version": 2}).json()
    assert posted_schedule["rows"][0]["payment"] == 17_400.00

    with engines["lease_gateway"].begin() as conn:
        assert post_approved(conn, ENTITY, modification["period"]) == []
        assert post_approved_modification(conn, modification["id"]) == entry_id
    with engines["lease_agent"].begin() as conn:
        conn.execute(text("UPDATE job SET run_after = now() WHERE id = :id"),
                     {"id": job["id"]})
    [done] = drain(engines["lease_agent"], "recovered-modification")
    assert (done.job.kind, done.status) == ("modification_recheck", "done")
    assert done.result["revised"] >= 1


def test_the_portfolio_is_read_as_of_july_once_the_clock_says_so(client, july):
    from app.jobs.clock import set_today

    engines, _ = july
    with engines["lease_agent"].begin() as conn:
        set_today(conn, date(2026, 7, 1))
    assert client.get("/api/summary").json()["as_of"] == "2026-07-01"
