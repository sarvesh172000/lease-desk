"""The read side of the API (DESIGN.md §16) against a seeded database.

Exceptions are CHARGE_CHECK work items. The checker -> work wiring lands
later, so `checked` runs the real checker over the seeded January charges and
inserts its holds as the owner, with the evidence shape exceptions.py reads.
"""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_data_dir, get_engine
from app.auth.deps import SessionActor, current_actor
from app.main import create_app
from app.records.seed import seed
from app.work.events import append_event

ROOT = Path(__file__).resolve().parents[3]


# --- fixtures ---------------------------------------------------------------------

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


# The read routes need a session; who it is does not matter to them (any
# signed-in person may read). test_api_write.py covers 401 and real cookies.
READER = SessionActor(id="PER-CTRL", name="Priya Raghunathan", role="controller",
                      region_id=None, entity_id=None)


def make_client(engines, data_dir) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engines["lease_api"]
    app.dependency_overrides[current_actor] = lambda: READER
    app.dependency_overrides[get_data_dir] = lambda: Path(data_dir)
    return TestClient(app)


@pytest.fixture
def client(seeded, generated):
    return make_client(seeded, generated)


def insert_work_item(owner, *, state, evidence, subject_id, clinic_id=None, period=None,
                     proposal="hold", kind="CHARGE_CHECK", subject_type="landlord_charge",
                     amount=None) -> int:
    with owner.begin() as conn:
        return conn.execute(text("""
            INSERT INTO work_item (kind, state, subject_type, subject_id, clinic_id, period,
                                   title, amount, proposal, evidence, proposed_by)
            VALUES (:kind, :state, :st, :sid, :clinic, :period, 'test item', :amount,
                    :proposal, CAST(:evidence AS jsonb), 'agent:checker')
            RETURNING id
        """), dict(kind=kind, state=state, st=subject_type, sid=subject_id, clinic=clinic_id,
                   period=period, amount=amount, proposal=proposal,
                   evidence=json.dumps(evidence))).scalar_one()


def run_checker(engines):
    """The real checker over the seeded January charges: every finding, keyed
    by the landlord_charge id it is about."""
    from app.agents.checker import Charge, check_month
    from app.engine.from_datagen import rules_from_terms
    from datagen.company import build_company
    from datagen.leases import build_leases

    company = build_company()
    rules = rules_from_terms(build_leases(company), company)
    with engines["lease_reader"].connect() as conn:
        rows = conn.execute(text("""
            SELECT id, invoice_id, lease_id, clinic_id, period, charge_type, suite, amount
              FROM landlord_charge WHERE period = '2026-01-01' ORDER BY id
        """)).mappings().all()
    charges = [Charge(charge_id=r["id"], invoice_id=r["invoice_id"], lease_id=r["lease_id"],
                      clinic_id=r["clinic_id"], period=r["period"], charge_type=r["charge_type"],
                      suite=r["suite"] or "", amount=float(r["amount"])) for r in rows]
    return check_month(charges, rules, date(2026, 1, 1))


@pytest.fixture
def checked(seeded):
    """One PROPOSED hold per checker hold, as the wiring will write them."""
    ids = {}
    for f in run_checker(seeded):
        if not f.is_hold:
            continue
        c = f.charge
        ids[(c.lease_id, c.charge_type, c.charge_id)] = insert_work_item(
            seeded["owner"], state="PROPOSED", subject_id=c.charge_id, clinic_id=c.clinic_id,
            period=c.period, amount=f.variance,
            evidence={"lease_id": c.lease_id, "charge_id": c.charge_id,
                      "charge_ids": [c.charge_id] + f.related, "charge_type": c.charge_type,
                      "billed": f.billed, "supported": f.supported, "rule": f.rule})
    return ids


def cam_item(ids):
    return next(v for (lease, kind, _), v in ids.items()
                if lease == "LEASE-01" and kind == "cam_estimate")


# --- GET /api/leases ------------------------------------------------------------------

def test_leases_lists_the_portfolio(client):
    body = client.get("/api/leases").json()
    assert [l["lease_id"] for l in body] == ["LEASE-0%d" % i for i in range(1, 6)]
    first = body[0]
    assert first["clinic_id"] == "CLINIC-01"
    assert first["location"] == "Northbay PT — Daly City — Suite 210"
    assert first["lessor"] == "Serramonte Retail Partners LLC"
    assert first["monthly_rent"] == 19626.65
    assert first["end"] == "2028-12-31"
    assert all(l["status"] == "balanced" for l in body), "no work items yet"


def test_lease_01_liability_as_of_the_business_date(client):
    """Default as-of is 2026-01-01: the January closing liability."""
    first = client.get("/api/leases").json()[0]
    assert first["liability"] == 640143.06


def test_lease_01_reproduces_the_fixture_liability_as_of_june(client):
    """The §16 fixture's 559,665.35 is the carried liability at 30 June 2026,
    the day before the amendment (DESIGN.md §6)."""
    first = client.get("/api/leases", params={"as_of": "2026-06-01"}).json()[0]
    assert (first["monthly_rent"], first["liability"]) == (19626.65, 559665.35)


def test_a_lease_with_an_open_hold_is_an_exception(client, checked):
    status = {l["lease_id"]: l["status"] for l in client.get("/api/leases").json()}
    held = {lease for (lease, _, _) in checked}
    assert held, "the checker should hold something in January"
    assert {k for k, v in status.items() if v == "exception"} == held


def test_an_approved_hold_no_longer_makes_the_lease_an_exception(client, seeded, checked):
    with seeded["owner"].begin() as conn:
        conn.execute(text("UPDATE work_item SET state = 'APPROVED'"))
    assert {l["status"] for l in client.get("/api/leases").json()} == {"balanced"}


def test_an_approve_proposal_is_not_an_exception(client, seeded):
    insert_work_item(seeded["owner"], state="PROPOSED", proposal="approve", subject_id="x",
                     evidence={"lease_id": "LEASE-02"})
    assert {l["status"] for l in client.get("/api/leases").json()} == {"balanced"}


def test_leases_without_terms_on_file_are_listed_with_nulls(seeded, tmp_path):
    body = make_client(seeded, tmp_path).get("/api/leases").json()
    assert len(body) == 5
    assert body[0]["monthly_rent"] is None and body[0]["liability"] is None


def test_leases_bad_as_of_is_422(client):
    assert client.get("/api/leases", params={"as_of": "2026-13-01"}).status_code == 422
    assert client.get("/api/leases", params={"as_of": "soon"}).status_code == 422


def test_leases_on_an_empty_database_is_an_empty_list(clean, tmp_path):
    assert make_client(clean, tmp_path).get("/api/leases").json() == []


# --- GET /api/leases/{id}/schedule ----------------------------------------------------

def test_schedule_v1_is_the_engine_schedule(client, generated):
    from leasedesk.models import load_lease
    from leasedesk.schedule import build

    body = client.get("/api/leases/LEASE-01/schedule").json()
    engine = build(load_lease(str(generated / "leases" / "lease-01.json")))
    assert body["version"] == 1 and body["versions"] == [1] and body["confirmed"] is True
    assert body["effective_from"] == "2024-01-01"
    assert len(body["rows"]) == len(engine.periods) == 60
    assert body["opening_liability"] == engine.opening_liability
    june = next(r for r in body["rows"] if r["period"] == "2026-06-01")
    assert june["liability_close"] == 559665.35 and june["rou_close"] == 538771.19
    assert body["rows"][-1]["liability_close"] == pytest.approx(0, abs=0.05)


def add_version(owner, lease_id, version, effective, terms, confirmed=False):
    with owner.begin() as conn:
        vid = conn.execute(text("""
            INSERT INTO lease_version (lease_id, version, effective_from, confirmed_by, confirmed_at)
            VALUES (:l, :v, :e, CAST(:by AS text),
                    CASE WHEN CAST(:by AS text) IS NULL THEN NULL ELSE now() END) RETURNING id
        """), dict(l=lease_id, v=version, e=effective,
                   by="P-RM-01" if confirmed else None)).scalar_one()
        for field, value in terms.items():
            conn.execute(text("""INSERT INTO lease_term (lease_version_id, field, value)
                                 VALUES (:id, :f, CAST(:v AS jsonb))"""),
                         dict(id=vid, f=field, v=json.dumps(value)))


SECOND_AMENDMENT = {"base_rent_monthly": 17400.00, "expiration": "2031-12-31",
                    "escalation_kind": "fixed_percent", "escalation_amount": 0.025}


def test_schedule_v2_is_the_remeasured_amendment(client, seeded):
    """The demo amendment as lease_version 2 reproduces DESIGN.md §6:
    liability 1,002,921.05 and ROU 982,026.89 from 1 July 2026."""
    add_version(seeded["owner"], "LEASE-01", 2, "2026-07-01", SECOND_AMENDMENT)
    body = client.get("/api/leases/LEASE-01/schedule", params={"version": 2}).json()
    assert body["versions"] == [1, 2] and body["confirmed"] is False
    assert body["effective_from"] == "2026-07-01"
    assert (body["opening_liability"], body["opening_rou"]) == (1002921.05, 982026.89)
    assert body["rows"][0]["payment"] == 17400.00
    assert body["rows"][-1]["period"] == "2031-12-01"


def test_unconfirmed_version_is_not_the_default_but_confirmed_one_is(client, seeded):
    add_version(seeded["owner"], "LEASE-01", 2, "2026-07-01", SECOND_AMENDMENT)
    assert client.get("/api/leases/LEASE-01/schedule").json()["version"] == 1
    with seeded["owner"].begin() as conn:
        conn.execute(text("UPDATE lease_version SET confirmed_by = 'P-RM-01', confirmed_at = now()"))
    # Still v1 on the business date (January), v2 in the portfolio once in effect.
    assert client.get("/api/leases/LEASE-01/schedule").json()["version"] == 1
    july = client.get("/api/leases", params={"as_of": "2026-07-01"}).json()[0]
    assert (july["monthly_rent"], july["end"]) == (17400.00, "2031-12-31")


def test_term_value_may_be_wrapped(client, seeded):
    add_version(seeded["owner"], "LEASE-01", 2, "2026-07-01",
                {k: {"value": v} for k, v in SECOND_AMENDMENT.items()})
    body = client.get("/api/leases/LEASE-01/schedule", params={"version": 2}).json()
    assert body["opening_liability"] == 1002921.05


def test_schedule_unknown_lease_is_404(client):
    assert client.get("/api/leases/LEASE-99/schedule").status_code == 404
    assert client.get("/api/leases/..%2F..%2Fetc/schedule").status_code == 404


def test_schedule_unknown_version_is_404(client):
    response = client.get("/api/leases/LEASE-01/schedule", params={"version": 2})
    assert response.status_code == 404 and "has no version 2" in response.json()["detail"]


@pytest.mark.parametrize("bad", ["0", "-1", "two", "1.5", ""])
def test_schedule_bad_version_is_422(client, bad):
    assert client.get("/api/leases/LEASE-01/schedule", params={"version": bad}).status_code == 422


def test_schedule_with_unreadable_version_terms_is_422_not_500(client, seeded):
    add_version(seeded["owner"], "LEASE-01", 2, "2026-07-01",
                {"base_rent_monthly": "a lot", "expiration": "2031-12-31"})
    response = client.get("/api/leases/LEASE-01/schedule", params={"version": 2})
    assert response.status_code == 422
    # The portfolio still renders, with nulls only where it must.
    assert client.get("/api/leases").status_code == 200


def test_schedule_version_outside_the_term_is_422(client, seeded):
    add_version(seeded["owner"], "LEASE-01", 2, "2035-01-01", SECOND_AMENDMENT)
    assert client.get("/api/leases/LEASE-01/schedule", params={"version": 2}).status_code == 422


def test_schedule_without_terms_on_file_is_404(seeded, tmp_path):
    response = make_client(seeded, tmp_path).get("/api/leases/LEASE-01/schedule")
    assert response.status_code == 404 and "no terms" in response.json()["detail"]


# --- GET /api/exceptions ------------------------------------------------------------

def test_exceptions_lists_the_checker_holds(client, checked):
    body = client.get("/api/exceptions").json()
    assert len(body) == len(checked)
    cam = next(e for e in body if e["exception_id"] == "exc_%d" % cam_item(checked))
    # The fixture's own numbers: billed 6,458.33 against 5,941.67 supported.
    assert cam == {"exception_id": cam["exception_id"], "lease_id": "LEASE-01",
                   "clinic_id": "CLINIC-01", "period": "2026-01-01",
                   "charge_type": "cam_estimate", "expected": 5941.67, "actual": 6458.33,
                   "delta": 516.66, "status": "pending_review", "confidence": None}


def test_exceptions_status_follows_the_work_state(client, seeded, checked):
    item = cam_item(checked)
    expected = {"NEW": "exception", "PROPOSED": "pending_review",
                "NEEDS_INFO": "escalated", "HELD": "escalated", "APPROVED": "balanced"}
    for state, status in expected.items():
        with seeded["owner"].begin() as conn:
            conn.execute(text("UPDATE work_item SET state = :s WHERE id = :i"), dict(s=state, i=item))
        listed = {e["exception_id"]: e["status"] for e in client.get("/api/exceptions").json()}
        assert listed["exc_%d" % item] == status, state


def test_closed_and_rejected_items_are_not_open(client, seeded, checked):
    item = cam_item(checked)
    for state in ("POSTED", "CLOSED", "REJECTED"):
        with seeded["owner"].begin() as conn:
            conn.execute(text("UPDATE work_item SET state = :s WHERE id = :i"), dict(s=state, i=item))
        assert "exc_%d" % item not in {e["exception_id"] for e in client.get("/api/exceptions").json()}


def test_other_kinds_and_approve_proposals_are_not_exceptions(client, seeded):
    insert_work_item(seeded["owner"], state="PROPOSED", proposal="approve", subject_id="a",
                     evidence={})
    insert_work_item(seeded["owner"], state="PROPOSED", kind="LEASE_ABSTRACTION",
                     subject_type="lease", subject_id="LEASE-01", evidence={})
    assert client.get("/api/exceptions").json() == []


def test_confidence_comes_from_evidence(client, seeded):
    insert_work_item(seeded["owner"], state="PROPOSED", subject_id="z",
                     evidence={"lease_id": "LEASE-03", "billed": 10, "supported": 8,
                               "investigation": {"confidence": 0.81}})
    [e] = client.get("/api/exceptions").json()
    assert (e["confidence"], e["delta"]) == (0.81, 2.0)


def test_hostile_evidence_is_nulled_not_a_500(client, seeded):
    insert_work_item(seeded["owner"], state="PROPOSED", subject_id="z", amount=12.5,
                     evidence={"lease_id": 7, "billed": "lots", "supported": None,
                               "confidence": "NaN", "investigation": "nope"})
    [e] = client.get("/api/exceptions").json()
    assert e["lease_id"] is None and e["expected"] is None and e["delta"] is None
    assert e["actual"] == 12.5, "falls back to the item amount"
    assert e["confidence"] is None
    detail = client.get("/api/exceptions/" + e["exception_id"]).json()
    assert detail["investigation"] is None, "a string where the investigation should be is no investigation"


# --- GET /api/exceptions/{id} -------------------------------------------------------

INVESTIGATION = {
    "root_cause": "amendment", "confidence": 0.94, "explains_variance": True,
    "evidence": [{"doc_id": "eml_20260618", "date": "2026-06-18",
                  "source": "dana.reyes@serramonteretail.example", "trust_rank": 1,
                  "quote": "Base rent reduced to $17,400 per month effective July 1, 2026.",
                  "page": 1, "box": [85.0, 125.3, 527.0, 152.1]}],
    "liability_before": 559665.35, "liability_after": 1002921.05,
    "rou_before": 538771.19, "rou_after": 982026.89,
    "entries": [{"account": "Lease liability", "debit": 0, "credit": 443255.70},
                {"account": "ROU asset", "debit": 443255.70, "credit": 0}],
}


def test_exception_detail_without_investigation_is_null(client, checked):
    """No investigation is null, not an Investigation full of nulls.

    The screen says "No investigation on record yet." for the first and
    "does not explain the variance" for the second; they are different claims.
    """
    item = cam_item(checked)
    body = client.get("/api/exceptions/exc_%d" % item).json()
    assert body["exception_id"] == "exc_%d" % item
    assert (body["lease_id"], body["period"], body["expected"], body["actual"], body["delta"]) \
        == ("LEASE-01", "2026-01-01", 5941.67, 6458.33, 516.66)
    assert body["status"] == "pending_review"
    assert body["investigation"] is None


def test_exception_detail_carries_the_recorded_investigation(client, seeded):
    item = insert_work_item(seeded["owner"], state="PROPOSED", subject_id="p",
                            period="2026-07-01", clinic_id="CLINIC-01",
                            evidence={"lease_id": "LEASE-01", "billed": 17400.00,
                                      "supported": 19626.65, "investigation": INVESTIGATION})
    body = client.get("/api/exceptions/exc_%d" % item).json()
    assert body["delta"] == -2226.65
    inv = body["investigation"]
    assert inv["evidence"] == INVESTIGATION["evidence"]
    assert inv["liability_after"] == 1002921.05
    assert inv["balanced"] is True, "computed from the entries when not recorded"


def test_exception_detail_shows_closed_items_as_balanced(client, seeded, checked):
    item = cam_item(checked)
    with seeded["owner"].begin() as conn:
        conn.execute(text("UPDATE work_item SET state = 'POSTED' WHERE id = :i"), dict(i=item))
    assert client.get("/api/exceptions/exc_%d" % item).json()["status"] == "balanced"


@pytest.mark.parametrize("bad", ["exc_999999", "exc_0", "exc_abc", "999", "exc_",
                                 "exc_99999999999999999999999", "LEASE-01"])
def test_exception_detail_unknown_or_malformed_id_is_404(client, checked, bad):
    assert client.get("/api/exceptions/" + bad).status_code == 404


def test_exception_detail_of_a_non_exception_work_item_is_404(client, seeded):
    item = insert_work_item(seeded["owner"], state="PROPOSED", proposal="approve",
                            subject_id="q", evidence={})
    assert client.get("/api/exceptions/exc_%d" % item).status_code == 404


# --- GET /api/audit -----------------------------------------------------------------

def _event(engines, **kw):
    with engines["lease_api"].begin() as conn:
        return append_event(conn, **kw).seq


def test_audit_for_a_lease_gathers_its_subjects(client, seeded, checked):
    item = cam_item(checked)
    on_item = _event(seeded, actor_id="agent:checker", action="propose",
                     subject_type="work_item", subject_id=item, reason="CAM above lease")
    on_lease = _event(seeded, actor_id="P-RM-01", action="confirm", subject_type="lease",
                      subject_id="LEASE-01")
    elsewhere = _event(seeded, actor_id="P-RM-01", action="confirm", subject_type="lease",
                       subject_id="LEASE-02")
    body = client.get("/api/audit", params={"lease_id": "LEASE-01"}).json()
    assert body["chain_verified"] is True and body["broken_seq"] is None
    seqs = [e["seq"] for e in body["events"]]
    assert seqs == sorted(seqs) and on_item in seqs and on_lease in seqs
    assert elsewhere not in seqs
    first = body["events"][0]
    assert set(first) == {"seq", "at", "actor_id", "action", "subject_type", "subject_id",
                          "allowed", "reason"}


def test_audit_by_subject_and_denied_attempts_show(client, seeded):
    _event(seeded, actor_id="P-RM-02", action="approve", subject_type="work_item",
           subject_id=7, allowed=False, reason="outside your region")
    _event(seeded, actor_id="P-RM-01", action="approve", subject_type="work_item", subject_id=8)
    body = client.get("/api/audit", params={"subject_type": "work_item", "subject_id": "7"}).json()
    assert [(e["allowed"], e["reason"]) for e in body["events"]] == [(False, "outside your region")]
    assert len(client.get("/api/audit").json()["events"]) == 2


def test_audit_limit_keeps_the_newest(client, seeded):
    seqs = [_event(seeded, actor_id="a", action="x", subject_type="t", subject_id=i)
            for i in range(5)]
    body = client.get("/api/audit", params={"limit": 2}).json()
    assert [e["seq"] for e in body["events"]] == seqs[-2:]


def test_audit_reports_a_broken_chain(client, seeded):
    from app.db.bootstrap import execute_raw

    seq = _event(seeded, actor_id="a", action="x", subject_type="t", subject_id=1)
    _event(seeded, actor_id="a", action="y", subject_type="t", subject_id=1)
    with seeded["owner"].begin() as conn:
        execute_raw(conn, "ALTER TABLE audit_event DISABLE TRIGGER USER;"
                          "UPDATE audit_event SET reason = 'tampered' WHERE seq = %d;"
                          "ALTER TABLE audit_event ENABLE TRIGGER USER;" % seq)
    body = client.get("/api/audit").json()
    assert body["chain_verified"] is False and body["broken_seq"] == seq


def test_audit_unknown_lease_is_404(client):
    assert client.get("/api/audit", params={"lease_id": "LEASE-99"}).status_code == 404


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": "many"}, {"limit": 10_001},
                                    {"subject_id": "7"}, {"lease_id": ""}])
def test_audit_bad_params_are_422(client, params):
    assert client.get("/api/audit", params=params).status_code == 422
