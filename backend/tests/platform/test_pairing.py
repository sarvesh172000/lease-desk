"""/api/pairing and the scoped chat session it issues (PHASE_3.md group 9).

A one-time code from a signed-in person, claimed once by the front desk for
a chat user, becomes a bearer token that acts as that person on the chat
routes only. Real app, real database, real cookies; nothing patched.
"""

import json

import ledger_world as w
import pytest
from sqlalchemy import text
from test_api_write import as_, make_client, open_item, world  # noqa: F401 — fixtures

from app.agents import investigation_run
from app.api.exceptions import investigation_runner, sse_delay
from app.auth import pairing

CHAT = "agent1qchatuserdesert000000000000000000000000000000000000000"
OTHER_CHAT = "agent1qsomeoneelse0000000000000000000000000000000000000000000"


@pytest.fixture
def client(world):  # noqa: F811
    return make_client(world)


def mint(world, actor_id="PER-RM-BAY"):  # noqa: F811
    web = as_(make_client(world), actor_id)
    response = web.post("/api/pairing/codes")
    assert response.status_code == 201, response.text
    return response.json()


def claim(world, code, chat_user=CHAT, headers=None):  # noqa: F811
    return make_client(world).post("/api/pairing/claim", json={"code": code, "chat_user": chat_user},
                                   headers=headers or {})


def bearer(token, chat_user=CHAT):
    return {"Authorization": "Bearer %s" % token, pairing.CHAT_USER_HEADER: chat_user}


def paired(world, actor_id="PER-RM-BAY", chat_user=CHAT):  # noqa: F811
    body = claim(world, mint(world, actor_id)["code"], chat_user).json()
    return body["token"], body


def events(world, action):  # noqa: F811
    with world["owner"].connect() as conn:
        return conn.execute(text("""
            SELECT actor_id, subject_id, allowed, evidence FROM audit_event
             WHERE subject_type = 'pairing' AND action = :a ORDER BY seq"""), {"a": action}).all()


# --- minting -------------------------------------------------------------------------

def test_minting_a_code_needs_a_session(client):
    assert client.post("/api/pairing/codes").status_code == 401


def test_a_code_is_short_typable_and_short_lived(world):  # noqa: F811
    body = mint(world)
    code = body["code"]
    assert len(code) == 9 and code[4] == "-"
    assert all(ch in pairing.CODE_ALPHABET for ch in code.replace("-", ""))
    assert body["ttl_seconds"] == 600
    assert code in body["instructions"] and "Northbay Lease Desk" in body["instructions"]
    with world["owner"].connect() as conn:
        stored = conn.execute(text("SELECT code_hash FROM pairing")).scalar_one()
    assert code.replace("-", "") not in stored, "only the hash is stored"


# --- claiming ------------------------------------------------------------------------

def test_claiming_returns_a_token_that_acts_as_the_person(world):  # noqa: F811
    code = mint(world, "PER-RM-BAY")["code"]
    response = claim(world, code.lower().replace("-", " "))     # typed sloppily, still works
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token"].startswith("ldp_") and body["token_type"] == "Bearer"
    assert body["actor"]["id"] == "PER-RM-BAY" and body["chat_user"] == CHAT

    api = make_client(world)
    me = api.get("/api/auth/me", headers=bearer(body["token"]))
    assert me.status_code == 200 and me.json()["id"] == "PER-RM-BAY"
    mine = api.get("/api/pairing/me", headers=bearer(body["token"])).json()
    assert mine["pairing_id"] == body["pairing_id"] and mine["actor"]["region_id"] == "REG-BAY"

    [(actor, subject, allowed, evidence)] = events(world, "pair")
    assert (actor, subject, allowed) == ("PER-RM-BAY", str(body["pairing_id"]), True)
    assert evidence["chat_user"] == CHAT and evidence["channel"] == "asi1"


def test_a_code_works_once(world):  # noqa: F811
    code = mint(world)["code"]
    assert claim(world, code).status_code == 200
    second = claim(world, code, chat_user=OTHER_CHAT)
    assert second.status_code == 400 and second.json()["detail"] == pairing.INVALID_CODE


def test_an_expired_code_is_refused(world):  # noqa: F811
    code = mint(world)["code"]
    with world["owner"].begin() as conn:
        conn.execute(text("UPDATE pairing SET code_expires_at = now() - interval '1 second'"))
    response = claim(world, code)
    assert response.status_code == 400 and response.json()["detail"] == pairing.INVALID_CODE


def test_a_new_code_voids_the_unused_one(world):  # noqa: F811
    first = mint(world)["code"]
    second = mint(world)["code"]
    assert claim(world, first).status_code == 400
    assert claim(world, second).status_code == 200


@pytest.mark.parametrize("code", ["", "ABCD", "ABCD-EFG0", "'; DROP TABLE pairing; --", "ZZZZ-ZZZZ"])
def test_bad_codes_are_one_generic_refusal(world, code):  # noqa: F811
    mint(world)
    response = claim(world, code)
    assert response.status_code in (400, 422)
    if response.status_code == 400:
        assert response.json()["detail"] == pairing.INVALID_CODE


def test_a_deactivated_person_cannot_be_paired_or_stay_paired(world):  # noqa: F811
    token, _ = paired(world, "PER-RM-BAY")
    code = mint(world, "PER-CTRL")["code"]
    with world["owner"].begin() as conn:
        conn.execute(text("UPDATE actor SET active = false WHERE id IN ('PER-RM-BAY', 'PER-CTRL')"))
    assert make_client(world).get("/api/auth/me", headers=bearer(token)).status_code == 401
    assert claim(world, code, chat_user=OTHER_CHAT).status_code == 400


def test_the_client_key_is_required_when_configured(world, monkeypatch):  # noqa: F811
    monkeypatch.setenv("LEASEDESK_PAIRING_CLIENT_KEY", "front-desk-key")
    code = mint(world)["code"]
    assert claim(world, code).status_code == 401
    assert claim(world, code, headers={"X-Pairing-Client-Key": "wrong"}).status_code == 401
    assert claim(world, code, headers={"X-Pairing-Client-Key": "front-desk-key"}).status_code == 200


def test_pairing_again_from_the_same_chat_replaces_the_old_pairing(world):  # noqa: F811
    old, _ = paired(world, "PER-RM-BAY")
    new, _ = paired(world, "PER-CTRL")
    api = make_client(world)
    assert api.get("/api/auth/me", headers=bearer(old)).status_code == 401
    assert api.get("/api/auth/me", headers=bearer(new)).json()["id"] == "PER-CTRL"


# --- the token -----------------------------------------------------------------------

def test_the_token_is_bound_to_its_chat_user(world):  # noqa: F811
    token, _ = paired(world)
    api = make_client(world)
    assert api.get("/api/auth/me", headers=bearer(token, OTHER_CHAT)).status_code == 401
    assert api.get("/api/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 401


@pytest.mark.parametrize("header", ["Bearer nonsense", "Bearer ldp_" + "x" * 40, "Bearer "])
def test_an_unknown_bearer_token_is_401(client, header):
    assert client.get("/api/items", headers={"Authorization": header,
                                             pairing.CHAT_USER_HEADER: CHAT}).status_code == 401


def test_an_expired_token_is_401(world):  # noqa: F811
    token, _ = paired(world)
    with world["owner"].begin() as conn:
        conn.execute(text("UPDATE pairing SET token_expires_at = now() - interval '1 second'"))
    assert make_client(world).get("/api/auth/me", headers=bearer(token)).status_code == 401


def test_the_bearer_header_wins_over_a_cookie(world):  # noqa: F811
    token, _ = paired(world, "PER-RM-BAY")
    api = as_(make_client(world), "PER-CTRL")
    assert api.get("/api/auth/me").json()["id"] == "PER-CTRL"
    assert api.get("/api/auth/me", headers=bearer(token)).json()["id"] == "PER-RM-BAY"
    # A non-bearer Authorization header is not a pairing: the cookie still counts.
    assert api.get("/api/auth/me", headers={"Authorization": "Basic Zm9vOmJhcg=="}).json()["id"] \
        == "PER-CTRL"


@pytest.mark.parametrize("method,path", [
    ("post", "/api/pairing/codes"),
    ("get", "/api/pairing"),
    ("post", "/api/pairing/1/revoke"),
    ("post", "/api/batches/2026-01/release"),
    ("post", "/api/exceptions/exc_1/approve"),
    ("post", "/api/exceptions/exc_1/hold"),
    ("post", "/api/exceptions/exc_1/pay-as-billed"),
    ("get", "/api/summary"),
])
def test_a_paired_session_reaches_only_the_chat_routes(world, method, path):  # noqa: F811
    token, _ = paired(world, "PER-CTRL")
    response = getattr(make_client(world), method)(path, headers=bearer(token))
    assert response.status_code == 403, (path, response.text)
    assert "paired chat session" in response.json()["detail"]


def test_a_paired_session_reads_and_acts_through_can(world):  # noqa: F811
    bay = open_item(world, w.RENT)
    token, _ = paired(world, "PER-RM-BAY")
    api = make_client(world)
    assert [i["id"] for i in api.get("/api/items", headers=bearer(token)).json()["items"]] == [bay]
    assert api.get("/api/items/%d" % bay, headers=bearer(token)).status_code == 200


def no_model(**_):
    raise investigation_run.NoModel("No model in this test.")


def test_a_paired_session_may_run_an_investigation(world):  # noqa: F811
    """The investigation agent's one call: an SSE stream under the paired
    person's token. It proposes and never posts, so nothing changes state."""
    bay = open_item(world, w.RENT)
    token, _ = paired(world, "PER-RM-BAY")
    api = make_client(world)
    api.app.dependency_overrides[sse_delay] = lambda: 0.0
    api.app.dependency_overrides[investigation_runner] = lambda: no_model
    response = api.post("/api/exceptions/exc_%d/investigate" % bay, headers=bearer(token))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    stages = [json.loads(line[len("data:"):])["stage"] for line in response.text.splitlines()
              if line.startswith("data:")]
    assert stages and stages[-1] == "error", stages
    assert api.get("/api/items/%d" % bay, headers=bearer(token)).json()["item"]["state"] == "PROPOSED"


def test_an_investigation_still_needs_a_live_pairing(world):  # noqa: F811
    bay = open_item(world, w.RENT)
    token, _ = paired(world, "PER-RM-BAY")
    api = make_client(world)
    api.app.dependency_overrides[investigation_runner] = lambda: no_model
    assert api.post("/api/exceptions/exc_%d/investigate" % bay,
                    headers=bearer(token, OTHER_CHAT)).status_code == 401
    assert api.post("/api/exceptions/exc_%d/investigate" % bay).status_code == 401


# --- revoking ------------------------------------------------------------------------

def test_unpairing_from_chat_kills_the_token(world):  # noqa: F811
    token, body = paired(world)
    api = make_client(world)
    assert api.post("/api/pairing/me/revoke", headers=bearer(token)).status_code == 204
    assert api.get("/api/auth/me", headers=bearer(token)).status_code == 401
    [(actor, subject, _, evidence)] = events(world, "unpair")
    assert (actor, subject, evidence["via"]) == ("PER-RM-BAY", str(body["pairing_id"]), "chat")


def test_pairing_me_is_404_for_a_cookie_session(world):  # noqa: F811
    assert as_(make_client(world), "PER-RM-BAY").get("/api/pairing/me").status_code == 404


def test_the_web_app_lists_and_revokes_its_own_pairings(world):  # noqa: F811
    token, body = paired(world, "PER-RM-BAY")
    web = as_(make_client(world), "PER-RM-BAY")
    [listed] = web.get("/api/pairing").json()["pairings"]
    assert listed["id"] == body["pairing_id"] and listed["chat_user"] == CHAT

    other = as_(make_client(world), "PER-CTRL")
    assert other.post("/api/pairing/%d/revoke" % body["pairing_id"]).status_code == 404
    assert make_client(world).get("/api/auth/me", headers=bearer(token)).status_code == 200

    assert web.post("/api/pairing/%d/revoke" % body["pairing_id"]).status_code == 204
    assert make_client(world).get("/api/auth/me", headers=bearer(token)).status_code == 401
    assert web.get("/api/pairing").json()["pairings"] == []
    assert web.post("/api/pairing/%d/revoke" % body["pairing_id"]).status_code == 404
