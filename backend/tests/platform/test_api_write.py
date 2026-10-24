"""The write side of the API, and auth on every route (PHASE_1.md group 11).

A Bay Area and a Desert clinic on top of the ledger world, items opened and
proposed by the checker through the real work layer as `lease_agent`, and
every request made with a real signed session cookie: the app's engines and
settings are swapped through `app.dependency_overrides`, nothing is patched.

The Phase 1 acceptance check lives here: as the Bay Area regional manager,
approve a Desert item through the API: 403, and the denied event is in the
timeline.
"""

import dataclasses
from decimal import Decimal

import ledger_world as w
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_gateway_engine
from app.auth.deps import api_engine, auth_settings
from app.auth.sessions import COOKIE_NAME, issue_token
from app.db.bootstrap import execute_raw
from app.main import create_app
from app.settings import get_settings, parse_origins
from app.work.roles import Actor, ensure_gateway_actor
from app.work.transitions import create_item, transition

SECRET = "test-write-secret"
CHECKER = Actor("agent:checker", "agent", None, None)


# --- the world ----------------------------------------------------------------------

@pytest.fixture
def world(books):
    w.build(books["owner"])
    with books["owner"].begin() as conn:
        execute_raw(conn, """
            INSERT INTO region VALUES ('REG-DESERT', 'Desert', 'PER-RM-DESERT');
            INSERT INTO center VALUES ('CTR-02', 'Desert Ridge', NULL, 'LL-01', 18000);
            INSERT INTO clinic VALUES ('CLINIC-21', 'Northbay PT Scottsdale', 'ENT-NV',
                                       'REG-DESERT', 'CTR-02', '4', 2100);
            INSERT INTO lease (id, clinic_id, landlord_id) VALUES ('LEASE-21', 'CLINIC-21', 'LL-01');
            INSERT INTO landlord_charge (id, lease_id, clinic_id, invoice_id, suite, period,
                                         charge_type, amount, raw_ref) VALUES
              ('CHG-DESERT-01', 'LEASE-21', 'CLINIC-21', 'INV-21', '4', '2026-01-01',
               'base_rent', 15200.00, 'RAW-1');
            INSERT INTO actor (id, name, role, region_id, entity_id, active) VALUES
              ('PER-RM-DESERT', 'Desi RM', 'regional_manager', 'REG-DESERT', 'ENT-NV', true),
              ('PER-AUD', 'Brennan Audit', 'auditor', NULL, NULL, true),
              ('agent:checker', 'Charge checker', 'agent', NULL, NULL, true);
        """)
        ensure_gateway_actor(conn)
    return books


CLINIC = {"CLINIC-01": ("ENT-CA", "REG-BAY"), "CLINIC-21": ("ENT-NV", "REG-DESERT")}


def open_item(engines, charge_id, clinic="CLINIC-01", period="2026-01-01", proposal="approve",
              state="PROPOSED", amount="19626.65"):
    """Create and (by default) propose a charge check as the checker would."""
    entity, region = CLINIC[clinic]
    with engines["lease_agent"].begin() as conn:
        item = create_item(conn, CHECKER, kind="CHARGE_CHECK", subject_type="landlord_charge",
                           subject_id=charge_id, title="check %s" % charge_id, entity_id=entity,
                           region_id=region, clinic_id=clinic, period=period, amount=amount,
                           evidence={"lease_id": "LEASE-01", "charge_id": charge_id,
                                     "billed": float(amount), "supported": float(amount)})
        if state != "NEW":
            transition(conn, CHECKER, item["id"], "propose", reason="matches the lease",
                       patch={"proposal": proposal})
    return item["id"]


def ask(engines, item_id, asked_to, body="Is this the right suite?"):
    with engines["lease_agent"].begin() as conn:
        transition(conn, CHECKER, item_id, "ask", patch={"asked_to": asked_to, "body": body})


def make_client(engines) -> TestClient:
    settings = dataclasses.replace(get_settings(), session_secret=SECRET,
                                   cors_origins=("http://localhost:3000",))
    app = create_app(settings)
    app.dependency_overrides[api_engine] = lambda: engines["lease_api"]
    app.dependency_overrides[get_gateway_engine] = lambda: engines["lease_gateway"]
    app.dependency_overrides[auth_settings] = lambda: settings
    return TestClient(app)


@pytest.fixture
def client(world):
    return make_client(world)


def as_(client, actor_id):
    client.cookies.set(COOKIE_NAME, issue_token(SECRET, actor_id))
    return client


def state(engines, item_id):
    return w.scalar(engines["lease_reader"], "SELECT state FROM work_item WHERE id = :i", i=item_id)


def audit(client, subject_type="work_item", subject_id=None):
    params = {"subject_type": subject_type}
    if subject_id is not None:
        params["subject_id"] = str(subject_id)
    body = client.get("/api/audit", params=params).json()
    assert body["chain_verified"] is True
    return body["events"]


# --- auth on every route ------------------------------------------------------------

READS = ["/api/leases", "/api/leases/LEASE-01/schedule", "/api/exceptions", "/api/exceptions/exc_1",
         "/api/audit", "/api/items", "/api/items/1", "/api/items/1/allowed-actions",
         "/api/documents/%s/pages" % ("0" * 64)]
WRITES = ["/api/items/1/actions/approve", "/api/exceptions/exc_1/approve",
          "/api/batches/2026-01/release"]


@pytest.mark.parametrize("path", READS)
def test_every_read_is_401_without_a_session(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", WRITES)
def test_every_write_is_401_without_a_session(client, path):
    assert client.post(path, json={}).status_code == 401


def test_a_forged_cookie_reads_nothing(client):
    client.cookies.set(COOKIE_NAME, issue_token("someone-elses-secret", "PER-CTRL"))
    assert client.get("/api/items").status_code == 401


def test_any_signed_in_person_may_read(client):
    for who in ("PER-CTRL", "PER-AP", "PER-RM-BAY", "PER-AUD"):
        assert as_(client, who).get("/api/leases").status_code == 200, who


# --- GET /api/items -----------------------------------------------------------------

def test_the_queue_is_scoped_like_can(client, world):
    bay = open_item(world, w.RENT)
    cam = open_item(world, w.CAM, state="NEW", amount="2100.00")
    desert = open_item(world, "CHG-DESERT-01", clinic="CLINIC-21", amount="15200.00")

    def ids(who):
        return {i["id"] for i in as_(client, who).get("/api/items").json()["items"]}

    assert ids("PER-RM-BAY") == {bay, cam}
    assert ids("PER-RM-DESERT") == {desert}
    assert ids("PER-AP") == {bay, cam}                 # entity ENT-CA
    assert ids("PER-AP-NV") == {desert}
    assert ids("PER-CTRL") == ids("PER-AUD") == ids("PER-AP-ALL") == {bay, cam, desert}


def test_the_queue_rows_and_counts(client, world):
    bay = open_item(world, w.RENT)
    open_item(world, w.CAM, state="NEW", amount="2100.00")
    body = as_(client, "PER-CTRL").get("/api/items").json()
    assert body["counts"] == {"NEW": 1, "PROPOSED": 1, "NEEDS_INFO": 0, "HELD": 0,
                              "APPROVED": 0, "REJECTED": 0, "POSTED": 0, "CLOSED": 0}
    assert body["total"] == 2
    row = next(i for i in body["items"] if i["id"] == bay)
    assert set(row) == {"id", "kind", "state", "title", "clinic_id", "region_id", "entity_id",
                        "period", "amount", "proposal", "reason", "updated_at"}
    assert (row["kind"], row["state"], row["clinic_id"], row["region_id"], row["period"],
            row["amount"], row["proposal"], row["reason"]) == (
        "CHARGE_CHECK", "PROPOSED", "CLINIC-01", "REG-BAY", "2026-01-01", 19626.65,
        "approve", "matches the lease")


def test_the_queue_filters_and_counts_ignore_the_state_filter(client, world):
    bay = open_item(world, w.RENT)
    open_item(world, w.CAM, state="NEW", amount="2100.00")
    desert = open_item(world, "CHG-DESERT-01", clinic="CLINIC-21", amount="15200.00")
    c = as_(client, "PER-CTRL")
    proposed = c.get("/api/items", params={"state": "PROPOSED"}).json()
    assert {i["id"] for i in proposed["items"]} == {bay, desert}
    assert proposed["counts"]["NEW"] == 1, "counts are for every state, so tabs can show them"
    assert [i["id"] for i in c.get("/api/items", params={"region_id": "REG-DESERT"}).json()["items"]] \
        == [desert]
    assert {i["id"] for i in c.get("/api/items", params={"clinic_id": "CLINIC-01",
                                                          "state": "PROPOSED"}).json()["items"]} == {bay}
    assert c.get("/api/items", params={"period": "2025-12-01"}).json()["total"] == 0


@pytest.mark.parametrize("params", [{"state": "DONE"}, {"period": "soon"}, {"limit": 0}])
def test_the_queue_rejects_bad_filters(client, params):
    assert as_(client, "PER-CTRL").get("/api/items", params=params).status_code == 422


def test_an_empty_queue(client):
    body = as_(client, "PER-RM-BAY").get("/api/items").json()
    assert body["total"] == 0 and body["items"] == [] and set(body["counts"].values()) == {0}


# --- GET /api/items/{id} and allowed-actions --------------------------------------

def test_item_detail_has_evidence_questions_and_timeline(client, world):
    item = open_item(world, w.RENT)
    ask(world, item, "PER-RM-BAY")
    body = as_(client, "PER-RM-BAY").get("/api/items/%d" % item).json()
    assert body["item"]["id"] == item and body["item"]["state"] == "NEEDS_INFO"
    assert body["evidence"]["charge_id"] == w.RENT
    [q] = body["questions"]
    assert (q["asked_to"], q["asked_by"], q["body"], q["answer"]) == (
        "PER-RM-BAY", "agent:checker", "Is this the right suite?", None)
    assert [(e["action"], e["from_state"], e["to_state"]) for e in body["timeline"]] == [
        ("create", None, "NEW"), ("propose", "NEW", "PROPOSED"), ("ask", "PROPOSED", "NEEDS_INFO")]
    assert body["allowed_actions"] == ["answer", "hold"]


def test_allowed_actions_come_from_can(client, world):
    bay = open_item(world, w.RENT)
    assert as_(client, "PER-RM-BAY").get("/api/items/%d/allowed-actions" % bay).json() == {
        "actions": ["hold", "approve", "reject"]}
    assert as_(client, "PER-CTRL").get("/api/items/%d/allowed-actions" % bay).json() == {
        "actions": ["hold", "approve", "reject"]}
    for who in ("PER-AUD", "PER-AP"):           # AP clerks only touch PAYMENT_RELEASE items
        assert as_(client, who).get("/api/items/%d/allowed-actions" % bay).json() == {"actions": []}


def test_an_item_outside_your_scope_or_unknown_is_404(client, world):
    desert = open_item(world, "CHG-DESERT-01", clinic="CLINIC-21", amount="15200.00")
    c = as_(client, "PER-RM-BAY")
    assert c.get("/api/items/%d" % desert).status_code == 404
    assert c.get("/api/items/%d/allowed-actions" % desert).status_code == 404
    assert c.get("/api/items/999999").status_code == 404
    assert c.get("/api/items/abc").status_code == 422
    assert c.get("/api/items/0").status_code == 422
    assert c.get("/api/items/99999999999999999999").status_code == 422


# --- POST /api/items/{id}/actions/{action} ------------------------------------------

def test_acceptance_bay_manager_approving_a_desert_item_is_403_and_on_record(client, world):
    """PHASE_1.md Acceptance Criteria: 403, and a denied event in the timeline."""
    desert = open_item(world, "CHG-DESERT-01", clinic="CLINIC-21", amount="15200.00")
    response = as_(client, "PER-RM-BAY").post("/api/items/%d/actions/approve" % desert, json={})
    assert response.status_code == 403
    assert "PER-RM-BAY" in response.json()["detail"]
    assert state(world, desert) == "PROPOSED", "nothing changed"

    denied = [e for e in audit(client, subject_id=desert) if not e["allowed"]]
    assert [(e["actor_id"], e["action"]) for e in denied] == [("PER-RM-BAY", "approve")]
    assert denied[0]["reason"] == response.json()["detail"]
    # And in the item's own timeline, as its own region's manager sees it.
    timeline = as_(client, "PER-RM-DESERT").get("/api/items/%d" % desert).json()["timeline"]
    assert [(e["actor_id"], e["action"], e["allowed"]) for e in timeline][-1] == (
        "PER-RM-BAY", "approve", False)


def test_the_desert_manager_may_approve_their_own_region(client, world):
    desert = open_item(world, "CHG-DESERT-01", clinic="CLINIC-21", amount="15200.00")
    response = as_(client, "PER-RM-DESERT").post("/api/items/%d/actions/approve" % desert)
    assert response.status_code == 200
    # ENT-NV has no chart or open period in this world: the approval stands, posting waits.
    assert response.json()["state"] == "APPROVED"
    assert response.json()["posting"]["status"] == "pending"


def test_approving_a_charge_check_posts_it_through_the_gateway(client, world):
    item = open_item(world, w.RENT)
    response = as_(client, "PER-RM-BAY").post("/api/items/%d/actions/approve" % item,
                                              json={"reason": "matches the lease"})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "POSTED" and body["item"]["state"] == "POSTED"
    assert body["posting"]["status"] == "posted"
    entry = body["posting"]["journal_entry_id"]
    assert w.scalar(world["lease_reader"], "SELECT work_item_id FROM journal_entry WHERE id = :e",
                    e=entry) == item
    assert w.scalar(world["lease_reader"], "SELECT sum(debit) FROM journal_line "
                    "WHERE journal_entry_id = :e", e=entry) == Decimal("19626.65")
    events = audit(client, subject_id=item)
    assert [(e["actor_id"], e["action"]) for e in events][-2:] == [
        ("PER-RM-BAY", "approve"), ("system:gateway", "post")]


def test_a_failed_post_keeps_the_approval_and_says_pending(client, world):
    """December is closed: the gateway refuses, the approval is not lost."""
    item = open_item(world, w.RENT_DEC, period="2025-12-01")
    response = as_(client, "PER-RM-BAY").post("/api/items/%d/actions/approve" % item)
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "APPROVED" and state(world, item) == "APPROVED"
    assert body["posting"]["status"] == "pending" and body["posting"]["journal_entry_id"] is None
    assert "closed" in body["posting"]["error"].lower()
    assert w.scalar(world["lease_reader"], "SELECT count(*) FROM journal_entry") == 0
    assert audit(client, subject_id=item)[-1]["action"] == "approve"


def test_hold_resume_reject_and_close(client, world):
    item = open_item(world, w.RENT)
    c = as_(client, "PER-RM-BAY")
    held = c.post("/api/items/%d/actions/hold" % item, json={"reason": "waiting on landlord"}).json()
    assert held["state"] == "HELD" and held["item"]["reason"] == "waiting on landlord"
    assert held["posting"] is None
    assert c.post("/api/items/%d/actions/resume" % item).json()["state"] == "PROPOSED"
    assert c.post("/api/items/%d/actions/reject" % item, json={"reason": "wrong suite"}
                  ).json()["state"] == "REJECTED"
    assert c.post("/api/items/%d/actions/close" % item).status_code == 403, \
        "only the controller closes"
    assert as_(client, "PER-CTRL").post("/api/items/%d/actions/close" % item
                                        ).json()["state"] == "CLOSED"


def test_separation_of_duties_whoever_answered_cannot_approve(client, world):
    item = open_item(world, w.RENT)
    ask(world, item, "PER-RM-BAY")
    c = as_(client, "PER-RM-BAY")
    answered = c.post("/api/items/%d/actions/answer" % item,
                      json={"patch": {"answer": "Yes, suite 110."}})
    assert answered.status_code == 200 and answered.json()["state"] == "PROPOSED"
    assert "approve" not in c.get("/api/items/%d/allowed-actions" % item).json()["actions"]

    response = c.post("/api/items/%d/actions/approve" % item)
    assert response.status_code == 403
    assert "separation of duties" in response.json()["detail"]
    assert audit(client, subject_id=item)[-1]["allowed"] is False
    assert state(world, item) == "PROPOSED"

    # Someone else may.
    assert as_(client, "PER-CTRL").post("/api/items/%d/actions/approve" % item
                                        ).json()["state"] == "POSTED"


def test_answer_takes_the_reason_when_no_patch(client, world):
    item = open_item(world, w.RENT)
    ask(world, item, "PER-RM-BAY")
    as_(client, "PER-RM-BAY").post("/api/items/%d/actions/answer" % item,
                                   json={"reason": "Suite 110, confirmed."})
    [q] = client.get("/api/items/%d" % item).json()["questions"]
    assert (q["answer"], q["answered_by"]) == ("Suite 110, confirmed.", "PER-RM-BAY")


def test_a_move_the_machine_does_not_have_is_409(client, world):
    item = open_item(world, w.RENT)
    response = as_(client, "PER-RM-BAY").post("/api/items/%d/actions/resume" % item)
    assert response.status_code == 409 and "PROPOSED" in response.json()["detail"]


def test_unknown_item_is_404_and_non_human_actions_are_422(client, world):
    item = open_item(world, w.RENT)
    c = as_(client, "PER-CTRL")
    assert c.post("/api/items/999999/actions/approve").status_code == 404
    for action in ("post", "propose", "ask", "delete"):
        assert c.post("/api/items/%d/actions/%s" % (item, action)).status_code == 422, action
    assert state(world, item) == "PROPOSED"


@pytest.mark.parametrize("body", [{"patch": {"state": "POSTED"}}, {"patch": {"amount": "lots"}},
                                  {"patch": "approve"}, {"reason": "x" * 5000}])
def test_bad_bodies_are_422_and_change_nothing(client, world, body):
    item = open_item(world, w.RENT)
    response = as_(client, "PER-RM-BAY").post("/api/items/%d/actions/hold" % item, json=body)
    assert response.status_code == 422
    assert state(world, item) == "PROPOSED"


def test_answering_without_an_answer_is_422(client, world):
    item = open_item(world, w.RENT)
    ask(world, item, "PER-RM-BAY")
    response = as_(client, "PER-RM-BAY").post("/api/items/%d/actions/answer" % item, json={})
    assert response.status_code == 422 and state(world, item) == "NEEDS_INFO"


def test_the_auditor_can_never_write(client, world):
    item = open_item(world, w.RENT)
    exc = open_item(world, w.CAM, proposal="hold", amount="2100.00")
    c = as_(client, "PER-AUD")
    for action in ("approve", "hold", "resume", "reject", "answer", "close"):
        response = c.post("/api/items/%d/actions/%s" % (item, action), json={"reason": "x"})
        assert response.status_code == 403, action
    assert c.post("/api/exceptions/exc_%d/approve" % exc).status_code == 403
    assert c.post("/api/batches/2026-01/release", json={"entity_id": "ENT-CA"}).status_code == 403
    assert state(world, item) == state(world, exc) == "PROPOSED"
    denied = [(e["action"]) for e in audit(client, subject_id=item) if not e["allowed"]]
    assert denied == ["approve", "hold", "resume", "reject", "answer", "close"]
    assert [e["allowed"] for e in audit(client, subject_type="ap_batch")] == [False]


# --- POST /api/exceptions/{id}/approve (§16 #4) -------------------------------------

def test_exception_approve_returns_the_new_status(client, world):
    exc = open_item(world, w.CAM, proposal="hold", amount="2100.00")
    c = as_(client, "PER-RM-BAY")
    assert c.get("/api/exceptions/exc_%d" % exc).json()["status"] == "pending_review"
    response = c.post("/api/exceptions/exc_%d/approve" % exc)
    assert response.status_code == 200 and response.json() == {"status": "balanced"}
    assert state(world, exc) == "POSTED"
    assert c.post("/api/exceptions/exc_%d/approve" % exc).status_code == 409, "already done"


def test_exception_approve_is_refused_out_of_region_and_on_record(client, world):
    desert = open_item(world, "CHG-DESERT-01", clinic="CLINIC-21", proposal="hold",
                       amount="15200.00")
    response = as_(client, "PER-RM-BAY").post("/api/exceptions/exc_%d/approve" % desert)
    assert response.status_code == 403
    assert [(e["actor_id"], e["allowed"]) for e in audit(client, subject_id=desert)][-1] == (
        "PER-RM-BAY", False)


@pytest.mark.parametrize("exc_id", ["exc_999999", "LEASE-01", "exc_abc"])
def test_exception_approve_of_no_exception_is_404(client, world, exc_id):
    assert as_(client, "PER-CTRL").post("/api/exceptions/%s/approve" % exc_id).status_code == 404


def test_exception_approve_of_an_approve_proposal_is_404(client, world):
    item = open_item(world, w.RENT)            # proposal approve: not an exception
    assert as_(client, "PER-CTRL").post("/api/exceptions/exc_%d/approve" % item).status_code == 404
    assert state(world, item) == "PROPOSED"


# --- POST /api/batches/{period}/release ---------------------------------------------

def test_the_ap_clerk_releases_the_batch_once(client, world):
    item = open_item(world, w.RENT)
    as_(client, "PER-RM-BAY").post("/api/items/%d/actions/approve" % item)
    first = as_(client, "PER-AP").post("/api/batches/2026-01/release")
    assert first.status_code == 200
    body = first.json()
    assert (body["created"], body["item_count"], body["total"], body["period"]) == (
        True, 1, 19626.65, "2026-01-01")
    assert body["idempotency_key"] == "ap_batch:ENT-CA:2026-01"
    assert w.scalar(world["lease_reader"], "SELECT kind FROM outbox WHERE id = :i",
                    i=body["outbox_id"]) == "ap_batch"
    again = client.post("/api/batches/2026-01-01/release").json()
    assert (again["created"], again["outbox_id"]) == (False, body["outbox_id"])
    assert [e["action"] for e in audit(client, subject_type="ap_batch")] == ["release_batch"]


@pytest.mark.parametrize("who", ["PER-RM-BAY", "PER-CTRL"])
def test_only_an_ap_clerk_releases_and_the_refusal_is_on_record(client, world, who):
    item = open_item(world, w.RENT)
    as_(client, "PER-CTRL").post("/api/items/%d/actions/approve" % item)
    response = as_(client, who).post("/api/batches/2026-01/release", json={"entity_id": "ENT-CA"})
    assert response.status_code == 403 and "AP clerk" in response.json()["detail"]
    [event] = audit(client, subject_type="ap_batch")
    assert (event["actor_id"], event["allowed"]) == (who, False)
    assert w.scalar(world["lease_reader"], "SELECT count(*) FROM outbox") == 0


def test_another_entitys_clerk_is_refused(client, world):
    response = as_(client, "PER-AP-NV").post("/api/batches/2026-01/release",
                                             json={"entity_id": "ENT-CA"})
    assert response.status_code == 403


def test_nothing_approved_is_409(client, world):
    open_item(world, w.RENT)                  # proposed, not approved
    response = as_(client, "PER-AP").post("/api/batches/2026-01/release")
    assert response.status_code == 409 and "nothing to release" in response.json()["detail"]


@pytest.mark.parametrize("period", ["2026-13", "2026-01-15", "january", "26-01"])
def test_a_bad_period_is_422(client, period):
    assert as_(client, "PER-AP").post("/api/batches/%s/release" % period).status_code == 422


# --- CORS -------------------------------------------------------------------------

def test_cors_lets_the_dev_server_send_the_cookie(client):
    response = client.options("/api/items/1/actions/approve", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"
    simple = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert simple.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_ignores_other_origins(client):
    response = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_origins_setting():
    assert parse_origins("http://localhost:3000") == ("http://localhost:3000",)
    assert parse_origins(" https://a.example/ , http://localhost:3000,, ") == (
        "https://a.example", "http://localhost:3000")
    assert parse_origins("") == ()
    with pytest.raises(ValueError):
        parse_origins("*")


def test_cors_origins_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("LEASEDESK_CORS_ORIGINS", "https://desk.example,http://localhost:3001")
    get_settings.cache_clear()
    try:
        assert get_settings().cors_origins == ("https://desk.example", "http://localhost:3001")
    finally:
        monkeypatch.delenv("LEASEDESK_CORS_ORIGINS")
        get_settings.cache_clear()
    assert get_settings().cors_origins == ("http://localhost:3000",)
