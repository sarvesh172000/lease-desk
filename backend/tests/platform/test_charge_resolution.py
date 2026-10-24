"""What "Approve" means on a held charge (work/charges.py), on a real January.

datagen.build -> seed -> run_month: twelve charge checks, five holds. Approving
a hold upholds it: a wholly unsupported charge (the duplicate rent, the
unleased suite) posts nothing, a partly unsupported one (an escalation applied
early, CAM above the estimate) posts only what the lease supports. The only
path for a disputed dollar to reach AP is the controller's pay-as-billed
override, with a reason, on record.
"""

import csv
import dataclasses
import io
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import lease_world as lw
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_gateway_engine
from app.auth.deps import api_engine, auth_settings
from app.auth.sessions import COOKIE_NAME, issue_token
from app.jobs.monthly import run_month
from app.jobs.worker import drain
from app.main import create_app
from app.records.seed import seed
from app.settings import get_settings
from app.work import charges
from app.work.events import events_for
from app.work.gateway import GatewayError, post_approved, post_approved_charge, release_batch
from app.work.roles import load_actor
from app.work.transitions import transition

ROOT = Path(__file__).resolve().parents[3]
JAN = date(2026, 1, 1)
ENTITY = "ENT-CA"
RM = "PER-RM-BAY"
CTRL = "PER-CTRL"
AP = "PER-AP"
SECRET = "test-resolution-secret"
HELD_TOTAL = Decimal("25736.36")


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("generated")
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    return out


@pytest.fixture
def jan(clean, generated, monkeypatch):
    seed(Path(generated), clean["lease_agent"], clean["lease_gateway"])
    # The checker only uses confirmed leases: draft and confirm them first.
    lw.use_documents(monkeypatch, generated)
    lw.draft_and_confirm(clean, generated)
    with clean["lease_agent"].begin() as conn:
        run_month(conn, ENTITY, "2026-01")
    drain(clean["lease_agent"], "resolution")
    return clean


@pytest.fixture
def client(jan):
    settings = dataclasses.replace(get_settings(), session_secret=SECRET,
                                   cors_origins=("http://localhost:3000",))
    app = create_app(settings)
    app.dependency_overrides[api_engine] = lambda: jan["lease_api"]
    app.dependency_overrides[get_gateway_engine] = lambda: jan["lease_gateway"]
    app.dependency_overrides[auth_settings] = lambda: settings
    return TestClient(app)


def as_(client, actor_id):
    client.cookies.set(COOKIE_NAME, issue_token(SECRET, actor_id))
    return client


def q(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def items(eng):
    with eng["lease_reader"].connect() as conn:
        rows = conn.execute(text("""
            SELECT w.id, w.state, w.proposal, w.evidence, w.subject_id, w.reason,
                   c.amount AS billed, c.charge_type
              FROM work_item w JOIN landlord_charge c ON c.id = w.subject_id
             WHERE w.kind = 'CHARGE_CHECK' ORDER BY w.id
        """)).mappings().all()
    return [dict(r, supported=Decimal(str(r["evidence"]["supported"]))) for r in rows]


def held(eng, billed=None, wholly=None):
    out = [i for i in items(eng) if i["proposal"] == "hold"]
    if billed is not None:
        out = [i for i in out if i["billed"] == Decimal(billed)]
    if wholly is True:
        out = [i for i in out if i["supported"] == 0]
    if wholly is False:
        out = [i for i in out if i["supported"] > 0]
    return out


def ledger_total(eng):
    return q(eng["lease_reader"], "SELECT coalesce(sum(debit), 0) FROM journal_line")


def entry_total(eng, item_id):
    return q(eng["lease_reader"], """
        SELECT coalesce(sum(l.debit), 0) FROM journal_line l
          JOIN journal_entry e ON e.id = l.journal_entry_id WHERE e.work_item_id = :i
    """, i=item_id)


def item(eng, item_id):
    return next(i for i in items(eng) if i["id"] == item_id)


def release(eng):
    with eng["lease_gateway"].begin() as conn:
        return release_batch(conn, JAN, AP, entity_id=ENTITY)


def batch_lines(eng):
    payload = q(eng["lease_reader"], "SELECT payload FROM outbox ORDER BY id DESC LIMIT 1")
    return list(csv.DictReader(io.StringIO(payload["csv"])))


def approve(client, actor, item_id, **body):
    return as_(client, actor).post("/api/items/%d/actions/approve" % item_id, json=body or None)


# --------------------------------------------------------------------- the world

def test_january_holds_five_charges_for_25736_36(jan):
    holds = held(jan)
    assert len(holds) == 5
    assert sum((h["billed"] - h["supported"] for h in holds), Decimal("0")) == HELD_TOTAL
    assert len(held(jan, wholly=True)) == 2 and len(held(jan, wholly=False)) == 3
    assert held(jan, billed="19626.65", wholly=True)          # the duplicate rent


# ------------------------------------------------------------- upholding a hold

def test_approving_the_held_duplicate_rent_posts_nothing(jan, client):
    (dup,) = held(jan, billed="19626.65", wholly=True)
    res = approve(client, RM, dup["id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["posting"]["status"] == "closed"
    assert body["posting"]["journal_entry_id"] is None
    assert body["posting"]["disputed"] == 19626.65
    assert body["state"] == "CLOSED"

    after = item(jan, dup["id"])
    assert after["evidence"]["resolution"] == "upheld"
    assert after["evidence"]["resolved_by"] == RM
    assert after["evidence"]["payable"] == "0.00"
    assert ledger_total(jan) == 0
    assert q(jan["lease_reader"], "SELECT count(*) FROM journal_entry") == 0

    with jan["lease_reader"].connect() as conn:
        trail = events_for(conn, "work_item", dup["id"])
    approve_ev, close_ev = trail[-2], trail[-1]
    assert (approve_ev.actor_id, approve_ev.action) == (RM, "approve")
    assert approve_ev.evidence["resolution"] == "upheld"
    assert (close_ev.actor_id, close_ev.action) == ("system:gateway", "close")
    assert close_ev.evidence["disputed_amount"] == "19626.65"

    # The exception screen says so.
    detail = as_(client, RM).get("/api/exceptions/exc_%d" % dup["id"]).json()
    assert (detail["resolution"], detail["payable"], detail["disputed"]) == ("upheld", 0.0, 19626.65)

    # AP: approve one good charge so there is a batch; the duplicate is not in it.
    good = next(i for i in items(jan) if i["proposal"] == "approve")
    assert approve(client, RM, good["id"]).json()["posting"]["status"] == "posted"
    batch = release(jan)
    assert batch.item_count == 1 and batch.total == good["billed"]
    assert {l["charge_id"] for l in batch_lines(jan)} == {good["subject_id"]}


def test_approving_a_partly_wrong_charge_posts_only_the_supported_amount(jan, client):
    for part in held(jan, wholly=False):
        res = approve(client, RM, part["id"])
        assert res.status_code == 200, res.text
        posting = res.json()["posting"]
        assert posting["status"] == "posted"
        assert Decimal(str(posting["amount"])) == part["supported"]
        assert Decimal(str(posting["disputed"])) == part["billed"] - part["supported"]
        assert entry_total(jan, part["id"]) == part["supported"]
        after = item(jan, part["id"])
        assert after["state"] == "POSTED" and after["evidence"]["resolution"] == "upheld"
        key = q(jan["lease_reader"], "SELECT idempotency_key FROM journal_entry "
                                     "WHERE work_item_id = :i", i=part["id"])
        assert key.endswith("|supported")
        # The disputed difference is on no journal line anywhere.
        disputed = part["billed"] - part["supported"]
        assert q(jan["lease_reader"], "SELECT count(*) FROM journal_line WHERE debit = :d "
                 "OR credit = :d OR debit = :b OR credit = :b",
                 d=disputed, b=part["billed"]) == 0

    supported = sum((p["supported"] for p in held(jan, wholly=False)), Decimal("0"))
    assert ledger_total(jan) == supported
    batch = release(jan)
    assert batch.item_count == 3 and batch.total == supported
    lines = batch_lines(jan)
    assert sum(Decimal(l["amount"]) for l in lines) == supported
    assert all(Decimal(l["billed"]) > Decimal(l["amount"]) for l in lines)


def test_approving_the_early_escalation_posts_exactly_16726_50(jan, client):
    """$17,270.11 billed, the escalation applied a year early; the rent
    schedule supports $16,726.50 for January. The $543.61 stays out."""
    (early,) = held(jan, billed="17270.11")
    assert early["supported"] == Decimal("16726.50")
    res = approve(client, RM, early["id"])
    assert res.json()["posting"]["status"] == "posted"
    assert entry_total(jan, early["id"]) == Decimal("16726.50")
    assert ledger_total(jan) == Decimal("16726.50")
    ap = q(jan["lease_reader"], """
        SELECT sum(l.credit) FROM journal_line l JOIN account a ON a.id = l.account_id
         WHERE a.name = 'Accounts payable'""")
    assert ap == Decimal("16726.50")
    for figure in (Decimal("543.61"), Decimal("17270.11")):
        assert q(jan["lease_reader"], "SELECT count(*) FROM journal_line WHERE debit = :f "
                 "OR credit = :f", f=figure) == 0
    assert release(jan).total == Decimal("16726.50")


def test_reposting_an_upheld_hold_adds_nothing(jan, client):
    (part, *_) = held(jan, wholly=False)
    entry = approve(client, RM, part["id"]).json()["posting"]["journal_entry_id"]
    before = q(jan["lease_reader"], "SELECT count(*) FROM journal_line")
    with jan["lease_gateway"].begin() as conn:
        assert post_approved(conn, ENTITY, JAN) == []
        assert post_approved_charge(conn, part["id"]) == entry      # the key replays
    assert q(jan["lease_reader"], "SELECT count(*) FROM journal_line") == before


def test_a_disputed_item_never_posts_twice_under_two_keys(jan, client):
    """Force an upheld, already-posted item back to APPROVED as an override
    (the owner can; nobody else can): the gateway still refuses a second,
    as-billed entry, because the item already posted its supported one."""
    (part, *_) = held(jan, wholly=False)
    approve(client, RM, part["id"])
    assert entry_total(jan, part["id"]) == part["supported"]
    with jan["owner"].begin() as conn:
        conn.execute(text("""
            UPDATE work_item SET state = 'APPROVED',
                   evidence = evidence || '{"resolution": "pay_as_billed"}'::jsonb WHERE id = :i
        """), {"i": part["id"]})
    with pytest.raises(GatewayError):
        with jan["lease_gateway"].begin() as conn:
            post_approved_charge(conn, part["id"])
    assert entry_total(jan, part["id"]) == part["supported"]


def test_an_override_set_in_evidence_without_a_controller_approval_pays_nothing_disputed(jan):
    """pay_as_billed written into evidence some other way (here by the
    checker's re-proposal) is not an override: the gateway refuses it."""
    (dup,) = held(jan, billed="19626.65", wholly=True)
    with jan["lease_agent"].begin() as conn:
        checker = load_actor(conn, "agent:checker")
        transition(conn, checker, dup["id"], "propose", patch={
            "evidence": dict(dup["evidence"], resolution="pay_as_billed")})
    with jan["lease_api"].begin() as conn:
        transition(conn, load_actor(conn, CTRL), dup["id"], "approve")   # bypasses charges
    with pytest.raises(GatewayError, match="pay-as-billed"):
        with jan["lease_gateway"].begin() as conn:
            post_approved_charge(conn, dup["id"])
    assert ledger_total(jan) == 0


# ------------------------------------------------------------- the override

def test_pay_as_billed_is_refused_for_a_regional_manager_and_on_record(jan, client):
    (dup,) = held(jan, billed="19626.65", wholly=True)
    res = approve(client, RM, dup["id"], reason="landlord insists",
                  patch={"resolution": "pay_as_billed"})
    assert res.status_code == 403
    assert "controller" in res.json()["detail"]
    with jan["lease_reader"].connect() as conn:
        last = events_for(conn, "work_item", dup["id"])[-1]
    assert (last.actor_id, last.action, last.allowed) == (RM, "approve", False)
    assert last.evidence == {"resolution": "pay_as_billed"}
    assert item(jan, dup["id"])["state"] == "PROPOSED"

    res = as_(client, RM).post("/api/exceptions/exc_%d/pay-as-billed" % dup["id"],
                               json={"reason": "landlord insists"})
    assert res.status_code == 403
    assert ledger_total(jan) == 0


@pytest.mark.parametrize("body", [None, {}, {"reason": ""}, {"reason": "   "}])
def test_pay_as_billed_needs_a_reason(jan, client, body):
    (dup,) = held(jan, billed="19626.65", wholly=True)
    res = as_(client, CTRL).post("/api/exceptions/exc_%d/pay-as-billed" % dup["id"], json=body)
    assert res.status_code == 422
    res = approve(client, CTRL, dup["id"], patch={"resolution": "pay_as_billed"},
                  **({"reason": body["reason"]} if body and "reason" in body else {}))
    assert res.status_code == 422
    assert item(jan, dup["id"])["state"] == "PROPOSED"
    assert ledger_total(jan) == 0


def test_the_controller_pays_a_held_charge_as_billed_and_the_trail_says_who_and_why(jan, client):
    (dup,) = held(jan, billed="19626.65", wholly=True)
    why = "Landlord confirmed a second suite under a side letter; paying pending amendment."
    res = as_(client, CTRL).post("/api/exceptions/exc_%d/pay-as-billed" % dup["id"],
                                 json={"reason": why})
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "POSTED" and res.json()["posting"]["status"] == "posted"
    assert entry_total(jan, dup["id"]) == Decimal("19626.65")
    key = q(jan["lease_reader"], "SELECT idempotency_key FROM journal_entry WHERE work_item_id = :i",
            i=dup["id"])
    assert key.endswith("|as_billed")

    after = item(jan, dup["id"])
    assert after["evidence"]["resolution"] == "pay_as_billed"
    assert after["evidence"]["resolved_by"] == CTRL
    assert after["evidence"]["override_reason"] == why
    with jan["lease_reader"].connect() as conn:
        trail = events_for(conn, "work_item", dup["id"])
    approve_ev = next(e for e in reversed(trail) if e.action == "approve" and e.allowed)
    assert (approve_ev.actor_id, approve_ev.reason) == (CTRL, why)
    assert approve_ev.evidence["resolution"] == "pay_as_billed"
    assert trail[-1].evidence["resolution"] == "pay_as_billed"

    audit = as_(client, CTRL).get("/api/audit", params={"subject_type": "work_item",
                                                        "subject_id": str(dup["id"])}).json()
    assert any(e["actor_id"] == CTRL and e["reason"] == why for e in audit["events"])

    batch = release(jan)
    assert batch.item_count == 1 and batch.total == Decimal("19626.65")


def test_the_items_route_takes_the_override_too(jan, client):
    (part, *_) = held(jan, wholly=False)
    res = approve(client, CTRL, part["id"], reason="Escalation agreed early by email",
                  patch={"resolution": "pay_as_billed"})
    assert res.status_code == 200, res.text
    assert entry_total(jan, part["id"]) == part["billed"]


def test_an_approve_of_a_charge_check_takes_no_other_patch(jan, client):
    (dup,) = held(jan, billed="19626.65", wholly=True)
    res = approve(client, CTRL, dup["id"], reason="x",
                  patch={"evidence": {"resolution": "pay_as_billed"}})
    assert res.status_code == 422
    assert item(jan, dup["id"])["state"] == "PROPOSED"


def test_an_override_after_an_unposted_upheld_hold_posts_once_as_billed(jan, client):
    """Upheld but not yet posted (the period was closed), pulled back, then
    overridden: the as-billed entry is the only one; the supported one never
    posted."""
    (part, *_) = held(jan, wholly=False)
    with jan["owner"].begin() as conn:
        conn.execute(text("UPDATE period SET status = 'closed' WHERE entity_id = :e AND period = :p"),
                     {"e": ENTITY, "p": JAN})
    assert approve(client, RM, part["id"]).json()["posting"]["status"] == "pending"
    with jan["owner"].begin() as conn:
        conn.execute(text("UPDATE period SET status = 'open' WHERE entity_id = :e AND period = :p"),
                     {"e": ENTITY, "p": JAN})
    assert as_(client, CTRL).post("/api/items/%d/actions/hold" % part["id"],
                                  json={"reason": "landlord called"}).status_code == 200
    assert as_(client, CTRL).post("/api/items/%d/actions/resume" % part["id"]).status_code == 200
    res = approve(client, CTRL, part["id"], reason="escalation agreed",
                  patch={"resolution": "pay_as_billed"})
    assert res.json()["posting"]["status"] == "posted"
    assert q(jan["lease_reader"], "SELECT count(*) FROM journal_entry WHERE work_item_id = :i",
             i=part["id"]) == 1
    assert entry_total(jan, part["id"]) == part["billed"]


# ------------------------------------------------------- unchanged: a good charge

def test_an_approve_proposed_charge_still_posts_as_billed(jan, client):
    good = next(i for i in items(jan) if i["proposal"] == "approve")
    res = approve(client, RM, good["id"])
    assert res.status_code == 200
    posting = res.json()["posting"]
    assert posting["status"] == "posted" and Decimal(str(posting["amount"])) == good["billed"]
    assert entry_total(jan, good["id"]) == good["billed"]
    key = q(jan["lease_reader"], "SELECT idempotency_key FROM journal_entry WHERE work_item_id = :i",
            i=good["id"])
    assert not key.endswith(("|supported", "|as_billed"))
    with jan["lease_reader"].connect() as conn:
        post_ev = events_for(conn, "work_item", good["id"])[-1]
    assert post_ev.evidence == {"journal_entry_id": posting["journal_entry_id"]}
    assert "resolution" not in item(jan, good["id"])["evidence"]

    res = approve(client, CTRL, next(i for i in items(jan) if i["proposal"] == "approve"
                                     and i["state"] == "PROPOSED")["id"],
                  reason="x", patch={"resolution": "pay_as_billed"})
    assert res.status_code == 422                     # nothing disputed to override


def test_payable_never_exceeds_billed_and_defaults_to_upheld():
    hold = {"kind": "CHARGE_CHECK", "proposal": "hold"}
    assert charges.payable(dict(hold, evidence={"supported": 900}), "1000").amount == Decimal("900.00")
    assert charges.payable(dict(hold, evidence={"supported": 1200}), "1000").amount == Decimal("1000.00")
    assert charges.payable(dict(hold, evidence={}), "1000").amount == 0
    assert charges.payable(dict(hold, evidence={"supported": "junk"}), "1000").disputed == Decimal("1000.00")
    assert charges.payable(dict(hold, evidence={"supported": -5}), "1000").amount == 0
    good = {"kind": "CHARGE_CHECK", "proposal": "approve", "evidence": {"supported": 1}}
    assert charges.payable(good, "1000").amount == Decimal("1000.00")
