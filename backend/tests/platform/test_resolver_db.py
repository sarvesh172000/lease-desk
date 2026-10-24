"""The resolver on a real January: sources, confidence and route on every
charge check (without changing the 12 items / 5 holds / $25,736.36 outcome),
the "Escalates" demo beat end to end, the busy-approver job (reminders on
business days, escalation after the SLA, the undisputed part paid when the
invoice falls due), and the two read endpoints.

Every write runs as the role its process uses: the checker and the reminders
job as lease_agent (the job through the real worker), people through
lease_api, test-only data fixes as the owner.
"""

import dataclasses
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import lease_world as lw
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agents.trust import classify_email
from app.api.deps import get_data_dir, get_gateway_engine
from app.auth.deps import api_engine, auth_settings
from app.auth.sessions import COOKIE_NAME, issue_token
from app.jobs import clock, reminders
from app.jobs.handlers import handler_for
from app.jobs.monthly import check_period
from app.jobs.worker import drain
from app.main import create_app
from app.records.seed import seed
from app.settings import get_settings
from app.work import resolver
from app.work.events import verify_chain
from app.work.roles import load_actor
from app.work.transitions import transition

ROOT = Path(__file__).resolve().parents[3]
ENTITY = "ENT-CA"
JAN = date(2026, 1, 1)
RM, CTRL, AP, AUD = "PER-RM-BAY", "PER-CTRL", "PER-AP", "PER-AUD"
HELD_TOTAL = Decimal("25736.36")
SECRET = "test-resolver-secret"

MON = date(2025, 12, 15)          # the day the demo question is asked


# ---------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("generated")
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    return out


@pytest.fixture
def january(clean, generated, monkeypatch):
    seed(Path(generated), clean["lease_agent"], clean["lease_gateway"])
    lw.use_documents(monkeypatch, generated)
    lw.draft_and_confirm(clean, generated)
    with clean["lease_agent"].begin() as conn:
        check_period(conn, ENTITY, JAN)
    return clean


def q(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def items(eng):
    with eng["lease_reader"].connect() as conn:
        return conn.execute(text("""
            SELECT w.id, w.state, w.proposal, w.subject_id, w.evidence, c.amount
              FROM work_item w JOIN landlord_charge c ON c.id = w.subject_id
             WHERE w.kind = 'CHARGE_CHECK' ORDER BY w.id
        """)).mappings().all()


def item_where(eng, **match):
    return next(i for i in items(eng) if all(i["evidence"].get(k) == v for k, v in match.items()))


def cam_hold(eng):
    """LEASE-01's operating expense estimate: billed $6,458.33, the lease's
    $11.50/RSF supports $5,941.67."""
    return item_where(eng, rule="operating_expense", lease_id="LEASE-01")


def set_today(eng, d):
    with eng["lease_agent"].begin() as conn:
        clock.set_today(conn, d)


def run_reminders(eng, d):
    with eng["lease_agent"].begin() as conn:
        return reminders.run(conn, d)


def pm_email(eng, lease_id, value, sent=date(2025, 3, 12)):
    """A March email from the landlord's property manager, who is not the
    representative the lease names, saying the CAM cap does not apply."""
    with eng["lease_reader"].connect() as conn:
        landlord = conn.execute(text("""
            SELECT d.* FROM landlord d JOIN lease l ON l.landlord_id = d.id WHERE l.id = :l
        """), {"l": lease_id}).mappings().one()
    ranked = classify_email(
        "eml_20250312", landlord["property_manager_email"],
        "Per our call, the controllable CAM cap is waived for 2026; please pay the full estimate.",
        authorized_rep_email=landlord["authorized_rep_email"],
        landlord_domain=landlord["authorized_rep_email"].split("@")[-1], sent=sent,
        claim="the CAM cap is waived for 2026", quote="the controllable CAM cap is waived for 2026")
    assert ranked.rank == 4 and not ranked.is_suspect
    return resolver.from_trust(ranked, value=value), landlord


def ask_demo(eng, item, *, today=MON, extraction=0.95, unpaid=True):
    """The demo beat's setup: the lease term read with citation score 0.95, AP
    has not paid yet, and the property manager's email arrives."""
    with eng["owner"].begin() as conn:
        if extraction is not None:
            conn.execute(text("""
                UPDATE lease_term SET confidence = :c
                 WHERE lease_version_id = :v AND field = 'cam_estimate_psf_annual'
            """), {"c": extraction, "v": item["evidence"]["lease_version_id"]})
        if unpaid:
            conn.execute(text("""
                DELETE FROM payment p USING landlord_charge c
                 WHERE c.id = :id AND p.lease_id = c.lease_id AND p.period = c.period
                   AND p.charge_type = c.charge_type AND p.invoice_id = c.invoice_id
            """), {"id": item["subject_id"]})
    email, landlord = pm_email(eng, item["evidence"]["lease_id"], float(item["amount"]))
    set_today(eng, today)
    with eng["lease_agent"].begin() as conn:
        row = resolver.resolve_item(conn, load_actor(conn, "agent:checker"), item["id"],
                                    extra_sources=[email])
    return row, landlord


def client_for(engines, generated) -> TestClient:
    settings = dataclasses.replace(get_settings(), session_secret=SECRET)
    app = create_app(settings)
    app.dependency_overrides[api_engine] = lambda: engines["lease_api"]
    app.dependency_overrides[get_gateway_engine] = lambda: engines["lease_gateway"]
    app.dependency_overrides[auth_settings] = lambda: settings
    app.dependency_overrides[get_data_dir] = lambda: Path(generated)
    return TestClient(app)


def as_(client, actor_id):
    client.cookies.set(COOKIE_NAME, issue_token(SECRET, actor_id))
    return client


# --------------------------------------------- January: same outcome, now explained

def test_january_keeps_12_items_5_holds_and_25736_36_with_sources_on_every_item(january):
    eng = january
    rows = items(eng)
    assert len(rows) == 12 and {r["state"] for r in rows} == {"PROPOSED"}
    held = [r for r in rows if r["proposal"] == "hold"]
    assert len(held) == 5
    assert sum((r["amount"] - Decimal(str(r["evidence"]["supported"])) for r in held),
               Decimal("0")) == HELD_TOTAL
    assert q(eng["lease_reader"], "SELECT count(*) FROM question") == 0     # nobody is asked

    for r in rows:
        ev = r["evidence"]
        kinds = [s["kind"] for s in ev["sources"]]
        assert kinds == ["lease", "invoice", "payment_history"], (r["id"], kinds)
        assert [s["rank"] for s in ev["sources"]] == [2, 5, 6]
        assert ev["sources"][0]["value"] == ev["supported"]
        assert ev["sources"][1]["value"] == ev["billed"]
        assert ev["sources"][0]["citation"]["lease_version_id"] == ev["lease_version_id"]
        assert 0 <= ev["confidence"] <= 1 and ev["confidence_reasons"][-1].startswith(
            "Confidence %.2f = " % ev["confidence"])
        assert ev["payment_due"] == "2026-01-01"
        if r["proposal"] == "hold":
            assert ev["decision"]["action"] == "hold"
            assert ev["decision"]["explanation"].startswith("Trusted the lease LEASE-0")
            assert " over invoice " in ev["decision"]["explanation"]
            assert ev["confidence"] == 0.56          # 0.9/1.4 x 0.875, e = q = 1
            assert (ev["route"]["role"], ev["asked_to"]) == ("regional_manager", RM)
        else:
            assert ev["decision"]["action"] == "proceed"
            assert ev["decision"]["explanation"].startswith("All 3 sources agree on $")
            assert ev["confidence"] == 1.0
            assert (ev["route"]["role"], ev["asked_to"]) == ("ap_clerk", AP)
        material = ev["route"]["amount_at_stake"] >= 10000
        assert ev["route"]["material"] is material
        assert ev["route"]["also_to"] == ([CTRL] if material else [])

    duplicate = item_where(eng, rule="duplicate")["evidence"]
    assert duplicate["route"]["amount_at_stake"] == 19626.65
    assert duplicate["route"]["also_to"] == [CTRL]
    assert "already billed on another invoice" in duplicate["sources"][0]["claim"]


def test_january_again_adds_nothing(january):
    eng = january
    before = (q(eng["lease_reader"], "SELECT count(*) FROM audit_event"),
              q(eng["lease_reader"], "SELECT count(*) FROM work_item"))
    with eng["lease_agent"].begin() as conn:
        assert check_period(conn, ENTITY, JAN)["created"] == 0
    assert (q(eng["lease_reader"], "SELECT count(*) FROM audit_event"),
            q(eng["lease_reader"], "SELECT count(*) FROM work_item")) == before


# ------------------------------------------------------------ the demo beat

def test_escalates_cam_cap_vs_an_unauthorized_email_confidence_0_38_routed_to_the_rm(january):
    eng = january
    item = cam_hold(eng)
    row, landlord = ask_demo(eng, item)
    assert row["state"] == "NEEDS_INFO"
    ev = row["evidence"]
    assert [s["rank"] for s in ev["sources"]] == [2, 5, 4]
    assert ev["decision"]["action"] == "ask"
    assert ev["decision"]["explanation"].startswith(
        "Did not pick a side: the email from %s (Mar 12, 2025) (email from property management "
        "without stated authority, rank 4) says $6,458.33, against the lease LEASE-01 §4.1"
        % landlord["property_manager_email"])
    assert "informational only" in ev["decision"]["explanation"]
    assert ev["confidence"] == 0.38
    assert ev["confidence_reasons"][-1] == (
        "Confidence 0.38 = 1 - (1 - 0.95 x 1.00 x 0.53 x 0.75) x (1 - 0.0).")
    assert (ev["route"]["role"], ev["route"]["asked_to"]) == ("regional_manager", RM)
    assert ev["route"]["amount_at_stake"] == 516.66
    with eng["lease_reader"].connect() as conn:
        question = conn.execute(text("SELECT * FROM question WHERE work_item_id = :i"),
                                {"i": item["id"]}).mappings().one()
        ask = conn.execute(text("""
            SELECT actor_id, evidence FROM audit_event
             WHERE subject_type = 'work_item' AND subject_id = :s AND action = 'ask'
        """), {"s": str(item["id"])}).mappings().one()
    assert question["asked_to"] == RM and question["asked_by"] == "agent:checker"
    assert question["due_at"] == datetime(2025, 12, 18, 17, tzinfo=timezone.utc)  # Mon + 3
    assert "Is there an agreement with the landlord" in question["body"]
    assert ask["evidence"]["asked_on"] == "2025-12-15"
    assert ask["evidence"]["due_on"] == "2025-12-18"


def test_reminded_on_business_days_then_escalated_then_the_undisputed_part_paid(january):
    eng = january
    item = cam_hold(eng)
    ask_demo(eng, item)
    qid = q(eng["lease_reader"], "SELECT id FROM question WHERE work_item_id = :i", i=item["id"])

    assert run_reminders(eng, date(2025, 12, 16))["reminded"] == 0     # T+1: too soon
    first = run_reminders(eng, date(2025, 12, 17))                      # T+2
    assert (first["open"], first["reminded"], first["escalated"]) == (1, 1, 0)
    assert run_reminders(eng, date(2025, 12, 17))["reminded"] == 0     # same day: no duplicate
    assert run_reminders(eng, date(2025, 12, 18))["reminded"] == 0     # T+3: next is T+4

    # T+4 (Friday) through the real worker, as lease_agent.
    with eng["lease_agent"].begin() as conn:
        reminders.schedule(conn, date(2025, 12, 19))
        assert reminders.schedule(conn, date(2025, 12, 19)) == reminders.schedule(
            conn, date(2025, 12, 19))                                   # one job per date
    [outcome] = drain(eng["lease_agent"], "test-reminders")
    assert (outcome.job.kind, outcome.status) == ("reminders", "done")
    assert outcome.result["reminded"] == 1 and outcome.result["escalated"] == 0

    # The weekend is not a business day: Sunday is still T+4, nothing new.
    weekend = run_reminders(eng, date(2025, 12, 21))
    assert (weekend["reminded"], weekend["escalated"], weekend["released"]) == (0, 0, 0)
    # T+5 (Monday): past the SLA, escalated to the controller, once.
    esc = run_reminders(eng, date(2025, 12, 22))
    assert (esc["escalated"], esc["reminded"]) == (1, 0)
    assert run_reminders(eng, date(2025, 12, 23))["escalated"] == 0
    assert run_reminders(eng, date(2025, 12, 26))["reminded"] == 0     # no reminders after

    with eng["lease_reader"].connect() as conn:
        history = reminders.history_of(conn, qid)
    assert [(e["action"], e["actor_id"]) for e in history] == [
        ("remind", "agent:resolver"), ("remind", "agent:resolver"), ("escalate", "agent:resolver")]
    assert [e["evidence"].get("n") for e in history[:2]] == [1, 2]
    assert history[0]["evidence"]["overdue"] is False and history[1]["evidence"]["overdue"] is True
    assert history[1]["reason"].startswith("Reminder 2 to %s: overdue since 2025-12-18" % RM)
    assert history[2]["evidence"]["escalated_to"] == CTRL
    assert history[2]["evidence"]["escalated_from"] == RM

    # The invoice falls due before anyone answers: the undisputed $5,941.67
    # goes to the AP clerk; the disputed $516.66 stays held on the item.
    paid = run_reminders(eng, JAN)
    assert paid["released"] == 1
    assert run_reminders(eng, JAN)["released"] == 0
    assert run_reminders(eng, date(2026, 1, 2))["released"] == 0
    with eng["lease_reader"].connect() as conn:
        release = conn.execute(text("SELECT * FROM work_item WHERE kind = 'PAYMENT_RELEASE'")
                               ).mappings().one()
        original = conn.execute(text("SELECT state FROM work_item WHERE id = :i"),
                                {"i": item["id"]}).scalar()
        due_events = [e for e in reminders.history_of(conn, qid) if e["action"] == "payment_due"]
    assert original == "NEEDS_INFO"
    assert (release["state"], release["proposal"], release["amount"]) == (
        "PROPOSED", "approve", Decimal("5941.67"))
    assert release["subject_id"] == item["subject_id"]
    assert release["evidence"]["disputed"] == 516.66
    assert release["evidence"]["charge_check_item_id"] == item["id"]
    assert len(due_events) == 1 and due_events[0]["evidence"]["release_item_id"] == release["id"]

    # The AP clerk releases exactly the undisputed portion.
    with eng["lease_api"].begin() as conn:
        approved = transition(conn, load_actor(conn, AP), release["id"], "approve")
    assert approved["state"] == "APPROVED"
    with eng["lease_reader"].connect() as conn:
        assert verify_chain(conn) is None


def test_payment_due_before_any_reminder_still_pays_only_the_undisputed_part(january):
    eng = january
    item = cam_hold(eng)
    ask_demo(eng, item, today=date(2025, 12, 31))
    got = run_reminders(eng, JAN)                                       # T+1: no reminder yet
    assert (got["reminded"], got["escalated"], got["released"]) == (0, 0, 1)
    assert q(eng["lease_reader"], "SELECT amount FROM work_item WHERE kind = 'PAYMENT_RELEASE'"
             ) == Decimal("5941.67")


def test_nothing_undisputed_means_nothing_proceeds_and_that_is_on_record(january):
    eng = january
    dup = item_where(eng, rule="duplicate")
    email, _ = pm_email(eng, dup["evidence"]["lease_id"], float(dup["amount"]))
    set_today(eng, date(2025, 12, 31))
    with eng["lease_agent"].begin() as conn:
        row = resolver.resolve_item(conn, load_actor(conn, "agent:checker"), dup["id"],
                                    extra_sources=[email])
    assert row["state"] == "NEEDS_INFO"
    assert row["evidence"]["route"]["also_to"] == [CTRL]       # $19,626.65 is material
    got = run_reminders(eng, JAN)
    assert (got["released"], got["nothing_undisputed"]) == (0, 1)
    assert run_reminders(eng, JAN)["nothing_undisputed"] == 0
    assert q(eng["lease_reader"], "SELECT count(*) FROM work_item WHERE kind = 'PAYMENT_RELEASE'"
             ) == 0
    assert q(eng["lease_reader"], "SELECT count(*) FROM audit_event WHERE action = 'payment_due'"
             ) == 1


def test_a_question_asked_without_the_resolver_back_computes_when_it_was_asked(january):
    eng = january
    item = cam_hold(eng)
    with eng["lease_agent"].begin() as conn:
        transition(conn, load_actor(conn, "agent:checker"), item["id"], "ask", patch={
            "asked_to": RM, "body": "Is the cap waived?",
            "due_at": resolver.due_at(date(2025, 12, 18))})
        [question] = reminders.open_questions(conn)
        assert reminders.asked_on_of(conn, question) == MON
    assert run_reminders(eng, date(2025, 12, 17))["reminded"] == 1


def test_a_question_without_a_due_date_has_no_sla(january):
    eng = january
    with eng["lease_agent"].begin() as conn:
        transition(conn, load_actor(conn, "agent:checker"), cam_hold(eng)["id"], "ask",
                   patch={"asked_to": RM, "body": "Is the cap waived?"})
    assert run_reminders(eng, date(2026, 3, 1))["open"] == 0


def test_the_worker_knows_the_reminders_kind():
    assert handler_for("reminders") is reminders.handler


def test_the_controller_is_not_escalated_to_itself(january):
    eng = january
    item = cam_hold(eng)
    with eng["lease_agent"].begin() as conn:
        transition(conn, load_actor(conn, "agent:checker"), item["id"], "ask", patch={
            "asked_to": CTRL, "body": "Accrue the difference?",
            "due_at": resolver.due_at(date(2025, 12, 18))})
    got = run_reminders(eng, date(2025, 12, 29))
    assert (got["escalated"], got["reminded"]) == (0, 1)


# --------------------------------------------------------------------- API

def test_sources_endpoint_shows_the_trust_explanation_confidence_and_route(january, generated):
    eng = january
    client = client_for(eng, generated)
    hold = cam_hold(eng)
    body = as_(client, RM).get("/api/items/%d/sources" % hold["id"]).json()
    assert body["item_id"] == hold["id"] and body["computed"] is False
    assert [s["kind"] for s in body["sources"]] == ["lease", "invoice", "payment_history"]
    assert body["sources"][0]["citation"]["section"] == "4.1"
    assert body["decision"]["action"] == "hold"
    assert body["explanation"].startswith(
        "Trusted the lease LEASE-01 §4.1 over invoice SERRA-202601-0001 because an invoice "
        "reports what the landlord billed")
    assert body["confidence"] == 0.56 and len(body["confidence_reasons"]) == 6
    assert body["route"]["role"] == "regional_manager" and body["asked_to"] == RM
    assert body["question"] is None and body["payment_due"] == "2026-01-01"

    # Out of scope is a 404, as on the queue.
    with eng["owner"].begin() as conn:
        conn.execute(text("INSERT INTO region (id, name) VALUES ('REG-DESERT', 'Desert')"))
        conn.execute(text("INSERT INTO actor (id, name, role, region_id, active) "
                          "VALUES ('PER-RM-DESERT', 'Desert', 'regional_manager', 'REG-DESERT', "
                          "true)"))
    assert as_(client, "PER-RM-DESERT").get(
        "/api/items/%d/sources" % hold["id"]).status_code == 404
    assert as_(client, RM).get("/api/items/999999/sources").status_code == 404
    client.cookies.clear()
    assert client.get("/api/items/%d/sources" % hold["id"]).status_code == 401

    # An item proposed before the resolver existed is resolved on the fly, read-only.
    with eng["owner"].begin() as conn:
        conn.execute(text("""
            UPDATE work_item SET evidence = evidence - 'sources' - 'decision' - 'confidence'
                                            - 'confidence_reasons' - 'route' - 'asked_to'
             WHERE id = :i
        """), {"i": hold["id"]})
    events = q(eng["lease_reader"], "SELECT count(*) FROM audit_event")
    body = as_(client, AUD).get("/api/items/%d/sources" % hold["id"]).json()
    assert body["computed"] is True and len(body["sources"]) == 3 and body["confidence"] == 0.56
    assert q(eng["lease_reader"], "SELECT count(*) FROM audit_event") == events

    # A lease abstraction has no sources to rank.
    abstraction = q(eng["lease_reader"],
                    "SELECT min(id) FROM work_item WHERE kind = 'LEASE_ABSTRACTION'")
    body = as_(client, RM).get("/api/items/%d/sources" % abstraction).json()
    assert body["sources"] == [] and body["decision"] is None and body["computed"] is False


def test_questions_mine_lists_due_dates_and_dollars_then_follows_the_escalation(january,
                                                                              generated):
    eng = january
    client = client_for(eng, generated)
    item = cam_hold(eng)
    ask_demo(eng, item)

    mine = as_(client, RM).get("/api/questions?mine=1").json()
    assert mine["business_date"] == "2025-12-15" and mine["total"] == 1
    [question] = mine["questions"]
    assert question["work_item_id"] == item["id"] and question["why"] == "asked"
    assert question["due_on"] == "2025-12-18" and question["overdue"] is False
    assert question["amount_at_stake"] == 516.66 and question["confidence"] == 0.38
    assert question["reminders"] == 0 and question["escalated_to"] is None
    assert as_(client, CTRL).get("/api/questions?mine=1").json()["total"] == 0
    assert as_(client, CTRL).get("/api/questions").json()["total"] == 1   # in scope, not mine

    run_reminders(eng, date(2025, 12, 17))
    run_reminders(eng, date(2025, 12, 19))
    run_reminders(eng, date(2025, 12, 22))
    set_today(eng, date(2025, 12, 22))
    got = as_(client, CTRL).get("/api/questions?mine=1").json()
    assert got["total"] == 1
    [question] = got["questions"]
    assert (question["why"], question["escalated_to"], question["reminders"]) == (
        "escalated", CTRL, 2)
    assert question["overdue"] is True

    detail = as_(client, RM).get("/api/items/%d/sources" % item["id"]).json()
    assert detail["question"]["escalated_to"] == CTRL and detail["question"]["reminders"] == 2
    assert detail["confidence"] == 0.38

    # The controller answers (it may answer any item); the question leaves every list.
    with eng["lease_api"].begin() as conn:
        transition(conn, load_actor(conn, CTRL), item["id"], "answer",
                   patch={"answer": "No agreement; the cap stands."})
    assert as_(client, CTRL).get("/api/questions?mine=1").json()["total"] == 0
    assert run_reminders(eng, date(2025, 12, 23))["open"] == 0


def test_material_items_copy_the_controller_on_the_question(january, generated):
    eng = january
    client = client_for(eng, generated)
    dup = item_where(eng, rule="duplicate")
    email, _ = pm_email(eng, dup["evidence"]["lease_id"], float(dup["amount"]))
    set_today(eng, MON)
    with eng["lease_agent"].begin() as conn:
        resolver.resolve_item(conn, load_actor(conn, "agent:checker"), dup["id"],
                              extra_sources=[email])
    [question] = as_(client, CTRL).get("/api/questions?mine=1").json()["questions"]
    assert question["why"] == "material" and question["amount_at_stake"] == 19626.65
