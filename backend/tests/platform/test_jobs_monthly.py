"""jobs/monthly.py and handlers.py: the month's three jobs, the bridge from
generator charge ids to database ids, and findings becoming work items.

The work layer (`app.work.transitions`) is built in parallel, so these tests
inject a small fake under that name. It writes real `work_item` rows as
lease_agent, which is what lets "January twice adds no items" mean something.
"""

import subprocess
import sys
import types
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from app.agents.checker import APPROVE, HOLD, Charge, Finding
from app.engine.charges import Proof
from app.jobs import handlers
from app.jobs.handlers import ABSTRACTION_SKIPPED, HandlerError, ingest
from app.jobs.monthly import (
    MonthlyRunError, charge_ids_by_source_id, check_period, job_key, load_charges,
    parse_period, record_findings, run_month,
)
from app.jobs.worker import drain
from app.records.ingest import stable_id
from app.records.seed import seed

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
def seeded(clean, generated):
    seed(Path(generated), clean["lease_agent"], clean["lease_gateway"])
    return clean


@pytest.fixture
def agent(clean):
    return clean["lease_agent"]


class FakeTransitions(types.ModuleType):
    """Stands in for app.work.transitions: same call shapes, real rows."""

    def __init__(self):
        super().__init__("app.work.transitions")
        self.calls = []

    def load_actor(self, conn, actor_id):
        row = conn.execute(text("SELECT id, role FROM actor WHERE id = :i"), {"i": actor_id}).one()
        return types.SimpleNamespace(id=row.id, role=row.role)

    def create_item(self, conn, actor, *, kind, subject_type, subject_id, **fields):
        self.calls.append(("create", actor.id, kind, subject_type, subject_id))
        return conn.execute(text("""
            INSERT INTO work_item (kind, subject_type, subject_id, entity_id, region_id,
                                   clinic_id, period, title, amount)
            VALUES (:kind, :st, :sid, :entity_id, :region_id, :clinic_id, :period, :title, :amount)
            RETURNING id
        """), dict(kind=kind, st=subject_type, sid=subject_id, **fields)).scalar_one()

    def transition(self, conn, actor, item_id, action, *, patch):
        import json
        self.calls.append(("transition", actor.id, item_id, action, patch["proposal"]))
        conn.execute(text("""
            UPDATE work_item SET state = 'PROPOSED', proposal = :p, reason = :r,
                   evidence = CAST(:e AS jsonb), proposed_by = :a WHERE id = :i
        """), dict(p=patch["proposal"], r=patch["reason"], e=json.dumps(patch["evidence"]),
                   a=actor.id, i=item_id))


@pytest.fixture
def work(monkeypatch):
    fake = FakeTransitions()
    monkeypatch.setitem(sys.modules, "app.work.transitions", fake)
    return fake


@pytest.fixture
def no_work_layer(monkeypatch):
    """Make the import fail the way it does before the work layer lands."""
    monkeypatch.setitem(sys.modules, "app.work.transitions", None)


def q(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _charge(cid="INV-1-L1", **kw):
    base = dict(charge_id=cid, invoice_id="INV-1", lease_id="LEASE-01", clinic_id="CLINIC-01",
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

def test_record_findings_without_the_work_layer_says_what_is_missing(agent, no_work_layer):
    finding = Finding("F001", "amount", _charge(), HOLD, "why", 100.0, 90.0)
    with agent.begin() as conn, pytest.raises(NotImplementedError, match="app.work.transitions"):
        record_findings(conn, [finding], JAN)


def test_record_findings_proposes_one_item_per_charge_as_the_checker(seeded, work):
    agent = seeded["lease_agent"]
    with agent.begin() as conn:
        counts = check_period(conn, ENTITY, JAN)
    assert counts["charges"] == counts["findings"] == counts["created"] == 12
    assert counts["holds"] == 5
    assert {c[1] for c in work.calls} == {"agent:checker"}
    assert [c[3] for c in work.calls if c[0] == "transition"] == ["propose"] * 12
    assert q(agent, "SELECT count(*) FROM work_item WHERE state = 'PROPOSED' "
                    "AND kind = 'CHARGE_CHECK' AND subject_type = 'landlord_charge'") == 12
    assert q(agent, "SELECT count(*) FROM work_item WHERE proposal = 'hold'") == 5
    orphans = q(agent, """SELECT count(*) FROM work_item w
                          LEFT JOIN landlord_charge c ON c.id = w.subject_id WHERE c.id IS NULL""")
    assert orphans == 0, "every item's subject is a real landlord_charge id"
    assert q(agent, "SELECT count(*) FROM work_item WHERE region_id IS NULL "
                    "OR entity_id IS NULL") == 0


def test_a_duplicate_items_evidence_points_at_the_original_by_database_id(seeded, work):
    agent = seeded["lease_agent"]
    with agent.begin() as conn:
        check_period(conn, ENTITY, JAN)
    with agent.connect() as conn:
        dup = conn.execute(text("SELECT evidence FROM work_item "
                                "WHERE evidence->>'rule' = 'duplicate'")).scalar_one()
        db_ids = set(conn.execute(text("SELECT id FROM landlord_charge")).scalars())
    assert dup["related"] and set(dup["related"]) <= db_ids
    assert dup["proof"]["section"] == "3.2"
    assert dup["charge_ref"].endswith(("-L1", "-L2", "-L3"))


def test_record_findings_twice_adds_nothing(seeded, work):
    agent = seeded["lease_agent"]
    with agent.begin() as conn:
        check_period(conn, ENTITY, JAN)
    with agent.begin() as conn:
        again = check_period(conn, ENTITY, JAN)
    assert (again["created"], again["skipped"]) == (0, 12)
    assert q(agent, "SELECT count(*) FROM work_item") == 12


def test_record_findings_with_nothing_to_record(agent, work):
    with agent.begin() as conn:
        assert record_findings(conn, [], JAN) == {"created": 0, "skipped": 0}


def test_a_finding_for_a_charge_the_database_never_saw_is_refused(seeded, work):
    finding = Finding("F001", "amount", _charge("GHOST-L1"), APPROVE, "ok", 100.0, 100.0,
                      Proof("3.1", "quote"))
    with seeded["lease_agent"].begin() as conn, pytest.raises(MonthlyRunError, match="GHOST-L1"):
        record_findings(conn, [finding], JAN)
    assert q(seeded["lease_agent"], "SELECT count(*) FROM work_item") == 0


def test_a_work_layer_without_load_actor_is_named(seeded, monkeypatch):
    bare = types.ModuleType("app.work.transitions")
    bare.create_item = bare.transition = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "app.work.transitions", bare)
    monkeypatch.setitem(sys.modules, "app.work.can", None)
    with seeded["lease_agent"].begin() as conn, pytest.raises(NotImplementedError,
                                                              match="load_actor"):
        check_period(conn, ENTITY, JAN)


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


def test_january_end_to_end_then_again_adds_no_jobs_and_no_items(seeded, work):
    agent = seeded["lease_agent"]
    outcomes = _month(agent)
    assert [(o.job.kind, o.status) for o in outcomes] == [
        ("ingest", "done"), ("abstraction", "done"), ("checking", "done")]
    assert outcomes[1].result == {"status": "skipped", "reason": ABSTRACTION_SKIPPED}
    assert outcomes[2].result["created"] == 12
    items, jobs = (q(agent, "SELECT count(*) FROM work_item"), q(agent, "SELECT count(*) FROM job"))

    assert _month(agent) == [], "nothing is ready the second time"
    assert q(agent, "SELECT count(*) FROM work_item") == items == 12
    assert q(agent, "SELECT count(*) FROM job") == jobs == 3


def test_without_the_work_layer_checking_fails_and_nothing_is_half_written(seeded, no_work_layer):
    agent = seeded["lease_agent"]
    outcomes = _month(agent)
    assert [o.status for o in outcomes] == ["done", "done", "failed"]
    assert "NotImplementedError" in outcomes[2].error
    assert q(agent, "SELECT count(*) FROM work_item") == 0


def test_an_unseeded_month_dead_ends_at_ingest_and_never_checks(clean, monkeypatch, work):
    agent = clean["lease_agent"]
    with clean["lease_gateway"].begin() as conn:
        conn.execute(text("INSERT INTO entity VALUES ('ENT-CA', 'Northbay', 'CA')"))
    monkeypatch.setattr(handlers, "check_period", lambda *a: pytest.fail("checking ran"))
    outcomes = _month(agent)
    assert [(o.job.kind, o.status) for o in outcomes] == [("ingest", "failed")]
    assert q(agent, "SELECT status FROM job WHERE kind = 'checking'") == "queued"
