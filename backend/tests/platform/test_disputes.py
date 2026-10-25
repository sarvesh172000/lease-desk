"""Disputes and landlord correspondence (work/disputes.py, the gateway's
dispute doors, api/disputes.py) on a real January.

datagen.build -> seed -> confirm -> run_month: five holds. The regional
manager upholds the duplicate rent ($19,626.65, nothing supported) and the
early escalation ($543.61 of $17,270.11 disputed). From there:

  the duplicate      letter drafted -> RM approves -> sent once -> controller
                     recognises the receivable -> the landlord's full credit
                     memo clears it -> both items close
  the escalation     partial credit ($135.90 of $543.61, datagen/replies.py's
                     25%) clears that much, reopens the rest to the RM, who
                     concedes; a controller closes it and the remainder is
                     written off to lease cost
  a refusal          reopens the letter with the landlord's reason; pursuing
                     it sends a follow-up, round 2, once

Every step runs as the database role its process uses, the ledger stays
balanced, verify_chain() passes and replay rebuilds the work items exactly.
"""

import dataclasses
import email
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
from app.jobs import clock
from app.jobs.monthly import run_month
from app.jobs.queue import enqueue
from app.jobs.worker import drain
from app.ledger.trial_balance import trial_balance
from app.main import create_app
from app.records.seed import seed
from app.settings import get_settings
from app.work import disputes
from app.work.events import events_for, verify_chain
from app.work.gateway import send_dispute_letter, send_outbox, sync_disputes
from app.work.replay import replay
from app.work.roles import load_actor
from app.work.transitions import Denied, transition
from datagen.company import build_company
from datagen.replies import FULL_CREDIT, PARTIAL_CREDIT, build_replies

ROOT = Path(__file__).resolve().parents[3]
ENTITY = "ENT-CA"
RM = "PER-RM-BAY"
RM_DESERT = "PER-RM-DESERT"
CTRL = "PER-CTRL"
AP = "PER-AP"
AUD = "PER-AUD"
SECRET = "test-disputes-secret"
DUP_BILLED = Decimal("19626.65")
EARLY_BILLED = Decimal("17270.11")
EARLY_DISPUTED = Decimal("543.61")
LETTER_DAY = date(2026, 2, 3)


# ---------------------------------------------------------------- the world

@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("generated")
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    return out


@pytest.fixture
def jan(clean, generated, monkeypatch):
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
    lw.draft_and_confirm(clean, generated)
    with clean["lease_agent"].begin() as conn:
        run_month(conn, ENTITY, "2026-01")
        clock.set_today(conn, LETTER_DAY)
    drain(clean["lease_agent"], "disputes")
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
    with eng["lease_reader"].connect() as conn:
        return conn.execute(text(sql), params).scalar()


def rows(eng, sql, **params):
    with eng["lease_reader"].connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def held(eng, billed):
    return rows(eng, """
        SELECT w.* FROM work_item w JOIN landlord_charge c ON c.id = w.subject_id
         WHERE w.kind = 'CHARGE_CHECK' AND w.proposal = 'hold' AND c.amount = :b
    """, b=Decimal(billed))[0]


def uphold(client, item_id):
    res = as_(client, RM).post("/api/items/%d/actions/approve" % item_id)
    assert res.status_code == 200, res.text
    return res.json()


def draft(eng):
    with eng["lease_agent"].begin() as conn:
        return disputes.draft_disputes(conn, ENTITY)


@pytest.fixture
def upheld(jan, client):
    """The duplicate rent and the early escalation, upheld and drafted."""
    dup, early = held(jan, DUP_BILLED), held(jan, EARLY_BILLED)
    assert uphold(client, dup["id"])["state"] == "CLOSED"       # nothing supported, nothing paid
    assert uphold(client, early["id"])["state"] == "POSTED"     # the supported $16,726.50 paid
    result = draft(jan)
    assert result["drafted"] == [disputes.dispute_id_for(dup["id"]),
                                 disputes.dispute_id_for(early["id"])]
    return {"dup": disputes.dispute_id_for(dup["id"]),
            "early": disputes.dispute_id_for(early["id"])}


def dispute(eng, dispute_id):
    return rows(eng, "SELECT * FROM dispute WHERE id = :id", id=dispute_id)[0]


def item_state(eng, item_id):
    return q(eng, "SELECT state FROM work_item WHERE id = :id", id=item_id)


def receivable_item(eng, dispute_id):
    return rows(eng, "SELECT * FROM work_item WHERE kind = 'DISPUTE_RECEIVABLE' "
                     "AND subject_id = :id", id=dispute_id)[0]


def account_balance(eng, name):
    """Debits minus credits on one account, across the entity."""
    return q(eng, """
        SELECT coalesce(sum(l.debit - l.credit), 0) FROM journal_line l
          JOIN account a ON a.id = l.account_id WHERE a.name = :n
    """, n=name)


def books_balance(eng):
    with eng["lease_reader"].connect() as conn:
        tb = trial_balance(conn, ENTITY, date(2026, 1, 1), date(2026, 12, 1))
        assert tb.total_debits == tb.total_credits
        assert verify_chain(conn) is None
    with eng["owner"].begin() as conn:
        report = replay(conn)
        assert report.identical, report.differences
    return tb


def datagen_replies(dup_amount=DUP_BILLED, early_amount=EARLY_DISPUTED):
    """The teammate's landlord replies, for our two disputes: the first is a
    full credit, the second a 25% partial (datagen/replies.py cycles)."""
    replies = build_replies(build_company(), [
        {"clinic_id": "STORE-01", "claimed": float(dup_amount), "about": "duplicate base rent",
         "sent": LETTER_DAY, "message_id": "dispute-dup-r1@lease-desk"},
        {"clinic_id": "STORE-03", "claimed": float(early_amount), "about": "escalation timing",
         "sent": LETTER_DAY, "message_id": "dispute-early-r1@lease-desk"},
    ])
    assert [r.outcome for r in replies] == [FULL_CREDIT, PARTIAL_CREDIT]
    return replies


def reply_body(reply, **extra):
    payload = disputes.reply_from_datagen(reply)
    payload["received_on"] = payload["received_on"].isoformat()
    payload.update(extra)
    return {k: v for k, v in payload.items() if v is not None}


def send_and_recognise(jan, client, dispute_id):
    res = as_(client, RM).post("/api/disputes/%s/approve" % dispute_id,
                               json={"reason": "Letter reviewed; send it."})
    assert res.status_code == 200, res.text
    assert res.json()["dispute"]["status"] == "sent"
    assert draft(jan)["receivables_proposed"] == [dispute_id]
    res = as_(client, CTRL).post("/api/disputes/%s/receivable/approve" % dispute_id,
                                 json={"reason": "Clear duplicate; recovery probable."})
    assert res.status_code == 200, res.text
    assert res.json()["gateway_error"] is None
    return res.json()


# ------------------------------------------------------------------ drafting

def test_an_upheld_hold_becomes_a_drafted_letter_from_facts_only(jan, upheld):
    d = dispute(jan, upheld["dup"])
    assert (d["status"], d["amount"], d["billed"], d["supported"]) == (
        "drafted", DUP_BILLED, DUP_BILLED, Decimal("0.00"))
    assert d["notice_to"] == {
        "landlord_id": "LL-SERRA", "name": "Serramonte Retail Partners LLC", "attn": "Dana Reyes",
        "address": "1500 Serramonte Blvd, Suite 400, Daly City, CA 94015",
        "email": "dana.reyes@serramonteretail.example"}
    letter = d["letter"]
    flat = " ".join(letter.split())
    for needle in ("Serramonte Retail Partners LLC", "Attn: Dana Reyes, Authorized Representative",
                   "1500 Serramonte Blvd, Suite 400, Daly City, CA 94015", "Section 3.2",
                   "Base Rent shall be due and payable in advance on the first (1st) day",
                   "SERRA-202601-0002", "SERRA-202601-0001", "$19,626.65", "February 3, 2026",
                   "Billed                     $   19,626.65",
                   "Supported by the Lease     $        0.00",
                   "Disputed                   $   19,626.65",
                   "Priya Raghunathan", "Lease LEASE-01", upheld["dup"]):
        assert needle in letter or needle in flat, needle
    # The math and the evidence are structured, not just prose.
    facts = d["facts"]
    assert facts["math"] == {"billed": "19626.65", "supported": "0.00", "disputed": "19626.65"}
    assert facts["lease"]["section"] == "3.2" and facts["lease"]["document_id"]
    assert [doc["invoice_id"] for doc in facts["documents"] if doc["kind"] == "invoice"] == [
        "SERRA-202601-0002", "SERRA-202601-0001"]

    early = dispute(jan, upheld["early"])
    assert (early["amount"], early["supported"]) == (EARLY_DISPUTED, Decimal("16726.50"))
    assert "We have approved the undisputed $16,726.50 for payment" in early["letter"]
    assert "Section 3.3" in early["letter"] and "Alicia Moreno" in early["letter"]
    assert early["facts"]["lease"]["page"] is not None          # from the confirmed lease_term

    # The DISPUTE item: proposed by the disputes agent, in the clinic's region.
    item = rows(jan, "SELECT * FROM work_item WHERE id = :i", i=d["work_item_id"])[0]
    assert (item["kind"], item["state"], item["subject_type"], item["subject_id"]) == (
        "DISPUTE", "PROPOSED", "dispute", upheld["dup"])
    assert (item["proposed_by"], item["proposal"], item["region_id"]) == (
        "agent:disputes", "send_letter", "REG-BAY")
    assert item["evidence"]["letter"] == letter
    # Drafted is on the dispute's own history.
    with jan["lease_reader"].connect() as conn:
        trail = events_for(conn, "dispute", upheld["dup"])
    assert [(e.actor_id, e.action) for e in trail] == [("agent:disputes", "draft")]


def test_drafting_is_idempotent_and_only_for_upheld_holds(jan, upheld, client):
    before = q(jan, "SELECT count(*) FROM audit_event")
    assert draft(jan) == {"drafted": [], "receivables_proposed": []}
    assert q(jan, "SELECT count(*) FROM audit_event") == before
    # Three holds are still unresolved: no dispute for them.
    assert q(jan, "SELECT count(*) FROM dispute") == 2
    # A hold paid as billed by the controller disputes nothing.
    other = rows(jan, """SELECT w.id FROM work_item w WHERE w.kind = 'CHARGE_CHECK'
                          AND w.proposal = 'hold' AND w.state = 'PROPOSED' ORDER BY w.id""")[0]
    res = as_(client, CTRL).post("/api/items/%d/actions/approve" % other["id"], json={
        "reason": "agreed by phone", "patch": {"resolution": "pay_as_billed"}})
    assert res.status_code == 200, res.text
    assert draft(jan)["drafted"] == []


def test_upholding_a_hold_queues_the_draft_and_the_worker_writes_it(jan, client):
    dup = held(jan, DUP_BILLED)
    uphold(client, dup["id"])
    # The uphold queued the sweep itself, once: nobody runs a job by hand.
    assert q(jan, "SELECT count(*) FROM job WHERE kind = 'disputes' AND idempotency_key = :k",
             k="disputes:upheld:%d" % dup["id"]) == 1
    (outcome,) = drain(jan["lease_agent"], "disputes")
    assert outcome.status == "done"
    assert outcome.result["drafted"] == [disputes.dispute_id_for(dup["id"])]
    # A sweep queued by anything else finds nothing left to draft.
    with jan["lease_agent"].begin() as conn:
        enqueue(conn, "disputes", {"entity_id": ENTITY})
    (again,) = drain(jan["lease_agent"], "disputes")
    assert again.result["drafted"] == []


def test_a_hold_paid_as_billed_queues_no_draft(jan, client):
    other = held(jan, DUP_BILLED)
    res = as_(client, CTRL).post("/api/items/%d/actions/approve" % other["id"], json={
        "reason": "agreed by phone", "patch": {"resolution": "pay_as_billed"}})
    assert res.status_code == 200, res.text
    assert q(jan, "SELECT count(*) FROM job WHERE idempotency_key LIKE 'disputes:upheld:%'") == 0


# ------------------------------------------------- the full arc: the duplicate

def test_duplicate_rent_letter_sent_once_credit_memo_clears_the_receivable(jan, upheld, client,
                                                                           tmp_path):
    did = upheld["dup"]
    d = dispute(jan, did)

    # The regional manager approves; the gateway queues the email once.
    res = as_(client, RM).post("/api/disputes/%s/approve" % did, json={"reason": "Send it."})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dispute"]["status"] == "sent" and body["gateway_error"] is None
    assert body["items"]["letter"]["state"] == "APPROVED"     # out, awaiting the landlord
    assert len(body["outbox"]) == 1 and body["outbox"][0]["status"] == "pending"
    with jan["lease_gateway"].begin() as conn:                 # sending twice sends once
        assert send_dispute_letter(conn, did) == body["outbox"][0]["id"]
        assert sync_disputes(conn, dispute_id=did).sent == []
    assert q(jan, "SELECT count(*) FROM outbox WHERE kind = 'email'") == 1

    with jan["lease_gateway"].connect() as conn:
        assert len(send_outbox(conn, tmp_path)) == 1
        assert send_outbox(conn, tmp_path) == []
    (eml,) = tmp_path.glob("*.eml")
    msg = email.message_from_string(eml.read_text())
    assert msg["To"] == "Dana Reyes <dana.reyes@serramonteretail.example>"
    assert "SERRA-202601-0002" in msg["Subject"]
    assert msg.get_payload(decode=True).decode() == d["letter"]
    assert q(jan, "SELECT status FROM outbox WHERE kind = 'email'") == "sent"

    # Once the letter is out, recognising the claim is proposed; only a
    # controller may approve it, and a refusal is on record.
    assert draft(jan)["receivables_proposed"] == [did]
    res = as_(client, RM).post("/api/disputes/%s/receivable/approve" % did)
    assert res.status_code == 403 and "controller" in res.json()["detail"]
    rec = receivable_item(jan, did)
    with jan["lease_reader"].connect() as conn:
        last = events_for(conn, "work_item", rec["id"])[-1]
    assert (last.actor_id, last.action, last.allowed) == (RM, "approve", False)
    assert account_balance(jan, "Landlord receivable") == 0

    res = as_(client, CTRL).post("/api/disputes/%s/receivable/approve" % did,
                                 json={"reason": "Clear duplicate; recovery probable."})
    assert res.status_code == 200, res.text
    assert res.json()["receivable"]["open"] == float(DUP_BILLED)
    assert account_balance(jan, "Landlord receivable") == DUP_BILLED
    assert account_balance(jan, "Accounts payable") == -(Decimal("16726.50") + DUP_BILLED)
    assert account_balance(jan, "Lease cost") == Decimal("16726.50")   # no P&L effect
    assert item_state(jan, rec["id"]) == "POSTED"

    # The landlord's full credit memo (datagen/replies.py), recorded by AP.
    full, _partial = datagen_replies()
    res = as_(client, AP).post("/api/disputes/%s/reply" % did, json=reply_body(full))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dispute"]["status"] == "credited"
    assert body["dispute"]["credited_amount"] == float(DUP_BILLED)
    assert body["receivable"]["open"] == 0 and body["receivable"]["cleared"] == float(DUP_BILLED)
    assert body["items"]["letter"]["state"] == "CLOSED"
    assert body["items"]["receivable"]["state"] == "CLOSED"
    assert account_balance(jan, "Landlord receivable") == 0
    assert account_balance(jan, "Accounts payable") == -Decimal("16726.50")
    assert [h["to_status"] for h in body["history"] if h["to_status"]] == [
        "drafted", "sent", "credited"]
    assert [h["action"] for h in body["history"]] == [
        "draft", "send_letter", "recognize_receivable", "reply", "clear_receivable"]

    # Everything again: nothing more.
    footprint = {t: q(jan, "SELECT count(*) FROM %s" % t)
                 for t in ("journal_entry", "outbox", "audit_event", "work_item")}
    with jan["lease_gateway"].begin() as conn:
        assert sync_disputes(conn) == type(sync_disputes(conn))([], [], [], [], [])
    assert draft(jan) == {"drafted": [], "receivables_proposed": []}
    assert {t: q(jan, "SELECT count(*) FROM %s" % t) for t in footprint} == footprint
    res = as_(client, AP).post("/api/disputes/%s/reply" % did, json=reply_body(full))
    assert res.status_code == 409
    books_balance(jan)


def test_the_register_lists_and_scopes_disputes(jan, upheld, client):
    res = as_(client, CTRL).get("/api/disputes")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2 and body["counts"]["drafted"] == 2
    assert {d["id"] for d in body["disputes"]} == set(upheld.values())
    assert as_(client, RM).get("/api/disputes").json()["total"] == 2
    assert as_(client, RM_DESERT).get("/api/disputes").json()["total"] == 0
    assert as_(client, RM_DESERT).get("/api/disputes/%s" % upheld["dup"]).status_code == 404
    detail = as_(client, AUD).get("/api/disputes/%s" % upheld["dup"]).json()
    assert detail["letter"].startswith("Northbay")
    assert detail["reply_outcomes"] == []
    assert as_(client, AP).get("/api/disputes/%s" % upheld["dup"]).json()["reply_outcomes"] == [
        "acknowledged", "queried", "full_credit"]
    assert as_(client, CTRL).get("/api/disputes?status=bogus").status_code == 422
    assert as_(client, CTRL).get("/api/disputes/DSP-999999").status_code == 404


# ----------------------------------------------- partial credit and concession

def test_early_escalation_partial_credit_clears_part_and_reopens_the_rest(jan, upheld, client):
    did = upheld["early"]
    send_and_recognise(jan, client, did)
    assert account_balance(jan, "Landlord receivable") == EARLY_DISPUTED

    _full, partial = datagen_replies()
    assert Decimal(str(partial.granted)) == Decimal("135.90")
    # An AP clerk may not record a partial credit: it changes what we recover.
    res = as_(client, AP).post("/api/disputes/%s/reply" % did, json=reply_body(partial))
    assert res.status_code == 403 and "controller" in res.json()["detail"]
    with jan["lease_reader"].connect() as conn:
        last = events_for(conn, "dispute", did)[-1]
    assert (last.actor_id, last.action, last.allowed) == (AP, "reply", False)

    res = as_(client, CTRL).post("/api/disputes/%s/reply" % did, json=reply_body(partial))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dispute"]["status"] == "partially_credited"
    assert body["dispute"]["credited_amount"] == 135.90
    assert body["receivable"]["open"] == pytest.approx(407.71)
    assert account_balance(jan, "Landlord receivable") == Decimal("407.71")
    # Reopened to the regional manager with the landlord's reason.
    letter = body["items"]["letter"]
    assert letter["state"] == "HELD"
    assert "credited $135.90 and refused the remaining $407.71" in letter["reason"]
    assert "Section 4.2" in letter["reason"]
    queue = as_(client, RM).get("/api/items", params={"state": "HELD", "kind": "DISPUTE"}).json()
    assert [i["id"] for i in queue["items"]] == [body["dispute"]["work_item_id"]]
    # Recognising more is refused once the landlord has refused part of it.
    assert as_(client, CTRL).post("/api/disputes/%s/receivable/approve" % did).status_code == 409

    # The RM concedes (reject); the write-off waits for the controller.
    item_id = body["dispute"]["work_item_id"]
    res = as_(client, RM).post("/api/items/%d/actions/reject" % item_id,
                               json={"reason": "Landlord is right about the remainder."})
    assert res.status_code == 200, res.text
    with jan["lease_gateway"].begin() as conn:
        assert sync_disputes(conn, dispute_id=did).written_off == []
    assert as_(client, RM).post("/api/items/%d/actions/close" % item_id).status_code == 403
    res = as_(client, CTRL).post("/api/items/%d/actions/close" % item_id,
                                 json={"reason": "Concession approved."})
    assert res.status_code == 200, res.text
    # Closing through the queue ran the gateway: the write-off is done, once.
    assert res.json()["dispute"]["gateway_error"] is None
    with jan["lease_gateway"].begin() as conn:
        assert sync_disputes(conn, dispute_id=did).written_off == []
    assert account_balance(jan, "Landlord receivable") == 0
    assert account_balance(jan, "Lease cost") == Decimal("16726.50") + Decimal("407.71")
    assert item_state(jan, receivable_item(jan, did)["id"]) == "CLOSED"
    books_balance(jan)


# ------------------------------------------------------- refusal and pursuit

def test_a_refusal_reopens_the_letter_and_pursuing_sends_one_follow_up(jan, upheld, client):
    did = upheld["dup"]
    assert as_(client, RM).post("/api/disputes/%s/approve" % did).status_code == 200
    why = "Two invoices were issued because the first was sent to the wrong suite."
    res = as_(client, AP).post("/api/disputes/%s/reply" % did,
                               json={"outcome": "refused", "reason": why})
    assert res.status_code == 403                                 # controller-only
    res = as_(client, CTRL).post("/api/disputes/%s/reply" % did, json={
        "outcome": "refused", "reason": why, "sender": "dana.reyes@serramonteretail.example"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dispute"]["status"] == "refused" and body["refusal_reason"] == why
    assert body["items"]["letter"]["state"] == "HELD" and why in body["items"]["letter"]["reason"]
    assert body["receivable"]["recognized"] == 0
    assert draft(jan)["receivables_proposed"] == []                # not probable any more

    # A manager from another region cannot pick it up.
    item_id = body["dispute"]["work_item_id"]
    assert as_(client, RM_DESERT).post("/api/items/%d/actions/resume" % item_id).status_code == 403
    # The RM pursues: resume, approve again; the gateway sends round 2 once.
    assert as_(client, RM).post("/api/items/%d/actions/resume" % item_id).status_code == 200
    res = as_(client, RM).post("/api/disputes/%s/approve" % did, json={"reason": "We maintain it."})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dispute"]["status"] == "sent"
    assert [o["round"] for o in body["outbox"]] == [1, 2]
    follow_up = q(jan, "SELECT payload FROM outbox WHERE idempotency_key = :k",
                  k="dispute_letter:%s:2" % did)
    assert "follow-up" in follow_up["subject"] and why in " ".join(follow_up["body"].split())
    assert follow_up["in_reply_to"] == "dispute-%s-r1@lease-desk" % did.lower()
    with jan["lease_gateway"].begin() as conn:
        assert sync_disputes(conn).sent == []
    assert q(jan, "SELECT count(*) FROM outbox WHERE kind = 'email'") == 2
    books_balance(jan)


# ------------------------------------------------------------ who may do what

def test_only_the_regions_manager_approves_a_letter(jan, upheld, client):
    did = upheld["dup"]
    item_id = dispute(jan, did)["work_item_id"]
    res = as_(client, RM_DESERT).post("/api/items/%d/actions/approve" % item_id)
    assert res.status_code == 403 and "region" in res.json()["detail"]
    assert as_(client, RM_DESERT).post("/api/disputes/%s/approve" % did).status_code == 404
    assert as_(client, AP).post("/api/disputes/%s/approve" % did).status_code == 403
    with jan["lease_api"].begin() as conn:
        with pytest.raises(Denied, match="region"):
            transition(conn, load_actor(conn, RM_DESERT), item_id, "approve")
    with jan["lease_reader"].connect() as conn:
        refused = [e for e in events_for(conn, "work_item", item_id) if not e.allowed]
    assert {e.actor_id for e in refused} == {RM_DESERT, AP}
    assert q(jan, "SELECT count(*) FROM outbox") == 0
    assert dispute(jan, did)["status"] == "drafted"
    # The disputes agent cannot approve its own letter either.
    with jan["lease_agent"].begin() as conn:
        with pytest.raises(Denied):
            transition(conn, load_actor(conn, "agent:disputes"), item_id, "approve")
    # Approving through the queue works the same way, and sends the letter.
    res = as_(client, RM).post("/api/items/%d/actions/approve" % item_id)
    assert res.status_code == 200, res.text
    sent = res.json()["dispute"]
    assert (sent["id"], sent["status"], sent["gateway_error"]) == (did, "sent", None)
    assert sent["notice_to"]["email"] == "dana.reyes@serramonteretail.example"
    assert q(jan, "SELECT count(*) FROM outbox") == 1
    with jan["lease_gateway"].begin() as conn:
        assert sync_disputes(conn).sent == []
    # The letter is out, so the disputes sweep is queued to propose the receivable.
    assert q(jan, "SELECT count(*) FROM job WHERE idempotency_key LIKE :k",
             k="disputes:sent:%s:%%" % did) == 1
    outcomes = drain(jan["lease_agent"], "disputes")
    assert sum((o.result["receivables_proposed"] for o in outcomes), []) == [did]


def test_a_reply_must_come_from_the_authorized_representative(jan, upheld, client):
    did = upheld["dup"]
    as_(client, RM).post("/api/disputes/%s/approve" % did)
    res = as_(client, AP).post("/api/disputes/%s/reply" % did, json={
        "outcome": "full_credit", "credit_memo_ref": "CM-1",
        "sender": "ktran@crestpointpm.example"})                   # the property manager
    assert res.status_code == 422 and "authorized representative" in res.json()["detail"]
    assert dispute(jan, did)["status"] == "sent"


@pytest.mark.parametrize("body, status", [
    ({"outcome": "partial_credit", "granted": 0, "reason": "x"}, 422),
    ({"outcome": "partial_credit", "granted": 19626.65, "reason": "x"}, 422),
    ({"outcome": "partial_credit", "granted": 10, "credit_memo_ref": "CM-2"}, 422),   # no reason
    ({"outcome": "full_credit", "granted": 5, "credit_memo_ref": "CM-3"}, 422),
    ({"outcome": "full_credit"}, 422),                                                 # no memo
    ({"outcome": "maybe"}, 422),
])
def test_malformed_replies_write_nothing(jan, upheld, client, body, status):
    did = upheld["dup"]
    as_(client, RM).post("/api/disputes/%s/approve" % did)
    before = q(jan, "SELECT count(*) FROM audit_event")
    res = as_(client, CTRL).post("/api/disputes/%s/reply" % did, json=body)
    assert res.status_code == status, res.text
    assert q(jan, "SELECT count(*) FROM audit_event") == before
    assert dispute(jan, did)["status"] == "sent"


def test_auditors_and_managers_cannot_record_replies_and_are_on_record(jan, upheld, client):
    did = upheld["dup"]
    as_(client, RM).post("/api/disputes/%s/approve" % did)
    for who in (AUD, RM):
        res = as_(client, who).post("/api/disputes/%s/reply" % did,
                                    json={"outcome": "acknowledged"})
        assert res.status_code == 403
    with jan["lease_reader"].connect() as conn:
        refused = [(e.actor_id, e.allowed) for e in events_for(conn, "dispute", did)
                   if e.action == "reply"]
    assert refused == [(AUD, False), (RM, False)]
    res = as_(client, AP).post("/api/disputes/%s/reply" % did, json={"outcome": "acknowledged"})
    assert res.status_code == 200 and res.json()["dispute"]["status"] == "acknowledged"


def test_a_reply_before_the_letter_is_sent_is_a_conflict(jan, upheld, client):
    res = as_(client, CTRL).post("/api/disputes/%s/reply" % upheld["dup"],
                                 json={"outcome": "acknowledged"})
    assert res.status_code == 409


def test_the_lease_agent_cannot_send_or_post_a_dispute(jan, upheld):
    with jan["lease_agent"].connect() as conn:
        with pytest.raises(Exception, match="permission denied"):
            conn.execute(text("UPDATE dispute SET status = 'credited'"))
        conn.rollback()
    with jan["lease_api"].connect() as conn:
        with pytest.raises(Exception, match="permission denied"):
            conn.execute(text("UPDATE dispute SET receivable_entry_id = 1"))
        conn.rollback()

