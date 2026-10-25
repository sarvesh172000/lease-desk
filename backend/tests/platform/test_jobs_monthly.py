"""jobs/monthly.py and handlers.py: the month's three jobs, the bridge from
generator charge ids to database ids, and findings becoming work items.

Findings go through the real work layer (`app.work.transitions`) on the
worker's own `lease_agent` connection, so these tests also prove that role's
grants are enough to create and propose work, and that every item starts
with a hash-chained event.
"""

import subprocess
import sys
from datetime import date
from pathlib import Path

import lease_world as lw
import pytest
from sqlalchemy import text

from app.agents.checker import APPROVE, Charge, Finding
from app.engine.charges import Proof
from app.jobs import handlers
from app.jobs.handlers import HandlerError, ingest
from app.jobs.monthly import (
    MonthlyRunError,
    charge_ids_by_source_id,
    check_period,
    job_key,
    load_charges,
    parse_period,
    record_findings,
    run_month,
)
from app.jobs.worker import drain
from app.records.ingest import stable_id
from app.records.seed import seed
from app.work.events import events_for, verify_chain
from app.work.roles import UnknownActor

ROOT = Path(__file__).resolve().parents[3]
JAN = date(2026, 1, 1)
ENTITY = "ENT-CA"


# ---------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("generated")
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    return out


@pytest.fixture
def seeded(clean, generated, monkeypatch):
    seed(Path(generated), clean["lease_agent"], clean["lease_gateway"])
    lw.use_documents(monkeypatch, generated)
    return clean


@pytest.fixture
def confirmed(seeded, generated):
    """Seeded, with the five leases drafted and confirmed by the Bay Area
    manager: the checker reads only confirmed lease versions."""
    lw.draft_and_confirm(seeded, generated)
    return seeded


CHECKS = "SELECT count(*) FROM work_item WHERE kind = 'CHARGE_CHECK'"


@pytest.fixture
def agent(clean):
    return clean["lease_agent"]


def q(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _charge(cid="INV-1-L1", **kw):
    base = dict(charge_id=cid, invoice_id="INV-1", lease_id="LEASE-01", clinic_id="STORE-01",
                period=JAN, charge_type="base_rent", suite="Suite 100", amount=100.0)
    base.update(kw)
    return Charge(**base)


# ------------------------------------------------------------------ periods

@pytest.mark.parametrize("value", ["2026-01", "2026-01-01", " 2026-01 ", date(2026, 1, 1)])
def test_parse_period_accepts_a_month(value):
    assert parse_period(value) == JAN


@pytest.mark.parametrize("value", ["2026-13", "2026-1", "2026-01-15", "January", "", None,
                                   202601, date(2026, 1, 15)])
def test_parse_period_refuses_anything_else(value):
    with pytest.raises(MonthlyRunError):
        parse_period(value)


def test_job_keys_name_entity_month_and_step():
    assert job_key("ENT-CA", JAN, "checking") == "run_month:ENT-CA:2026-01:checking"


# --------------------------------------------------------------- run_month

def test_run_month_enqueues_three_chained_jobs(seeded):
    agent = seeded["lease_agent"]
    with agent.begin() as conn:
        ids = run_month(conn, ENTITY, "2026-01")
    assert list(ids) == ["ingest", "abstraction", "checking"]
    with agent.connect() as conn:
        rows = {r.kind: r for r in conn.execute(text("SELECT * FROM job"))}
    assert rows["ingest"].depends_on == []
    assert rows["abstraction"].depends_on == [ids["ingest"]]
    assert rows["checking"].depends_on == [ids["abstraction"]]
    assert rows["checking"].idempotency_key == "run_month:ENT-CA:2026-01:checking"
    assert rows["checking"].payload == {"entity_id": ENTITY, "period": "2026-01-01"}


def test_running_a_month_twice_enqueues_nothing_new(seeded):
    agent = seeded["lease_agent"]
    with agent.begin() as conn:
        first = run_month(conn, ENTITY, JAN)
    with agent.begin() as conn:
        second = run_month(conn, ENTITY, "2026-01-01")
    assert first == second
    assert q(agent, "SELECT count(*) FROM job") == 3


def test_run_month_for_an_unknown_entity_is_refused(agent):
    with agent.begin() as conn, pytest.raises(MonthlyRunError, match="unknown entity 'ENT-XX'"):
        run_month(conn, "ENT-XX", JAN)


def test_run_month_with_a_bad_period_enqueues_nothing(seeded):
    agent = seeded["lease_agent"]
    with agent.begin() as conn, pytest.raises(MonthlyRunError, match="YYYY-MM"):
        run_month(conn, ENTITY, "2026-1")
    assert q(agent, "SELECT count(*) FROM job") == 0


# ------------------------------------------------------- the id bridge

def test_charges_load_with_the_generators_ids(seeded):
    with seeded["lease_agent"].connect() as conn:
        charges = load_charges(conn, ENTITY, JAN)
    assert len(charges) == 12
    assert "SERRA-202601-0001-L1" in {c.charge_id for c in charges}
    assert all(isinstance(c.amount, float) for c in charges)
    assert round(sum(c.amount for c in charges), 2) == 112759.69


def test_generator_ids_map_back_to_landlord_charge_ids(seeded):
    with seeded["lease_agent"].connect() as conn:
        charges = load_charges(conn, ENTITY, JAN)
        ids = charge_ids_by_source_id(conn, [c.charge_id for c in charges] + ["NOPE-L9"])
        db_ids = set(conn.execute(text(
            "SELECT id FROM landlord_charge WHERE period = '2026-01-01'")).scalars())
    assert ids["SERRA-202601-0001-L1"] == stable_id("ap_export", "SERRA-202601-0001-L1")
    assert set(ids.values()) == db_ids
    assert "NOPE-L9" not in ids


def test_no_charges_for_another_entity_or_month(seeded):
    with seeded["lease_agent"].connect() as conn:
        assert load_charges(conn, "ENT-NONE", JAN) == []
        assert load_charges(conn, ENTITY, date(2030, 1, 1)) == []
        assert charge_ids_by_source_id(conn, []) == {}


# ------------------------------------------------------ record_findings

def test_record_findings_proposes_one_item_per_charge_as_the_checker(confirmed):
    agent = confirmed["lease_agent"]
    with agent.begin() as conn:
        counts = check_period(conn, ENTITY, JAN)
    assert counts["charges"] == counts["findings"] == counts["created"] == 12
    assert counts["holds"] == 5
    assert q(agent, "SELECT count(*) FROM work_item WHERE state = 'PROPOSED' "
                    "AND kind = 'CHARGE_CHECK' AND subject_type = 'landlord_charge'") == 12
    assert q(agent, CHECKS + " AND proposal = 'hold'") == 5
    assert q(agent, CHECKS + " AND proposal = 'approve'") == 7
    assert q(agent, "SELECT count(DISTINCT proposed_by) FROM work_item "
                    "WHERE kind = 'CHARGE_CHECK'") == 1
    assert q(agent, "SELECT min(proposed_by) FROM work_item "
                    "WHERE kind = 'CHARGE_CHECK'") == "agent:checker"
    orphans = q(agent, """SELECT count(*) FROM work_item w
                          LEFT JOIN landlord_charge c ON c.id = w.subject_id
                          WHERE c.id IS NULL AND w.kind = 'CHARGE_CHECK'""")
    assert orphans == 0, "every item's subject is a real landlord_charge id"
    assert q(agent, "SELECT count(*) FROM work_item WHERE region_id IS NULL "
                    "OR entity_id IS NULL") == 0


def test_every_item_is_made_by_events_create_then_propose(confirmed):
    agent = confirmed["lease_agent"]
    with agent.begin() as conn:
        check_period(conn, ENTITY, JAN)
    with agent.connect() as conn:
        ids = list(conn.execute(text(
            "SELECT id FROM work_item WHERE kind = 'CHARGE_CHECK' ORDER BY id")).scalars())
        for item_id in ids:
            events = events_for(conn, "work_item", item_id)
            assert [(e.actor_id, e.action) for e in events] == [
                ("agent:checker", "create"), ("agent:checker", "propose")]
        assert verify_chain(conn) is None
        last = conn.execute(text("SELECT count(*) FROM work_item w WHERE w.last_event_seq = "
                                 "(SELECT max(seq) FROM audit_event a WHERE a.subject_id = "
                                 "w.id::text) AND w.kind = 'CHARGE_CHECK'")).scalar()
    assert len(ids) == last == 12


def test_evidence_has_the_shape_the_read_api_documents(confirmed):
    agent = confirmed["lease_agent"]
    with agent.begin() as conn:
        check_period(conn, ENTITY, JAN)
    with agent.connect() as conn:
        rows = conn.execute(text("""
            SELECT w.subject_id, w.proposal, w.evidence, c.lease_id, c.charge_type, c.amount
              FROM work_item w JOIN landlord_charge c ON c.id = w.subject_id
        """)).mappings().all()
    for r in rows:
        ev = r["evidence"]
        assert ev["charge_id"] == r["subject_id"] == ev["charge_ids"][0]
        assert ev["lease_id"] == r["lease_id"] and ev["charge_type"] == r["charge_type"]
        assert ev["billed"] == float(r["amount"])
        assert isinstance(ev["supported"], (int, float))
        assert ev["rule"] in {"premises", "duplicate", "amount", "operating_expense"}
        assert ev["proof"]["section"] and ev["proof"]["quote"]
        if r["proposal"] == "approve":
            assert abs(ev["billed"] - ev["supported"]) < 1


def test_a_duplicate_items_evidence_points_at_the_original_by_database_id(confirmed):
    agent = confirmed["lease_agent"]
    with agent.begin() as conn:
        check_period(conn, ENTITY, JAN)
    with agent.connect() as conn:
        dup = conn.execute(text("SELECT evidence FROM work_item "
                                "WHERE evidence->>'rule' = 'duplicate'")).scalar_one()
        db_ids = set(conn.execute(text("SELECT id FROM landlord_charge")).scalars())
    assert dup["related"] and set(dup["related"]) <= db_ids
    assert dup["proof"]["section"] == "3.2"
    assert dup["charge_ref"].endswith(("-L1", "-L2", "-L3"))


def test_record_findings_twice_adds_nothing(confirmed):
    agent = confirmed["lease_agent"]
    events = q(agent, "SELECT count(*) FROM audit_event")
    with agent.begin() as conn:
        check_period(conn, ENTITY, JAN)
    with agent.begin() as conn:
        again = check_period(conn, ENTITY, JAN)
    assert (again["created"], again["skipped"]) == (0, 12)
    assert q(agent, CHECKS) == 12
    assert q(agent, "SELECT count(*) FROM audit_event") == events + 24


def test_record_findings_with_nothing_to_record(agent):
    with agent.begin() as conn:
        assert record_findings(conn, [], JAN) == {"created": 0, "skipped": 0}


def test_a_finding_for_a_charge_the_database_never_saw_is_refused(seeded):
    finding = Finding("F001", "amount", _charge("GHOST-L1"), APPROVE, "ok", 100.0, 100.0,
                      Proof("3.1", "quote"))
    with seeded["lease_agent"].begin() as conn, pytest.raises(MonthlyRunError, match="GHOST-L1"):
        record_findings(conn, [finding], JAN)
    assert q(seeded["lease_agent"], "SELECT count(*) FROM work_item") == 0


def test_without_the_checker_actor_nothing_is_written(confirmed):
    seeded = confirmed
    with seeded["owner"].begin() as conn:
        conn.execute(text("UPDATE actor SET active = false WHERE id = 'agent:checker'"))
    with seeded["lease_agent"].begin() as conn, pytest.raises(UnknownActor, match="agent:checker"):
        check_period(conn, ENTITY, JAN)
    assert q(seeded["lease_agent"], CHECKS) == 0


# ------------------------------------------------------------- handlers

def test_ingest_reports_counts_when_the_rows_are_present(seeded):
    with seeded["lease_agent"].connect() as conn:
        result = ingest(conn, {"entity_id": ENTITY, "period": "2026-01-01"})
    assert result == {"status": "present", "raw_rows": 12, "charges": 12}


def test_ingest_of_an_empty_period_fails_rather_than_passing(seeded):
    with seeded["lease_agent"].connect() as conn, pytest.raises(HandlerError, match="make seed"):
        ingest(conn, {"entity_id": ENTITY, "period": "2030-01-01"})


def test_a_payload_without_a_period_is_refused(agent):
    with agent.connect() as conn, pytest.raises(HandlerError, match="period"):
        ingest(conn, {"entity_id": ENTITY})


# ------------------------------------------------------ the whole month

def _month(agent):
    with agent.begin() as conn:
        run_month(conn, ENTITY, "2026-01")
    return drain(agent, "test")


def test_january_end_to_end_then_again_adds_no_jobs_and_no_items(seeded):
    agent = seeded["lease_agent"]
    outcomes = _month(agent)
    assert [(o.job.kind, o.status) for o in outcomes] == [
        ("ingest", "done"), ("abstraction", "done"), ("checking", "done")]
    assert outcomes[1].result["status"] == "drafted" and outcomes[1].result["versions"] == 5
    assert outcomes[2].result["created"] == 0 and outcomes[2].result["waiting"] == 12
    assert q(agent, "SELECT count(*) FROM work_item WHERE kind = 'LEASE_ABSTRACTION'") == 5
    assert q(agent, CHECKS) == 0, "nothing is checked against unconfirmed terms"

    lw.confirm(seeded)
    again = _month(agent)
    assert [(o.job.kind, o.status) for o in again] == [("checking", "done")]
    assert again[0].result["created"] == 12
    items, jobs = (q(agent, CHECKS), q(agent, "SELECT count(*) FROM job"))

    assert _month(agent) == [], "nothing is ready the third time"
    assert q(agent, CHECKS) == items == 12
    assert q(agent, "SELECT count(*) FROM job") == jobs == 4


def test_a_failing_checking_job_leaves_nothing_half_written(confirmed):
    agent = confirmed["lease_agent"]
    events = q(agent, "SELECT count(*) FROM audit_event")
    with confirmed["owner"].begin() as conn:
        conn.execute(text("UPDATE actor SET active = false WHERE id = 'agent:checker'"))
    outcomes = _month(agent)
    assert [o.status for o in outcomes] == ["done", "done", "failed"]
    assert "UnknownActor" in outcomes[2].error
    assert q(agent, CHECKS) == 0
    assert q(agent, "SELECT count(*) FROM audit_event") == events


def test_an_unseeded_month_dead_ends_at_ingest_and_never_checks(clean, monkeypatch):
    agent = clean["lease_agent"]
    with clean["lease_gateway"].begin() as conn:
        conn.execute(text("INSERT INTO entity VALUES ('ENT-CA', 'Northbay', 'CA')"))
    monkeypatch.setattr(handlers, "check_period", lambda *a: pytest.fail("checking ran"))
    outcomes = _month(agent)
    assert [(o.job.kind, o.status) for o in outcomes] == [("ingest", "failed")]
    assert q(agent, "SELECT status FROM job WHERE kind = 'checking'") == "queued"
