"""Auth pieces that need no database: hashes and the signed cookie token."""

import time

import itsdangerous.timed
import pytest
from app.auth import passwords
from app.auth.deps import require_role
from app.auth.sessions import MAX_AGE_SECONDS, issue_token, read_token
from app.settings import DEV_SESSION_SECRET, get_settings
from argon2 import PasswordHasher

SECRET = "unit-test-secret"


# ------------------------------------------------------------- passwords

def test_hash_verifies_and_is_salted():
    a, b = passwords.hash_password("demo"), passwords.hash_password("demo")
    assert a != b and a.startswith("$argon2id$")
    assert passwords.verify_password(a, "demo")


def test_wrong_password_fails():
    assert not passwords.verify_password(passwords.hash_password("demo"), "Demo")


@pytest.mark.parametrize("stored", [None, "", "not-a-hash", "$2b$12$bcryptlookingvalue",
                                    "$argon2id$v=19$m=65536,t=3,p=4$garbage"])
def test_null_or_corrupt_hash_is_false_not_an_error(stored):
    assert passwords.verify_password(stored, "demo") is False


def test_weaker_parameters_need_a_rehash():
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash("demo")
    assert passwords.verify_password(weak, "demo")        # still verifies
    assert passwords.needs_rehash(weak)
    assert not passwords.needs_rehash(passwords.hash_password("demo"))
    assert passwords.needs_rehash("garbage")


def test_dummy_hash_is_stable_and_matches_nothing_obvious():
    assert passwords.dummy_hash() == passwords.dummy_hash()
    for guess in ("", "demo", "password"):
        assert not passwords.verify_password(passwords.dummy_hash(), guess or " ")


def test_cli_rejects_unknown_commands(capsys):
    assert passwords.main([]) == 2
    assert passwords.main(["set-everyones-password"]) == 2
    assert "usage" in capsys.readouterr().err


# ---------------------------------------------------------------- tokens

def test_token_round_trips_the_actor_id_only():
    token = issue_token(SECRET, "PER-AP")
    assert read_token(SECRET, token) == "PER-AP"
    assert "PER-CTRL" not in token


@pytest.mark.parametrize("token", [None, "", "garbage", "PER-AP", "a.b.c"])
def test_malformed_tokens_are_rejected(token):
    assert read_token(SECRET, token) is None


def test_tampered_token_is_rejected():
    token = issue_token(SECRET, "PER-AP")
    rest = token.split(".", 1)[1]
    forged = issue_token(SECRET, "PER-CTRL").split(".", 1)[0] + "." + rest
    assert read_token(SECRET, forged) is None
    flipped = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert read_token(SECRET, flipped) is None


def test_token_from_another_secret_is_rejected():
    assert read_token(SECRET, issue_token("someone-elses-secret", "PER-CTRL")) is None


def test_token_expires_after_twelve_hours(monkeypatch):
    token = issue_token(SECRET, "PER-AP")
    later = int(time.time()) + MAX_AGE_SECONDS + 60
    monkeypatch.setattr(itsdangerous.timed.TimestampSigner, "get_timestamp", lambda self: later)
    assert read_token(SECRET, token) is None


def test_token_still_valid_just_before_expiry(monkeypatch):
    token = issue_token(SECRET, "PER-AP")
    later = int(time.time()) + MAX_AGE_SECONDS - 60
    monkeypatch.setattr(itsdangerous.timed.TimestampSigner, "get_timestamp", lambda self: later)
    assert read_token(SECRET, token) == "PER-AP"


def test_require_role_needs_a_role():
    with pytest.raises(ValueError):
        require_role()


# -------------------------------------------------------------- settings

def _fresh_settings(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        return get_settings()
    finally:
        get_settings.cache_clear()


def test_default_secret_warns_loudly_when_demo_mode_is_off(monkeypatch):
    monkeypatch.delenv("LEASEDESK_SESSION_SECRET", raising=False)
    with pytest.warns(RuntimeWarning, match="LEASEDESK_SESSION_SECRET"):
        settings = _fresh_settings(monkeypatch, LEASEDESK_DEMO_MODE="0")
    assert settings.session_secret == DEV_SESSION_SECRET


def test_no_warning_with_a_real_secret_or_in_demo_mode(monkeypatch, recwarn):
    monkeypatch.delenv("LEASEDESK_SESSION_SECRET", raising=False)
    _fresh_settings(monkeypatch, LEASEDESK_DEMO_MODE="1")
    settings = _fresh_settings(monkeypatch, LEASEDESK_DEMO_MODE="0",
                               LEASEDESK_SESSION_SECRET="a-long-random-value")
    assert settings.session_secret == "a-long-random-value"
    assert not [w for w in recwarn if issubclass(w.category, RuntimeWarning)]
