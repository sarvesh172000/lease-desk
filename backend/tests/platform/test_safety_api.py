"""Every write endpoint refuses a caller with no session (401) and an auditor
(403, with the refusal on record), and changes nothing either way.

The routes are read from the FastAPI app itself, not listed by hand, so an
endpoint added later is covered the day it lands. A write route only escapes
this by being named below with the reason it is not a write behind a session:
the sign-in doors, and a POST that only streams what is already recorded. A
path parameter this file has no value for fails loudly, asking for one.
"""

import dataclasses

import ledger_world as w
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_agent_engine, get_gateway_engine
from app.api.exceptions import sse_delay
from app.auth.deps import api_engine, auth_settings
from app.auth.sessions import COOKIE_NAME, issue_token
from app.db.bootstrap import execute_raw
from app.main import create_app
from app.settings import get_settings
from app.work import limits
from app.work.roles import Actor, ensure_gateway_actor
from app.work.transitions import create_item, transition

SECRET = "test-safety-secret"
AUDITOR = "PER-AUD"
CHECKER = Actor("agent:checker", "agent", None, None)
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
BODY = {"reason": "safety test", "entity_id": "ENT-CA", "outcome": "acknowledged"}

# Write routes that are not "a write behind a session", and why.
SIGN_IN = {
    "/api/auth/login": "the door a session comes from; it cannot require one",
    "/api/auth/logout": "clears the caller's own cookie; touches no data",
    "/api/auth/demo-switch": "demo-mode sign-in (404 when demo mode is off)",
    # Chat pairing (C8) manages a person's own chat session, like login and
    # logout; tests/platform/test_pairing.py covers who may call each one.
    "/api/pairing/codes": "mints a code for the caller's own chat; any signed-in person",
    "/api/pairing/{pairing_id}/revoke": "ends one of the caller's own pairings",
    "/api/pairing/claim": "the door a chat pairing comes from: a one-time code, not a session",
    "/api/pairing/me/revoke": "a paired chat ending its own pairing (bearer token, not a cookie)",
}
READ_ONLY = {
    "/api/items/{item_id}/why": "POST only to carry a question; answers from read-only queries as lease_reader",
    "/api/evidence-packs": "POST only to carry the subject; builds a PDF as lease_reader, writes nothing",
}

# A value for each path parameter a write route may have. A Literal-typed
# parameter (the queue's {action}) is expanded to every value it allows.
ITEM = 1
PARAMS = {"item_id": str(ITEM), "exc_id": "exc_%d" % ITEM, "period": "2026-01",
          "lease_id": "LEASE-01", "dispute_id": "DSP-000001", "policy_id": "1", "pairing_id": "1"}


def _write_routes():
    """(method, path template, path parameters) of every write route, from the
    app's own OpenAPI schema (FastAPI builds it from the mounted routers)."""
    out = []
    for path, operations in create_app().openapi()["paths"].items():
        for method, operation in operations.items():
            if method.upper() in WRITE_METHODS:
                params = [p for p in operation.get("parameters", []) if p["in"] == "path"]
                out.append((method.upper(), path, params))
    return out


def _cases():
    out = []
    for method, path, params in _write_routes():
        if path in SIGN_IN or path in READ_ONLY:
            continue
        paths = [path]
        for param in params:
            name, schema = param["name"], param.get("schema", {})
            if "enum" in schema:                    # a Literal: try every value
                values = [str(v) for v in schema["enum"]]
            elif name in PARAMS:
                values = [PARAMS[name]]
            else:
                raise AssertionError("%s has a path parameter {%s} test_safety_api.py has no "
                                     "value for; add one to PARAMS" % (path, name))
            paths = [p.replace("{%s}" % name, v) for p in paths for v in values]
        out.extend((method, p) for p in paths)
    return out


CASES = _cases()


@pytest.fixture
def world(books):
    """The ledger world, a held charge check (item 1) the checker proposed,
    and an auditor."""
    w.build(books["owner"])
    with books["owner"].begin() as conn:
        execute_raw(conn, """
            INSERT INTO actor (id, name, role, active) VALUES
              ('agent:checker', 'Charge checker', 'agent', true),
              ('PER-AUD', 'External Auditor', 'auditor', true);
        """)
        ensure_gateway_actor(conn)
    with books["lease_agent"].begin() as conn:
        item = create_item(conn, CHECKER, kind="CHARGE_CHECK", subject_type="landlord_charge",
                           subject_id=w.RENT, title="January rent", entity_id="ENT-CA",
                           region_id="REG-BAY", clinic_id="STORE-01", period="2026-01-01",
                           amount="19626.65", evidence={"lease_id": "LEASE-01", "billed": 19626.65,
                                                        "supported": 15000.00})
        transition(conn, CHECKER, item["id"], "propose", reason="billed above the lease",
                   patch={"proposal": "hold"})
    assert item["id"] == ITEM
    return books


def make_client(engines, **overrides) -> TestClient:
    settings = dataclasses.replace(get_settings(), session_secret=SECRET, **overrides)
    app = create_app(settings)
    app.dependency_overrides[api_engine] = lambda: engines["lease_api"]
    app.dependency_overrides[get_gateway_engine] = lambda: engines["lease_gateway"]
    app.dependency_overrides[get_agent_engine] = lambda: engines["lease_agent"]
    app.dependency_overrides[auth_settings] = lambda: settings
    app.dependency_overrides[sse_delay] = lambda: 0
    return TestClient(app)


def footprint(engines, exclude=()):
    with engines["owner"].connect() as conn:
        return limits.table_footprint(conn, exclude=tuple(exclude))


def auditor_refusals(engines):
    with engines["owner"].connect() as conn:
        return conn.execute(text("""
            SELECT seq, action, subject_type, subject_id, reason FROM audit_event
             WHERE actor_id = :a AND NOT allowed ORDER BY seq
        """), {"a": AUDITOR}).mappings().all()


def call(client, method, path):
    return client.request(method, path, json=BODY)


# ------------------------------------------------------------------ coverage

def test_the_route_list_is_real_and_the_exemptions_are_not_stale():
    paths = {path for _, path, _ in _write_routes()}
    for exempt in list(SIGN_IN) + list(READ_ONLY):
        assert exempt in paths, "%s is exempted but no longer exists" % exempt
    covered = {p for _, p in CASES}
    assert any(p.startswith("/api/items/") for p in covered)
    assert any(p.startswith("/api/exceptions/") for p in covered)
    assert any(p.startswith("/api/batches/") for p in covered)
    assert len(CASES) >= 9   # six queue actions, three exception actions, one release


# --------------------------------------------------------------- the checks

@pytest.mark.parametrize("method,path", CASES, ids=["%s %s" % c for c in CASES])
def test_a_write_without_a_session_is_401_and_changes_nothing(world, method, path):
    client = make_client(world)
    before = footprint(world)
    response = call(client, method, path)
    assert response.status_code == 401, response.text
    assert footprint(world) == before


@pytest.mark.parametrize("method,path", CASES, ids=["%s %s" % c for c in CASES])
def test_a_write_by_an_auditor_is_403_on_record_and_changes_nothing_else(world, method, path):
    client = make_client(world)
    client.cookies.set(COOKIE_NAME, issue_token(SECRET, AUDITOR))
    before, refusals = footprint(world, exclude=["audit_event"]), auditor_refusals(world)

    response = call(client, method, path)

    assert response.status_code == 403, response.text
    new = auditor_refusals(world)[len(refusals):]
    assert len(new) == 1, "the 403 must leave exactly one allowed = false event: %s" % new
    assert footprint(world, exclude=["audit_event"]) == before
    with world["lease_reader"].connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_verify_chain()")).scalar() == 0


# ---------------------------------------------------------------- exemptions

@pytest.mark.parametrize("path", sorted(READ_ONLY))
def test_a_read_only_post_needs_a_session_and_writes_nothing_even_for_an_auditor(world, path):
    path = path.replace("{exc_id}", PARAMS["exc_id"]).replace("{item_id}", PARAMS["item_id"])
    client = make_client(world)
    before = footprint(world)
    assert call(client, "POST", path).status_code == 401
    client.cookies.set(COOKIE_NAME, issue_token(SECRET, AUDITOR))
    # The auditor may use a read-only POST: never refused for being an auditor
    # (a 404 or 422 for this test's placeholder subject is fine), and nothing,
    # not even an audit event, is written.
    assert call(client, "POST", path).status_code not in (401, 403)
    assert footprint(world) == before


def test_the_sign_in_doors_write_nothing(world):
    before = footprint(world)
    client = make_client(world, demo_mode=False)
    assert client.post("/api/auth/login", json={"email": "audit@x.example",
                                                "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/logout").status_code == 204
    assert client.post("/api/auth/demo-switch",
                       json={"actor_id": "PER-CTRL"}).status_code == 404
    assert footprint(world) == before


def test_an_agent_can_never_hold_a_session(world):
    """Agents act through the worker as lease_agent, never through the API:
    a valid cookie naming an agent is refused like no cookie at all."""
    client = make_client(world)
    client.cookies.set(COOKIE_NAME, issue_token(SECRET, CHECKER.id))
    before = footprint(world)
    for method, path in CASES:
        assert call(client, method, path).status_code == 401, path
    assert footprint(world) == before
