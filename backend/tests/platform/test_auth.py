"""Login end to end: the seeded org chart, real argon2 hashes, the API as lease_api.

Seeding goes through the same `load_org` / `load_actors` the real seed uses,
on a lease_gateway connection, then `set_dev_passwords` gives every person
`demo`. The app's engine and settings are swapped through
`app.dependency_overrides`, so nothing here patches a module.
"""

import dataclasses
import time

import itsdangerous.timed
import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import passwords
from app.auth.deps import (
    SessionActor,
    api_engine,
    auth_settings,
    current_actor,
    require_role,
)
from app.auth.routes import INVALID_LOGIN
from app.auth.sessions import COOKIE_NAME, MAX_AGE_SECONDS, issue_token
from app.main import create_app
from app.records.golden import load_actors, load_org
from app.settings import get_settings

SECRET = "test-session-secret"
CTRL = "priya.raghunathan@northbaypt.example"
AP = "marcus.oyelaran@northbaypt.example"
RM = "dana.whitfield@northbaypt.example"
AUDITOR = "audit@brennan-cpa.example"
HUMANS = {"PER-RM-BAY", "PER-AP", "PER-CTRL", "PER-AUD"}


@pytest.fixture(scope="module")
def company():
    from datagen.company import build_company

    return build_company()


@pytest.fixture
def seeded(clean, company):
    with clean["lease_gateway"].begin() as conn:
        load_org(conn, company)
        load_actors(conn, company)
        passwords.set_dev_passwords(conn, demo_mode=True)
    return clean


def _client(engines, demo_mode=True):
    app = create_app()
    settings = dataclasses.replace(get_settings(), demo_mode=demo_mode, session_secret=SECRET)
    app.dependency_overrides[api_engine] = lambda: engines["lease_api"]
    app.dependency_overrides[auth_settings] = lambda: settings

    probe = APIRouter()

    @probe.get("/probe/controller-only")
    def controller_only(actor: SessionActor = Depends(require_role("controller"))):
        return {"ok": actor.id}

    @probe.get("/probe/any")
    def any_actor(actor: SessionActor = Depends(current_actor)):
        return {"ok": actor.id}

    app.include_router(probe)
    return TestClient(app)


@pytest.fixture
def client(seeded):
    return _client(seeded)


def _gateway(engines, sql, **params):
    with engines["lease_gateway"].begin() as conn:
        conn.execute(text(sql), params)


def _login(client, email, password="demo"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ------------------------------------------------------------------ login

def test_login_sets_a_hardened_cookie_and_returns_the_actor(client):
    response = _login(client, CTRL)
    assert response.status_code == 200
    assert response.json() == {"id": "PER-CTRL", "name": "Priya Raghunathan",
                               "role": "controller", "region_id": None, "entity_id": None}
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith(COOKIE_NAME + "=")
    for attribute in ("httponly", "samesite=lax", "max-age=%d" % MAX_AGE_SECONDS, "path=/"):
        assert attribute in cookie
    assert "password" not in response.text and "argon2" not in response.text


def test_me_after_login_and_regional_scope_comes_from_the_database(client):
    _login(client, RM)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "regional_manager" and me.json()["region_id"] == "REG-BAY"


def test_every_seeded_person_can_log_in_including_the_auditor(client):
    for email, actor_id in ((CTRL, "PER-CTRL"), (AP, "PER-AP"), (RM, "PER-RM-BAY"),
                            (AUDITOR, "PER-AUD")):
        assert _login(client, email).json()["id"] == actor_id


def test_email_is_matched_without_case_or_surrounding_space(client):
    assert _login(client, "  Priya.Raghunathan@NorthbayPT.example ").status_code == 200


def test_wrong_password_and_unknown_email_look_identical(client):
    wrong = _login(client, CTRL, "not-demo")
    unknown = _login(client, "nobody@northbaypt.example")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": INVALID_LOGIN}
    assert "set-cookie" not in wrong.headers and "set-cookie" not in unknown.headers


def test_unknown_email_still_does_one_argon2_verify(client, monkeypatch):
    seen = []
    real = passwords.verify_password
    monkeypatch.setattr(passwords, "verify_password",
                        lambda h, p: seen.append(h) or real(h, p))
    _login(client, "nobody@northbaypt.example")
    _login(client, CTRL, "wrong")
    assert len(seen) == 2
    assert seen[0] == passwords.dummy_hash() and seen[1] != passwords.dummy_hash()


def test_a_person_with_no_password_hash_cannot_log_in(client, seeded):
    _gateway(seeded, "UPDATE actor SET password_hash = NULL WHERE id = 'PER-AP'")
    assert _login(client, AP).json() == {"detail": INVALID_LOGIN}


def test_a_corrupt_hash_is_a_failed_login_not_a_500(client, seeded):
    _gateway(seeded, "UPDATE actor SET password_hash = 'garbage' WHERE id = 'PER-AP'")
    assert _login(client, AP).status_code == 401


def test_an_inactive_person_cannot_log_in_even_with_the_right_password(client, seeded):
    _gateway(seeded, "UPDATE actor SET active = false WHERE id = 'PER-AP'")
    assert _login(client, AP).json() == {"detail": INVALID_LOGIN}


def test_an_agent_can_never_log_in_even_with_an_email_and_a_hash(client, seeded):
    _gateway(seeded, "UPDATE actor SET email = 'checker@agents.example', password_hash = :h "
                     "WHERE id = 'agent:checker'", h=passwords.hash_password("demo"))
    assert _login(client, "checker@agents.example").json() == {"detail": INVALID_LOGIN}


@pytest.mark.parametrize("body", [{}, {"email": CTRL}, {"password": "demo"},
                                  {"email": "", "password": "demo"},
                                  {"email": CTRL, "password": ""},
                                  {"email": CTRL, "password": "x" * 2000}])
def test_malformed_login_bodies_are_422(client, body):
    assert client.post("/api/auth/login", json=body).status_code == 422


# ------------------------------------------------------- sessions and me

def test_me_without_a_session_is_401(client):
    assert client.get("/api/auth/me").status_code == 401


def test_logout_ends_the_session(client):
    _login(client, CTRL)
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    assert COOKIE_NAME in response.headers["set-cookie"]
    assert client.get("/api/auth/me").status_code == 401


def test_logout_without_a_session_is_harmless(client):
    assert client.post("/api/auth/logout").status_code == 204


def test_tampered_cookie_is_401(client):
    token = issue_token(SECRET, "PER-AP")
    forged = issue_token(SECRET, "PER-CTRL").split(".", 1)[0] + "." + token.split(".", 1)[1]
    client.cookies.set(COOKIE_NAME, forged)
    assert client.get("/api/auth/me").status_code == 401


def test_cookie_signed_with_another_secret_is_401(client):
    client.cookies.set(COOKIE_NAME, issue_token("not-our-secret", "PER-CTRL"))
    assert client.get("/api/auth/me").status_code == 401


def test_raw_actor_id_as_a_cookie_is_401(client):
    client.cookies.set(COOKIE_NAME, "PER-CTRL")
    assert client.get("/api/auth/me").status_code == 401


def test_expired_session_is_401(client, monkeypatch):
    _login(client, CTRL)
    later = int(time.time()) + MAX_AGE_SECONDS + 60
    monkeypatch.setattr(itsdangerous.timed.TimestampSigner, "get_timestamp", lambda self: later)
    assert client.get("/api/auth/me").status_code == 401


def test_deactivation_ends_an_open_session_on_the_next_request(client, seeded):
    _login(client, AP)
    assert client.get("/api/auth/me").status_code == 200
    _gateway(seeded, "UPDATE actor SET active = false WHERE id = 'PER-AP'")
    assert client.get("/api/auth/me").status_code == 401


def test_a_role_change_shows_on_the_next_request(client, seeded):
    _login(client, AP)
    _gateway(seeded, "UPDATE actor SET role = 'controller' WHERE id = 'PER-AP'")
    assert client.get("/api/auth/me").json()["role"] == "controller"


def test_a_valid_cookie_naming_an_agent_is_401(client):
    client.cookies.set(COOKIE_NAME, issue_token(SECRET, "agent:checker"))
    assert client.get("/api/auth/me").status_code == 401


def test_a_valid_cookie_naming_nobody_is_401(client):
    client.cookies.set(COOKIE_NAME, issue_token(SECRET, "PER-GONE"))
    assert client.get("/api/auth/me").status_code == 401


# ------------------------------------------------------------ require_role

def test_require_role_is_401_then_403_then_passes(client):
    assert client.get("/probe/controller-only").status_code == 401
    _login(client, AP)
    assert client.get("/probe/any").json() == {"ok": "PER-AP"}
    forbidden = client.get("/probe/controller-only")
    assert forbidden.status_code == 403 and "controller" in forbidden.json()["detail"]
    _login(client, CTRL)
    assert client.get("/probe/controller-only").json() == {"ok": "PER-CTRL"}


# -------------------------------------------------------------- demo mode

def test_demo_actors_lists_people_never_agents_or_hashes(client):
    response = client.get("/api/auth/demo-actors")
    assert response.status_code == 200
    actors = response.json()
    assert {a["id"] for a in actors} == HUMANS
    assert all(set(a) == {"id", "name", "role", "region_id", "entity_id"} for a in actors)


def test_demo_actors_omits_the_deactivated(client, seeded):
    _gateway(seeded, "UPDATE actor SET active = false WHERE id = 'PER-AUD'")
    assert {a["id"] for a in client.get("/api/auth/demo-actors").json()} == HUMANS - {"PER-AUD"}


def test_demo_switch_becomes_someone_without_a_password(client, seeded):
    _gateway(seeded, "UPDATE actor SET password_hash = NULL")       # no passwords needed
    _login(client, CTRL)
    switched = client.post("/api/auth/demo-switch", json={"actor_id": "PER-RM-BAY"})
    assert switched.status_code == 200 and switched.json()["id"] == "PER-RM-BAY"
    assert client.get("/api/auth/me").json()["id"] == "PER-RM-BAY"


@pytest.mark.parametrize("actor_id", ["agent:checker", "PER-GONE"])
def test_demo_switch_to_an_agent_or_nobody_is_404(client, actor_id):
    response = client.post("/api/auth/demo-switch", json={"actor_id": actor_id})
    assert response.status_code == 404
    assert "set-cookie" not in response.headers


def test_demo_switch_to_a_deactivated_person_is_404(client, seeded):
    _gateway(seeded, "UPDATE actor SET active = false WHERE id = 'PER-AP'")
    assert client.post("/api/auth/demo-switch", json={"actor_id": "PER-AP"}).status_code == 404


def test_demo_routes_do_not_exist_with_demo_mode_off(seeded):
    client = _client(seeded, demo_mode=False)
    assert client.get("/api/auth/demo-actors").status_code == 404
    response = client.post("/api/auth/demo-switch", json={"actor_id": "PER-CTRL"})
    assert response.status_code == 404 and "set-cookie" not in response.headers
    # Password login still works.
    assert _login(client, CTRL).status_code == 200


# ---------------------------------------------------------- dev passwords

def _hashes(engines):
    with engines["lease_gateway"].connect() as conn:
        return dict(conn.execute(text("SELECT id, password_hash FROM actor")).all())


def test_dev_passwords_cover_people_and_skip_agents(seeded):
    hashes = _hashes(seeded)
    assert all(passwords.verify_password(hashes[p], "demo") for p in HUMANS)
    assert all(hashes[a] is None for a in hashes if a.startswith("agent:"))


def test_dev_passwords_are_idempotent(seeded):
    before = _hashes(seeded)
    with seeded["lease_gateway"].begin() as conn:
        assert passwords.set_dev_passwords(conn, demo_mode=True) == []
    assert _hashes(seeded) == before


def test_dev_passwords_replace_a_stale_hash(seeded):
    _gateway(seeded, "UPDATE actor SET password_hash = NULL WHERE id = 'PER-AP'")
    with seeded["lease_gateway"].begin() as conn:
        assert passwords.set_dev_passwords(conn, demo_mode=True) == ["PER-AP"]


def test_dev_passwords_refuse_with_demo_mode_off(seeded):
    _gateway(seeded, "UPDATE actor SET password_hash = NULL")
    with seeded["lease_gateway"].begin() as conn:
        with pytest.raises(passwords.DevPasswordsRefused):
            passwords.set_dev_passwords(conn, demo_mode=False)
    assert all(h is None for h in _hashes(seeded).values())


def test_the_api_role_cannot_set_passwords(seeded):
    """Login reads hashes as lease_api; only the gateway may write them."""
    from sqlalchemy.exc import ProgrammingError

    _gateway(seeded, "UPDATE actor SET password_hash = NULL WHERE id = 'PER-AP'")
    with pytest.raises(ProgrammingError, match="permission denied"):
        with seeded["lease_api"].begin() as conn:
            passwords.set_dev_passwords(conn, demo_mode=True)
