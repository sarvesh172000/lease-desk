"""The policy engine on the seeded dev company (PHASE_2.md group 10, B6).

Onboarding from 2025, policies as work (proposed by agent:policy, approved
or rejected by a controller through transition()), the database refusing any
other way to switch a rule on, rejection memory, backtests, and the demo arc:

    a manager answers -> a policy is proposed -> its backtest shows January's
    change -> the controller approves -> the re-run cites the policy

Every step runs as the role its process uses: the worker as lease_agent,
people through lease_api (and the HTTP API), the auditor's reads as
lease_reader, replay as the owner.
"""

import dataclasses
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import lease_world as lw
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InternalError, ProgrammingError

from app.api.deps import get_gateway_engine
from app.auth.deps import api_engine, auth_settings
from app.auth.sessions import COOKIE_NAME, issue_token
from app.jobs.monthly import check_period, run_month
from app.jobs.worker import drain
from app.main import create_app
from app.records.seed import seed
from app.settings import get_settings
from app.work.backtest import backtest
from app.work.events import verify_chain
from app.work.policies import PolicyFormatError, load_policies
from app.work.policy_learner import learn_from_answer, onboard, propose
from app.work.replay import replay
from app.work.roles import load_actor
from app.work.transitions import Denied, transition

ROOT = Path(__file__).resolve().parents[3]
JAN = date(2026, 1, 1)
FEB = date(2026, 2, 1)
ENTITY = "ENT-CA"
RM = "PER-RM-BAY"
CTRL = "PER-CTRL"
SECRET = "test-policy-secret"


# --- the world ----------------------------------------------------------------------

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
    lw.draft_and_confirm(seeded, generated)
    return seeded


@pytest.fixture
def january(confirmed):
    with confirmed["lease_agent"].begin() as conn:
        counts = check_period(conn, ENTITY, JAN)
    assert (counts["created"], counts["holds"]) == (12, 5)
    return confirmed


def q(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def rows(eng, sql, **params):
    with eng.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def as_agent(eng, fn, *args, **kwargs):
    with eng["lease_agent"].begin() as conn:
        return fn(conn, *args, **kwargs)


def act(eng, actor_id, item_id, action, role="lease_api", **kwargs):
    with eng[role].begin() as conn:
        return transition(conn, load_actor(conn, actor_id), item_id, action, **kwargs)


def policy_item(eng, policy_id):
    return rows(eng["lease_reader"], """
        SELECT * FROM work_item WHERE kind = 'POLICY' AND subject_id = :s
    """, s=str(policy_id))[0]


def charge_item(eng, lease_id, charge_type, proposal=None):
    found = [r for r in rows(eng["lease_reader"], """
        SELECT * FROM work_item WHERE kind = 'CHARGE_CHECK' ORDER BY id""")
        if r["evidence"]["lease_id"] == lease_id and r["evidence"]["charge_type"] == charge_type
        and (proposal is None or r["evidence"].get("checker_proposal", r["proposal"]) == proposal)]
    return found[0]


def make_client(engines) -> TestClient:
    settings = dataclasses.replace(get_settings(), session_secret=SECRET)
    app = create_app(settings)
    app.dependency_overrides[api_engine] = lambda: engines["lease_api"]
    app.dependency_overrides[get_gateway_engine] = lambda: engines["lease_gateway"]
    app.dependency_overrides[auth_settings] = lambda: settings
    return TestClient(app)


def as_(client, actor_id):
    client.cookies.set(COOKIE_NAME, issue_token(SECRET, actor_id))
    return client


def manual_rule(**over):
    base = {
        "name": "manual:LEASE-01:cam_estimate:dispute",
        "description": "Dispute LEASE-01's estimate above the lease.",
        "scope": {"lease_id": "LEASE-01"},
        "when": {"charge_types": ["cam_estimate"], "min_variance": "0.01"},
        "then": {"action": "dispute"},
        "evidence_ids": ["note:controller-memo-1"],
    }
    base.update(over)
    return base


# --- onboarding ---------------------------------------------------------------------

def test_onboarding_proposes_the_2025_habits_with_precedents(confirmed):
    eng = confirmed
    out = as_agent(eng, onboard, ENTITY)
    assert out["scanned"] == 120
    by_name = {p["name"]: p for p in out["proposed"]}
    assert sorted(by_name) == [
        "onboarding:LL-PACIFIC:base_rent:unchanged",
        "onboarding:LL-PACIFIC:cam_estimate:unchanged",
        "onboarding:LL-SERRA:base_rent:unchanged",
        "onboarding:LL-SERRA:cam_estimate:unchanged",
    ]
    counts = {n: p["precedents"] for n, p in by_name.items()}
    assert counts == {
        "onboarding:LL-PACIFIC:base_rent:unchanged": 31,
        "onboarding:LL-PACIFIC:cam_estimate:unchanged": 31,
        "onboarding:LL-SERRA:base_rent:unchanged": 21,
        "onboarding:LL-SERRA:cam_estimate:unchanged": 22,
    }
    # The two mistakes paid anyway (H1, H2) are found, and neither is covered.
    assert sorted((m["lease_id"], m["period"], m["amount"]) for m in out["paid_anyway"]) == [
        ("LEASE-02", "2025-06-01", 9700.0), ("LEASE-03", "2025-04-01", 4612.5)]
    # The changed-amount habit has too few precedents, and says so.
    skipped = {s["name"]: s["reason"] for s in out["skipped"]}
    assert "needed" in skipped["onboarding:ENT-CA:base_rent:changed-matches-lease"]

    reader = eng["lease_reader"]
    pol = rows(reader, "SELECT * FROM policy ORDER BY id")
    assert {p["status"] for p in pol} == {"proposed"} and len(pol) == 4
    serra = next(p for p in pol if p["name"] == "onboarding:LL-SERRA:base_rent:unchanged")
    assert serra["rule"]["scope"] == {"entity_id": ENTITY, "landlord_id": "LL-SERRA",
                                      "lease_id": None, "clinic_id": None}
    assert serra["rule"]["when"]["same_as_prior_paid"] is True
    assert serra["effective_from"] == JAN
    item = policy_item(eng, serra["id"])
    assert (item["state"], item["proposal"], item["proposed_by"]) == (
        "PROPOSED", "approve", "agent:policy")
    ev = item["evidence"]
    assert ev["precedents"]["count"] == 21 and ev["precedents"]["leases"] == ["LEASE-01", "LEASE-02"]
    linked = {d["charge_id"] for d in ev["precedents"]["decisions"]}
    assert {"landlord_charge:%s" % c for c in linked} <= set(serra["rule"]["evidence_ids"])
    assert all(d["payment_ids"] for d in ev["precedents"]["decisions"])
    assert ev["paid_anyway"][0]["period"] == "2025-06-01"          # H2, not covered
    # Its backtest ran before anyone could approve it, and changes nothing:
    # every unchanged Serramonte rent was paid, and January's matching charge
    # is one the checker approved too.
    assert ev["backtest"]["matched"] >= 21 and ev["backtest"]["changed"] == 0


def test_onboarding_without_confirmed_leases_says_what_it_cannot_tell(seeded):
    out = as_agent(seeded, onboard, ENTITY)
    assert len(out["proposed"]) == 4 and out["paid_anyway"] == []
    assert any("no confirmed leases" in s["reason"] for s in out["skipped"])


def test_onboarding_an_empty_year_proposes_nothing(confirmed):
    out = as_agent(confirmed, onboard, ENTITY, year=2019)
    assert out["proposed"] == [] and "no 2019 charges" in out["skipped"][0]["reason"]


def test_onboarding_twice_proposes_nothing_new(confirmed):
    as_agent(confirmed, onboard, ENTITY)
    again = as_agent(confirmed, onboard, ENTITY)
    assert again["proposed"] == []
    assert all("already proposed" in s["reason"] for s in again["skipped"] if s["name"]
               and s["name"].endswith(":unchanged"))
    assert q(confirmed["lease_reader"], "SELECT count(*) FROM policy") == 4


# --- policies are work --------------------------------------------------------------

def test_only_a_controller_switches_a_policy_on(confirmed):
    eng = confirmed
    out = as_agent(eng, onboard, ENTITY)
    pid = out["proposed"][0]["policy_id"]
    item_id = out["proposed"][0]["item_id"]
    with pytest.raises(Denied, match="role agent may not approve"):
        act(eng, "agent:policy", item_id, "approve", role="lease_agent")
    with pytest.raises(Denied, match="region"):                 # policies have no region
        act(eng, RM, item_id, "approve")
    assert q(eng["lease_reader"], "SELECT status FROM policy WHERE id = :i", i=pid) == "proposed"
    assert act(eng, CTRL, item_id, "approve")["state"] == "APPROVED"
    assert q(eng["lease_reader"], "SELECT status FROM policy WHERE id = :i", i=pid) == "approved"
    # Pulled back by a hold, it is off again.
    act(eng, CTRL, item_id, "hold", reason="second look")
    assert q(eng["lease_reader"], "SELECT status FROM policy WHERE id = :i", i=pid) == "proposed"


def test_nobody_approves_a_policy_they_proposed(confirmed):
    """Separation of duties, through the same can() as every item."""
    eng = confirmed
    out = as_agent(eng, onboard, ENTITY)
    item_id = out["proposed"][0]["item_id"]
    with eng["owner"].begin() as conn:      # a controller who proposed (revised) it
        conn.execute(text("UPDATE actor SET role = 'agent' WHERE id = :c"), {"c": CTRL})
    act(eng, CTRL, item_id, "propose", role="lease_agent", reason="revised")
    with eng["owner"].begin() as conn:
        conn.execute(text("UPDATE actor SET role = 'controller' WHERE id = :c"), {"c": CTRL})
    with pytest.raises(Denied, match="separation of duties"):
        act(eng, CTRL, item_id, "approve")


def test_the_database_refuses_every_other_way_to_switch_a_policy_on(confirmed):
    eng = confirmed
    # Born proposed, whatever the INSERT says.
    with eng["lease_agent"].begin() as conn:
        pid = conn.execute(text("""
            INSERT INTO policy (name, version, status, rule) VALUES ('sneaky', 1, 'approved',
                '{"name": "sneaky"}') RETURNING id""")).scalar_one()
    assert q(eng["lease_reader"], "SELECT status FROM policy WHERE id = :i", i=pid) == "proposed"
    # No role may UPDATE a policy.
    for role in ("lease_agent", "lease_api", "lease_gateway"):
        with pytest.raises(ProgrammingError, match="permission denied"):
            with eng[role].begin() as conn:
                conn.execute(text("UPDATE policy SET status = 'approved' WHERE id = :i"), {"i": pid})
    # A raw state change on its item, without a controller's approve event, is refused.
    out = as_agent(eng, onboard, ENTITY)
    item_id = out["proposed"][0]["item_id"]
    with pytest.raises((InternalError, DBAPIError), match="only be approved by a controller"):
        with eng["lease_agent"].begin() as conn:
            conn.execute(text("UPDATE work_item SET state = 'APPROVED' WHERE id = :i"),
                         {"i": item_id})
    with eng["lease_reader"].connect() as conn:
        assert load_policies(conn) == []


def test_propose_refuses_a_malformed_rule_and_writes_nothing(confirmed):
    with pytest.raises(PolicyFormatError, match="scope must name"):
        as_agent(confirmed, propose, manual_rule(scope={}))
    assert q(confirmed["lease_reader"], "SELECT count(*) FROM policy") == 0


# --- rejection memory ---------------------------------------------------------------

def test_a_rejected_policy_is_not_proposed_again_without_new_evidence(confirmed):
    eng = confirmed
    out = as_agent(eng, onboard, ENTITY)
    first = next(p for p in out["proposed"] if p["name"].startswith("onboarding:LL-SERRA:cam"))
    act(eng, CTRL, first["item_id"], "reject",
        reason="Serramonte re-bills estimates mid-year; I want each one reviewed.")
    pol = rows(eng["lease_reader"], "SELECT status FROM policy WHERE id = :i", i=first["policy_id"])
    assert pol[0]["status"] == "rejected"
    assert policy_item(eng, first["policy_id"])["reason"].startswith("Serramonte re-bills")

    again = as_agent(eng, onboard, ENTITY)
    skipped = {s["name"]: s for s in again["skipped"] if s["name"]}
    memory = skipped[first["name"]]
    assert "rejected as policy %d v1 by %s" % (first["policy_id"], CTRL) in memory["reason"]
    assert "Serramonte re-bills estimates mid-year" in memory["reason"]
    assert "no new evidence" in memory["reason"]
    assert q(eng["lease_reader"], "SELECT count(*) FROM policy WHERE name = :n",
             n=first["name"]) == 1

    # New evidence: a precedent no rejected version had. Then it may come back,
    # as version 2, carrying the rejection it follows.
    rule = dict(manual_rule(name=first["name"], evidence_ids=["note:landlord-letter-2026"]))
    result = as_agent(eng, propose, rule, entity_id=ENTITY)
    assert result["proposed"]["version"] == 2
    item = policy_item(eng, result["proposed"]["policy_id"])
    assert item["evidence"]["after_rejection"][0]["reason"].startswith("Serramonte re-bills")


def test_a_rejected_answer_policy_needs_a_new_answer(january):
    eng = january
    item = charge_item(eng, "LEASE-01", "cam_estimate", "hold")
    act(eng, "agent:checker", item["id"], "ask", role="lease_agent",
        patch={"asked_to": RM, "body": "Is the 2026 Serramonte estimate right?"})
    act(eng, RM, item["id"], "answer", patch={"answer": "Yes, it is correct. Pay it."})
    qid = q(eng["lease_reader"], "SELECT max(id) FROM question")
    first = as_agent(eng, learn_from_answer, qid)["proposed"]
    act(eng, CTRL, first["item_id"], "reject", reason="One answer is not enough.")
    again = as_agent(eng, learn_from_answer, qid)
    assert "no new evidence" in again["skipped"]["reason"]
    # A second question and answer is new evidence.
    act(eng, "agent:checker", item["id"], "ask", role="lease_agent",
        patch={"asked_to": RM, "body": "Did Serramonte confirm it in writing?"})
    act(eng, RM, item["id"], "answer", patch={"answer": "Yes, confirmed in writing. Pay it."})
    qid2 = q(eng["lease_reader"], "SELECT max(id) FROM question")
    assert as_agent(eng, learn_from_answer, qid2)["proposed"]["version"] == 2


# --- January is untouched until a policy is approved -------------------------------

def test_proposed_policies_change_nothing_about_january(confirmed):
    eng = confirmed
    as_agent(eng, onboard, ENTITY)
    with eng["lease_agent"].begin() as conn:
        counts = check_period(conn, ENTITY, JAN)
        ids = run_month(conn, ENTITY, JAN)
    assert (counts["created"], counts["holds"], counts["cited"]) == (12, 5, 0)
    assert "policies" not in ids
    assert q(eng["lease_reader"], "SELECT count(*) FROM audit_event WHERE policy_ref IS NOT NULL") == 0


def test_approved_onboarding_policies_are_cited_and_change_no_outcome(confirmed):
    eng = confirmed
    out = as_agent(eng, onboard, ENTITY)
    for p in out["proposed"]:
        act(eng, CTRL, p["item_id"], "approve")
    with eng["lease_agent"].begin() as conn:
        counts = check_period(conn, ENTITY, JAN)
    assert (counts["created"], counts["holds"]) == (12, 5)
    cited = rows(eng["lease_reader"], """
        SELECT w.evidence, w.proposal, e.policy_ref FROM audit_event e
          JOIN work_item w ON w.id::text = e.subject_id
         WHERE e.policy_ref IS NOT NULL AND e.action = 'propose'""")
    # The five charges billed at December's paid amount: LEASE-02 rent and the
    # LEASE-02..05 estimates, all ones the checker approves anyway.
    assert sorted((c["evidence"]["lease_id"], c["evidence"]["charge_type"]) for c in cited) == [
        ("LEASE-02", "base_rent"), ("LEASE-02", "cam_estimate"), ("LEASE-03", "cam_estimate"),
        ("LEASE-04", "cam_estimate"), ("LEASE-05", "cam_estimate")]
    assert {c["proposal"] for c in cited} == {"approve"}
    assert all(c["evidence"]["policy"]["ref"] == c["policy_ref"] for c in cited)


def test_an_approved_policy_is_cited_on_a_later_months_decision(confirmed):
    eng = confirmed
    out = as_agent(eng, onboard, ENTITY)
    pacific_cam = next(p for p in out["proposed"]
                       if p["name"] == "onboarding:LL-PACIFIC:cam_estimate:unchanged")
    act(eng, CTRL, pacific_cam["item_id"], "approve")
    # February: LEASE-04's estimate, billed at January's paid amount.
    with eng["owner"].begin() as conn:
        conn.execute(text("""
            INSERT INTO raw_row (id, source, source_id, payload)
            VALUES ('raw-feb-1', 'ap_export', 'PACIF-202602-0005-L2', '{}');
            INSERT INTO period (entity_id, period) VALUES ('ENT-CA', '2026-02-01')
                ON CONFLICT DO NOTHING;
            INSERT INTO landlord_charge (id, lease_id, clinic_id, invoice_id, suite, period,
                                         charge_type, description, amount, raw_ref)
            VALUES ('chg-feb-1', 'LEASE-04', 'CLINIC-04', 'PACIF-202602-0005', 'Suite 240',
                    '2026-02-01', 'cam_estimate', 'Operating Expense Estimate', 3371.88,
                    'raw-feb-1');
        """))
    with eng["lease_agent"].begin() as conn:
        counts = check_period(conn, ENTITY, FEB)
    assert (counts["created"], counts["cited"]) == (1, 1)
    event = rows(eng["lease_reader"], """
        SELECT e.policy_ref, e.actor_id FROM audit_event e JOIN work_item w ON w.id::text = e.subject_id
         WHERE w.subject_id = 'chg-feb-1' AND e.action = 'propose'""")[0]
    assert event == {"policy_ref": "policy:%d@v1" % pacific_cam["policy_id"],
                     "actor_id": "agent:checker"}


# --- backtest -----------------------------------------------------------------------

def test_backtest_reports_changes_dollars_and_conflicts(january):
    eng = january
    out = as_agent(eng, onboard, ENTITY)
    serra_cam = next(p for p in out["proposed"]
                     if p["name"] == "onboarding:LL-SERRA:cam_estimate:unchanged")
    act(eng, CTRL, serra_cam["item_id"], "approve")
    # Dispute LEASE-01's estimate whenever it is billed above the lease.
    with eng["lease_reader"].connect() as conn:
        result = backtest(conn, manual_rule())
    # 2025: never above the lease, so nothing; January 2026: the checker's hold
    # becomes a dispute (no dollars move: a hold already withholds them).
    assert result["matched"] == 1 and result["changed"] == 1
    change = result["changes"][0]
    assert (change["period"], change["current"], change["policy"], change["dollars"]) == (
        "2026-01-01", "hold", "dispute", 0.0)
    assert result["conflicts"] == []
    # A rule that pays it instead releases the disputed $516.66, and one that
    # holds every unchanged estimate collides with the approved onboarding policy.
    with eng["lease_reader"].connect() as conn:
        pay = backtest(conn, manual_rule(name="manual:pay", when={
            "charge_types": ["cam_estimate"], "max_amount": "6458.33"}, then={"action": "approve"}))
        hold = backtest(conn, manual_rule(name="manual:hold", when={
            "charge_types": ["cam_estimate"], "same_as_prior_paid": True},
            then={"action": "hold"}))
    jan = [c for c in pay["changes"] if c["period"] == "2026-01-01"]
    assert [(c["current"], c["policy"], c["dollars"]) for c in jan] == [
        ("hold", "approve", 516.66)]
    assert pay["released"] == 516.66 and pay["withheld"] == 0
    # (A hold withholds only what the lease does not support: on charges that
    # matched the lease, eleven decisions change and no dollar does.)
    assert hold["changed"] == 11 and hold["withheld"] == 0
    assert [(c["policy_id"], c["charges"], c["winner"]) for c in hold["conflicts"]] == [
        (serra_cam["policy_id"], 11, "this")]


def test_backtest_without_confirmed_leases_reports_unknown_not_matches(seeded):
    with seeded["lease_reader"].connect() as conn:
        result = backtest(conn, manual_rule())
    # LEASE-01's twelve 2025 estimates and January's: no lease says what is supported.
    assert result["matched"] == 0 and result["unknown"] == 13 and result["changed"] == 0


# --- the demo arc: answers -> policy -> backtest -> approve -> re-run cites it -------

def test_the_improves_beat_end_to_end_over_http(january):
    eng = january
    client = make_client(eng)
    reader = eng["lease_reader"]

    # The checker held LEASE-01's 2026 estimate ($6,458.33 against $5,941.67)
    # and asks the Bay Area manager.
    item = charge_item(eng, "LEASE-01", "cam_estimate", "hold")
    assert item["proposal"] == "hold"
    act(eng, "agent:checker", item["id"], "ask", role="lease_agent",
        patch={"asked_to": RM, "body": "Serramonte billed $6,458.33; the lease says $5,941.67. "
               "Is the new estimate agreed?"})

    # 1. The manager answers in the browser. The answer queues the learner.
    r = as_(client, RM).post("/api/items/%d/actions/answer" % item["id"], json={
        "patch": {"answer": "Confirmed with Serramonte: the 2026 estimate is correct, pay it."}})
    assert r.status_code == 200, r.text
    assert q(reader, "SELECT count(*) FROM job WHERE kind = 'policy_learn'") == 1

    # 2. The worker proposes the policy, as agent:policy, with its backtest.
    outcomes = drain(eng["lease_agent"], "policy-test")
    assert [(o.job.kind, o.status) for o in outcomes] == [("policy_learn", "done")]
    pol = rows(reader, "SELECT * FROM policy")[0]
    assert pol["name"] == "answer:LEASE-01:cam_estimate:approve" and pol["status"] == "proposed"
    assert pol["rule"]["scope"]["lease_id"] == "LEASE-01"
    assert pol["rule"]["when"] == {
        "charge_types": ["cam_estimate"], "checker_rules": ["operating_expense"],
        "max_amount": "6458.33", "min_amount": None, "min_variance": None,
        "max_variance": None, "same_as_prior_paid": None, "matches_lease": None,
        "description_contains": None}
    qid = q(reader, "SELECT max(id) FROM question")
    assert {"question:%d" % qid, "work_item:%d" % item["id"],
            "landlord_charge:%s" % item["subject_id"]} <= set(pol["rule"]["evidence_ids"])
    assert any(e.startswith("document:") for e in pol["rule"]["evidence_ids"])

    listing = as_(client, CTRL).get("/api/policies").json()
    assert listing["counts"]["proposed"] == 1
    row = listing["policies"][0]
    assert (row["id"], row["status"], row["version"], row["precedent_count"]) == (
        pol["id"], "proposed", 1, 1)
    detail = client.get("/api/policies/%d" % pol["id"]).json()
    assert detail["evidence"]["question"]["answer"].startswith("Confirmed with Serramonte")
    assert detail["evidence"]["question"]["answered_by"] == RM

    # 3. The backtest the controller sees: January's hold becomes a payment of
    #    the $516.66 the checker withheld; nothing in 2025 changes.
    bt = detail["backtest"]
    assert bt["changed"] == 1 and bt["released"] == 516.66 and bt["conflicts"] == []
    assert bt["changes"][0]["decided_by"] == "work_item:%d" % item["id"]
    live = client.post("/api/policies/%d/backtest" % pol["id"]).json()
    assert live["backtest"]["digest"] == bt["digest"] and live["refresh_job_id"] is None

    # 4. The manager may not approve the policy (or the item they answered);
    #    the controller approves the policy through the items endpoint.
    policy_item_id = row["work_item_id"]
    assert as_(client, RM).post("/api/items/%d/actions/approve" % policy_item_id).status_code == 403
    r = as_(client, CTRL).post("/api/items/%d/actions/approve" % policy_item_id,
                               json={"reason": "Serramonte's 2026 budget letter is on file."})
    assert r.status_code == 200 and r.json()["state"] == "APPROVED"
    assert q(reader, "SELECT status FROM policy WHERE id = :i", i=pol["id"]) == "approved"

    # 5. The re-run: run_month sees a new approved set and re-decides the
    #    month's open items. The answered hold is now an approve citing the policy.
    with eng["lease_agent"].begin() as conn:
        ids = run_month(conn, ENTITY, JAN)
    assert "policies" in ids
    outcomes = drain(eng["lease_agent"], "policy-test")
    done = {o.job.kind: o for o in outcomes}
    assert done["policies"].status == "done" and done["policies"].result["cited"] == 1
    ref = "policy:%d@v1" % pol["id"]
    after = rows(reader, "SELECT * FROM work_item WHERE id = :i", i=item["id"])[0]
    assert (after["state"], after["proposal"]) == ("PROPOSED", "approve")
    assert after["evidence"]["policy"]["ref"] == ref
    assert after["evidence"]["checker_proposal"] == "hold"
    assert after["reason"].startswith("Policy answer:LEASE-01:cam_estimate:approve v1 (%s)" % ref)
    event = rows(reader, """
        SELECT actor_id, action, policy_ref FROM audit_event
         WHERE subject_type = 'work_item' AND subject_id = :s ORDER BY seq DESC LIMIT 1
    """, s=str(item["id"]))[0]
    assert event == {"actor_id": "agent:checker", "action": "propose", "policy_ref": ref}
    cited = client.get("/api/policies/%d" % pol["id"]).json()["cited_by"]
    assert [(c["subject_id"], c["action"]) for c in cited] == [(str(item["id"]), "propose")]

    # Running the month again re-decides nothing.
    with eng["lease_agent"].begin() as conn:
        run_month(conn, ENTITY, JAN)
    assert drain(eng["lease_agent"], "policy-test") == []

    # 6. The controller approves the charge; it posts the billed amount.
    r = as_(client, CTRL).post("/api/items/%d/actions/approve" % item["id"])
    assert r.status_code == 200 and r.json()["posting"]["amount"] == 6458.33

    # The chain verifies and replay rebuilds the same work and policy statuses.
    with reader.connect() as conn:
        assert verify_chain(conn) is None
    statuses = rows(reader, "SELECT id, status FROM policy ORDER BY id")
    with eng["owner"].connect() as conn:
        with conn.begin() as tx:
            report = replay(conn)
            rebuilt = [dict(r) for r in conn.execute(text(
                "SELECT id, status FROM policy ORDER BY id")).mappings()]
            tx.rollback()
    assert report.identical, report.differences[:5]
    assert rebuilt == statuses


# --- the API ------------------------------------------------------------------------

def test_policies_api_needs_a_session_and_onboarding_needs_a_controller(confirmed):
    client = make_client(confirmed)
    assert client.get("/api/policies").status_code == 401
    assert client.post("/api/policies/1/backtest").status_code == 401
    assert as_(client, RM).post("/api/policies/onboard", json={"entity_id": ENTITY}).status_code == 403
    assert as_(client, CTRL).get("/api/policies/999").status_code == 404
    r = client.post("/api/policies/onboard", json={"entity_id": ENTITY})
    assert r.status_code == 200
    assert client.post("/api/policies/onboard", json={"entity_id": "ENT-XX"}).status_code == 404
    outcomes = drain(confirmed["lease_agent"], "policy-test")
    assert [(o.job.kind, o.status) for o in outcomes] == [("policy_onboard", "done")]
    listing = client.get("/api/policies").json()
    assert listing["counts"]["proposed"] == 4
    assert sorted(p["precedent_count"] for p in listing["policies"]) == [21, 22, 31, 31]
    # A backtest re-run that differs from the stored one is queued onto the item.
    first = listing["policies"][0]
    run = client.post("/api/policies/%d/backtest" % first["id"]).json()
    assert run["backtest"]["policy"]["id"] == first["id"] and run["status"] == "proposed"


def test_a_backtest_refresh_puts_the_new_result_on_the_item(january):
    eng = january
    out = as_agent(eng, onboard, ENTITY)
    serra_cam = next(p for p in out["proposed"]
                     if p["name"] == "onboarding:LL-SERRA:cam_estimate:unchanged")
    from app.work.policy_learner import refresh_backtest
    same = as_agent(eng, refresh_backtest, serra_cam["policy_id"])
    assert same["stored"] is False                 # nothing changed since it was proposed
    # Approve a conflicting policy; the stored backtest is now stale.
    other = as_agent(eng, propose, manual_rule(name="manual:hold-serra", scope={
        "landlord_id": "LL-SERRA"}, when={"charge_types": ["cam_estimate"],
                                         "same_as_prior_paid": True}, then={"action": "hold"}))
    act(eng, CTRL, other["proposed"]["item_id"], "approve")
    fresh = as_agent(eng, refresh_backtest, serra_cam["policy_id"])
    assert fresh["stored"] is True
    stored = policy_item(eng, serra_cam["policy_id"])["evidence"]["backtest"]
    assert stored["conflicts"][0]["policy_id"] == other["proposed"]["policy_id"]


def test_amounts_are_exact(january):
    """Money in evidence is rounded to the cent; dollars sum exactly."""
    eng = january
    with eng["lease_reader"].connect() as conn:
        result = backtest(conn, manual_rule(name="m", when={"charge_types": ["base_rent"]},
                                            scope={"entity_id": ENTITY}, then={"action": "hold"}))
    total = sum(Decimal(str(c["dollars"])) for c in result["changes"])
    assert Decimal(str(result["dollars"])) == total
