"""Obligations and critical dates (work/obligations.py, jobs/obligations.py,
api/obligations.py) on the generated company's five leases.

The leases are drafted and confirmed by the regional manager exactly as the
product does it; obligations come from the confirmed lease_term rows with
their pages. The deadline job opens an OBLIGATION item at 90, 60 and 30
business days before each due date, once each, routed to the clinic's region.
"""

import dataclasses
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import lease_world as lw
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_gateway_engine
from app.auth.deps import api_engine, auth_settings
from app.auth.sessions import COOKIE_NAME, issue_token
from app.jobs import clock
from app.jobs import obligations as job
from app.jobs.queue import enqueue
from app.jobs.worker import drain
from app.main import create_app
from app.records.seed import seed
from app.settings import get_settings
from app.work import disputes
from app.work import obligations as ob
from app.work.events import events_for, verify_chain
from app.work.replay import replay
from app.work.roles import load_actor
from app.work.transitions import Denied, transition

ROOT = Path(__file__).resolve().parents[3]
ENTITY = "ENT-CA"
RM = "PER-RM-BAY"
RM_DESERT = "PER-RM-DESERT"
CTRL = "PER-CTRL"
SECRET = "test-obligations-secret"

# What the five leases say (datagen/leases.py, confirmed through the PDFs).
EXPIRATIONS = {"LEASE-01": date(2028, 12, 31), "LEASE-02": date(2028, 6, 30),
               "LEASE-03": date(2029, 3, 31), "LEASE-04": date(2029, 12, 31),
               "LEASE-05": date(2027, 9, 30)}
NOTICE_DAYS = {"LEASE-01": 270, "LEASE-02": 180, "LEASE-03": 270, "LEASE-04": 180,
               "LEASE-05": 120}
COMMENCEMENT_YEARS = {"LEASE-01": 2024, "LEASE-02": 2023, "LEASE-03": 2024, "LEASE-04": 2025,
                      "LEASE-05": 2024}


# ------------------------------------------------------------------- pure

def test_business_days_skip_weekends():
    friday = date(2027, 6, 4)
    assert ob.business_days_before(friday, 0) == friday
    assert ob.business_days_before(friday, 1) == date(2027, 6, 3)
    assert ob.business_days_before(date(2027, 6, 7), 1) == friday          # Monday -> Friday
    assert ob.business_days_before(friday, 5) == date(2027, 5, 28)
    d = ob.business_days_before(date(2027, 6, 2), 90)
    assert d.weekday() < 5
    assert sum(1 for i in range(1, (date(2027, 6, 2) - d).days + 1)
               if (d + timedelta(days=i)).weekday() < 5) == 90
    with pytest.raises(ValueError):
        ob.business_days_before(friday, -1)


def test_the_current_threshold_is_the_most_urgent_one_passed():
    due = date(2027, 6, 2)
    a = ob.alert_dates(due)
    assert ob.threshold_for(a[90] - timedelta(days=1), due) is None
    assert ob.threshold_for(a[90], due) == 90
    assert ob.threshold_for(a[60] - timedelta(days=1), due) == 90
    assert ob.threshold_for(a[60], due) == 60
    assert ob.threshold_for(a[30], due) == 30
    assert ob.threshold_for(due, due) == 30
    assert ob.threshold_for(due + timedelta(days=1), due) is None


def test_compute_from_terms_with_citations():
    terms = {
        "commencement": ob.Term("2024-10-01", 2, "shall commence on October 1, 2024", "doc", 5),
        "expiration": ob.Term("2027-09-30", 2, "shall expire at 11:59 p.m. on September 30, 2027",
                              "doc", 5),
        "security_deposit": ob.Term(16240.0, 5, "shall deposit with Landlord the sum of $16,240.00",
                                    "doc", 5),
        "renewal_count": ob.Term(1.0, 7, "one (1) option", "doc", 5),
        "renewal_years": ob.Term(3.0, 7, "each for an additional period of 3 years", "doc", 5),
        "renewal_notice_days": ob.Term(120.0, 7, "not less than 120 days prior", "doc", 5),
    }
    found = {o.key: o for o in ob.compute("LEASE-05", terms, "lease_term",
                                          landlord={"name": "Pacific Crest Properties LLC",
                                                    "notice_address": "88 Baldwin Ave"})}
    assert found["expiration"].due_date == date(2027, 9, 30)
    assert found["renewal_notice"].due_date == date(2027, 6, 2)
    assert found["renewal_notice"].citation["section"] == "11.2"
    assert found["renewal_notice"].citation["page"] == 7
    assert "88 Baldwin Ave" in found["renewal_notice"].action
    assert found["deposit_return"].due_date == date(2027, 10, 30)
    assert found["deposit_return"].citation["section"] == "5.2"
    assert [k for k in found if k.startswith("cam_audit")] == [
        "cam_audit_window:%d" % y for y in range(2024, 2028)]
    # 2025's statement is due 2026-04-30; the audit right lapses 180 days later.
    assert found["cam_audit_window:2025"].due_date == date(2026, 10, 27)
    # No option, no renewal notice; no expiration, nothing at all.
    no_option = dict(terms, renewal_count=ob.Term(0.0))
    assert "renewal_notice" not in {o.key for o in ob.compute("L", no_option, "lease_term")}
    assert ob.compute("L", {}, "lease_term") == []
    assert ob.compute("L", {"expiration": ob.Term("not a date")}, "lease_term") == []


# ---------------------------------------------------------------- the world

@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("generated")
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    return out


@pytest.fixture
def seeded(clean, generated, monkeypatch):
    seed(Path(generated), clean["lease_agent"], clean["lease_gateway"])
    with clean["lease_gateway"].begin() as conn:
        disputes.ensure_agents(conn)
    with clean["owner"].begin() as conn:
        conn.execute(text("INSERT INTO region (id, name) VALUES ('REG-DESERT', 'Desert')"))
        conn.execute(text("""
            INSERT INTO actor (id, name, role, region_id, entity_id, active)
            VALUES (:id, 'Desert manager', 'regional_manager', 'REG-DESERT', NULL, true)
        """), {"id": RM_DESERT})
    lw.use_documents(monkeypatch, generated)
    return clean


@pytest.fixture
def confirmed(seeded, generated):
    lw.draft_and_confirm(seeded, generated)
    return seeded


def q(eng, sql, **params):
    with eng["lease_reader"].connect() as conn:
        return conn.execute(text(sql), params).scalar()


def rows(eng, sql, **params):
    with eng["lease_reader"].connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def run_job(eng, today):
    with eng["lease_agent"].begin() as conn:
        return job.obligations(conn, {"entity_id": ENTITY, "today": today.isoformat()})


def obligation(eng, lease_id, key):
    return rows(eng, "SELECT * FROM obligation WHERE lease_id = :l AND key = :k",
                l=lease_id, k=key)[0]


def alerts_for(eng, obligation_id):
    return rows(eng, """SELECT * FROM work_item WHERE kind = 'OBLIGATION'
                         AND subject_id LIKE :p ORDER BY id""", p="%d:%%" % obligation_id)


# ------------------------------------------------------------- obligations

def test_the_five_leases_obligations_come_from_confirmed_terms_with_pages(confirmed):
    with confirmed["lease_agent"].begin() as conn:
        result = ob.refresh(conn, ENTITY)
    assert result["skipped"] == {}
    found = rows(confirmed, "SELECT * FROM obligation ORDER BY due_date, lease_id, key")
    assert result["obligations"] == len(found) == len(set(result["new_or_moved"]))
    print("\n%-9s %-26s %-11s %-6s %s" % ("lease", "obligation", "due", "page", "clause"))
    for o in found:
        print("%-9s %-26s %s %-6s %s" % (o["lease_id"], o["key"], o["due_date"],
                                         o["citation"].get("page"), o["citation"].get("section")))
    by = {(o["lease_id"], o["key"]): o for o in found}
    for lease, expiration in EXPIRATIONS.items():
        assert by[(lease, "expiration")]["due_date"] == expiration
        renewal = by[(lease, "renewal_notice")]
        assert renewal["due_date"] == expiration - timedelta(days=NOTICE_DAYS[lease])
        assert renewal["citation"]["page"] == 7 and renewal["citation"]["section"] == "11.2"
        assert "%d days prior" % NOTICE_DAYS[lease] in renewal["citation"]["quote"]
        assert renewal["source"] == "lease_term" and renewal["lease_version_id"] is not None
        deposit = by[(lease, "deposit_return")]
        assert deposit["due_date"] == expiration + timedelta(days=30)
        assert deposit["citation"]["page"] == 5                      # located in the PDF
        audits = sorted(k for (l, k) in by if l == lease and k.startswith("cam_audit"))
        assert audits == ["cam_audit_window:%d" % y
                          for y in range(COMMENCEMENT_YEARS[lease], expiration.year + 1)]
        assert all(by[(lease, k)]["citation"]["page"] for k in audits)
        assert by[(lease, "expiration")]["citation"]["page"] == 2
    assert by[("LEASE-05", "renewal_notice")]["due_date"] == date(2027, 6, 2)
    assert by[("LEASE-01", "renewal_notice")]["due_date"] == date(2028, 4, 5)

    # Computing again changes nothing on record.
    events = q(confirmed, "SELECT count(*) FROM audit_event")
    with confirmed["lease_agent"].begin() as conn:
        again = ob.refresh(conn, ENTITY)
    assert again["new_or_moved"] == [] and again["obligations"] == result["obligations"]
    assert q(confirmed, "SELECT count(*) FROM audit_event") == events
    assert q(confirmed, "SELECT count(*) FROM obligation") == len(found)


def test_unconfirmed_leases_fall_back_to_the_generated_terms(seeded):
    with seeded["lease_agent"].begin() as conn:
        result = ob.refresh(conn, ENTITY, locate_clauses=False)
    assert result["skipped"] == {}
    renewal = obligation(seeded, "LEASE-05", "renewal_notice")
    assert renewal["source"] == "generator" and renewal["due_date"] == date(2027, 6, 2)
    assert renewal["citation"]["page"] is None and renewal["lease_version_id"] is None
    assert "120 days prior" in renewal["citation"]["quote"]


def test_alerts_fire_at_90_60_and_30_business_days_once_each(confirmed):
    with confirmed["lease_agent"].begin() as conn:
        ob.refresh(conn, ENTITY)
    target = obligation(confirmed, "LEASE-05", "renewal_notice")
    due = target["due_date"]
    marks = ob.alert_dates(due)

    run_job(confirmed, marks[90] - timedelta(days=1))
    assert alerts_for(confirmed, target["id"]) == []
    for n in (90, 60, 30):
        run_job(confirmed, marks[n])
        footprint = (q(confirmed, "SELECT count(*) FROM work_item"),
                     q(confirmed, "SELECT count(*) FROM audit_event"))
        assert run_job(confirmed, marks[n])["alerts_created"] == []            # rerun: nothing
        assert (q(confirmed, "SELECT count(*) FROM work_item"),
                q(confirmed, "SELECT count(*) FROM audit_event")) == footprint
        made = alerts_for(confirmed, target["id"])
        assert [a["subject_id"].rsplit(":", 1)[1] for a in made] == [
            "%dbd" % m for m in (90, 60, 30) if m >= n]
    run_job(confirmed, due)
    run_job(confirmed, due + timedelta(days=1))
    made = alerts_for(confirmed, target["id"])
    assert len(made) == 3

    item = made[0]
    assert (item["state"], item["proposed_by"], item["proposal"]) == (
        "PROPOSED", "agent:obligations", "act")
    assert (item["region_id"], item["entity_id"], item["clinic_id"]) == (
        "REG-BAY", ENTITY, "CLINIC-05")
    ev = item["evidence"]
    assert ev["routed_to"] == RM and ev["due_date"] == "2027-06-02"
    assert ev["threshold_business_days"] == 90 and ev["alert_date"] == marks[90].isoformat()
    assert ev["citation"]["page"] == 7 and ev["citation"]["section"] == "11.2"
    assert "Pacific Crest Properties LLC" in item["reason"]


def test_a_clock_that_jumps_fires_only_the_most_urgent_threshold(confirmed):
    with confirmed["lease_agent"].begin() as conn:
        ob.refresh(conn, ENTITY)
    target = obligation(confirmed, "LEASE-01", "renewal_notice")
    marks = ob.alert_dates(target["due_date"])
    run_job(confirmed, marks[30] + timedelta(days=2))
    assert [a["subject_id"].rsplit(":", 1)[1] for a in alerts_for(confirmed, target["id"])] == [
        "30bd"]
    run_job(confirmed, marks[30] + timedelta(days=3))
    assert len(alerts_for(confirmed, target["id"])) == 1


def test_the_regional_manager_records_a_decision_on_the_item(confirmed):
    with confirmed["lease_agent"].begin() as conn:
        ob.refresh(conn, ENTITY)
    target = obligation(confirmed, "LEASE-05", "renewal_notice")
    run_job(confirmed, ob.alert_dates(target["due_date"])[90])
    (item,) = alerts_for(confirmed, target["id"])
    with confirmed["lease_api"].begin() as conn:
        with pytest.raises(Denied, match="region"):
            transition(conn, load_actor(conn, RM_DESERT), item["id"], "approve")
    decision = "We will exercise the option; notice drafted for the controller's signature."
    with confirmed["lease_api"].begin() as conn:
        row = transition(conn, load_actor(conn, RM), item["id"], "approve", reason=decision)
    assert row["state"] == "APPROVED"
    with confirmed["lease_reader"].connect() as conn:
        last = events_for(conn, "work_item", item["id"])[-1]
        assert (last.actor_id, last.action, last.reason) == (RM, "approve", decision)
        assert verify_chain(conn) is None
    with confirmed["owner"].begin() as conn:
        assert replay(conn).identical


def test_a_confirmed_amendment_moves_the_dates_and_alerts_again(confirmed):
    with confirmed["lease_agent"].begin() as conn:
        ob.refresh(conn, ENTITY)
    before = obligation(confirmed, "LEASE-05", "renewal_notice")
    # A confirmed version 2 extends LEASE-05 by three years.
    with confirmed["lease_agent"].begin() as conn:
        vid = conn.execute(text("""
            INSERT INTO lease_version (lease_id, version, effective_from)
            VALUES ('LEASE-05', 2, '2026-06-01') RETURNING id""")).scalar_one()
        conn.execute(text("""
            INSERT INTO lease_term (lease_version_id, field, value, page, quote)
            VALUES (:v, 'expiration', '"2030-09-30"', 1,
                    'the Expiration Date is extended to September 30, 2030')"""), {"v": vid})
    with confirmed["owner"].begin() as conn:
        conn.execute(text("UPDATE lease_version SET confirmed_by = :rm, confirmed_at = now() "
                          "WHERE id = :v"), {"rm": RM, "v": vid})
    with confirmed["lease_agent"].begin() as conn:
        moved = ob.refresh(conn, ENTITY)["new_or_moved"]
    after = obligation(confirmed, "LEASE-05", "renewal_notice")
    assert after["id"] == before["id"] and after["id"] in moved
    assert after["due_date"] == date(2030, 9, 30) - timedelta(days=120)
    assert obligation(confirmed, "LEASE-05", "expiration")["citation"]["lease_version_id"] == vid
    with confirmed["lease_reader"].connect() as conn:
        trail = events_for(conn, "obligation", after["id"])
    assert [(e.diff["from"], e.diff["to"]) for e in trail] == [
        (None, "2027-06-02"), ("2027-06-02", "2030-06-02")]


def test_the_deadline_job_runs_through_the_worker_on_the_business_clock(confirmed):
    target_due = date(2027, 6, 2)
    with confirmed["lease_agent"].begin() as conn:
        clock.set_today(conn, ob.alert_dates(target_due)[60])
        enqueue(conn, "obligations", {"entity_id": ENTITY})
    (outcome,) = drain(confirmed["lease_agent"], "deadlines")
    assert outcome.status == "done", outcome
    assert outcome.result["obligations"] > 0 and outcome.result["alerts_created"]
    target = obligation(confirmed, "LEASE-05", "renewal_notice")
    assert [a["subject_id"].rsplit(":", 1)[1] for a in alerts_for(confirmed, target["id"])] == [
        "60bd"]


def test_only_the_obligations_agent_writes_obligations(confirmed):
    with confirmed["lease_api"].connect() as conn:
        with pytest.raises(Exception, match="permission denied"):
            conn.execute(text("UPDATE obligation SET due_date = '2099-01-01'"))
        conn.rollback()


# ---------------------------------------------------------------------- API

@pytest.fixture
def client(confirmed):
    settings = dataclasses.replace(get_settings(), session_secret=SECRET,
                                   cors_origins=("http://localhost:3000",))
    app = create_app(settings)
    app.dependency_overrides[api_engine] = lambda: confirmed["lease_api"]
    app.dependency_overrides[get_gateway_engine] = lambda: confirmed["lease_gateway"]
    app.dependency_overrides[auth_settings] = lambda: settings
    return TestClient(app)


def as_(client, actor_id):
    client.cookies.set(COOKIE_NAME, issue_token(SECRET, actor_id))
    return client


def test_get_obligations_within_days_from_the_business_date(confirmed, client):
    today = ob.alert_dates(date(2027, 6, 2))[90]
    until = today + timedelta(days=180)
    with confirmed["lease_agent"].begin() as conn:
        clock.set_today(conn, today)
    run_job(confirmed, today)
    res = as_(client, RM).get("/api/obligations", params={"within_days": 180})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["today"] == today.isoformat() and body["within_days"] == 180
    keys = [(o["lease_id"], o["key"]) for o in body["obligations"]]
    assert ("LEASE-05", "renewal_notice") in keys                 # 2027-06-02
    assert ("LEASE-05", "expiration") not in keys                 # 2027-09-30, too far
    assert all(today.isoformat() <= o["due_date"] <= until.isoformat() for o in body["obligations"])
    renewal = next(o for o in body["obligations"] if o["key"] == "renewal_notice")
    assert renewal["days_left"] == (date(2027, 6, 2) - today).days
    assert renewal["citation"]["page"] == 7
    assert set(renewal["alert_dates"]) == {"90", "60", "30"}
    assert [a["title"] for a in renewal["alerts"]][0].startswith("CLINIC-05: renewal notice")

    assert as_(client, RM_DESERT).get("/api/obligations").json()["total"] == 0
    filtered = as_(client, CTRL).get("/api/obligations", params={
        "within_days": 3660, "lease_id": "LEASE-01", "kind": "renewal_notice"}).json()
    assert [(o["lease_id"], o["due_date"]) for o in filtered["obligations"]] == [
        ("LEASE-01", "2028-04-05")]
    assert as_(client, CTRL).get("/api/obligations", params={"kind": "nope"}).status_code == 422
    assert as_(client, CTRL).get("/api/obligations", params={"within_days": -1}).status_code == 422
