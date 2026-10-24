"""audit_event: append-only and hash-chained, enforced by the database.

The acceptance check from Phase 1: edit a row as superuser with the triggers
switched off, and verification names the broken sequence number.
"""

import hashlib
import json
import threading

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.bootstrap import execute_raw

GENESIS = "0" * 64

INSERT = text("""
    INSERT INTO audit_event (actor_id, action, subject_type, subject_id, allowed, reason, diff)
    VALUES (:actor, :action, 'work_item', :subject, :allowed, :reason, CAST(:diff AS jsonb))
    RETURNING seq, prev_hash, hash
""")


def append(eng, actor="agent:checker", action="propose", subject="1", allowed=True,
           reason=None, diff=None):
    with eng.begin() as conn:
        return conn.execute(INSERT, dict(actor=actor, action=action, subject=subject,
                                         allowed=allowed, reason=reason,
                                         diff=json.dumps(diff or {}))).one()


def broken(eng):
    with eng.connect() as conn:
        return conn.execute(text("SELECT broken_seq, problem FROM audit_verify_chain()")).first()


def test_first_event_chains_from_genesis(clean):
    row = append(clean["lease_agent"])
    assert row.prev_hash == GENESIS
    assert len(row.hash) == 64 and row.hash != GENESIS


def test_each_event_links_to_the_one_before(clean):
    rows = [append(clean["lease_agent"], subject=str(i)) for i in range(5)]
    for previous, current in zip(rows, rows[1:]):
        assert current.prev_hash == previous.hash
        assert current.seq > previous.seq
    assert broken(clean["lease_reader"]) is None


def test_hash_is_sha256_of_prev_hash_and_the_canonical_row(clean):
    """Recompute one hash in Python from the canonical form, so verification
    does not depend on trusting the database's own function."""
    row = append(clean["lease_agent"], reason="matches the lease", diff={"state": "PROPOSED"})
    with clean["owner"].connect() as conn:
        canonical = conn.execute(text(
            "SELECT audit_canonical(e) FROM audit_event e WHERE seq = :s"), {"s": row.seq}).scalar_one()
    assert hashlib.sha256((row.prev_hash + canonical).encode()).hexdigest() == row.hash
    assert json.loads(canonical)["reason"] == "matches the lease"


def test_client_supplied_hashes_are_overwritten(clean):
    with clean["lease_agent"].begin() as conn:
        row = conn.execute(text("""
            INSERT INTO audit_event (actor_id, action, subject_type, subject_id, allowed,
                                     prev_hash, hash)
            VALUES ('agent', 'propose', 'work_item', '1', true, :forged, :forged)
            RETURNING prev_hash, hash"""), {"forged": "f" * 64}).one()
    assert row.prev_hash == GENESIS
    assert row.hash != "f" * 64


def test_denied_attempts_are_recorded_like_any_other_event(clean):
    append(clean["lease_api"], actor="user:dana", action="approve", allowed=False,
           reason="separation of duties: answered this item")
    with clean["lease_reader"].connect() as conn:
        assert conn.execute(text("SELECT allowed FROM audit_event")).scalar_one() is False


@pytest.mark.parametrize("role", ["lease_agent", "lease_gateway", "lease_api", "owner"])
@pytest.mark.parametrize("sql", [
    "UPDATE audit_event SET reason = 'rewritten'",
    "DELETE FROM audit_event",
    "TRUNCATE audit_event",
])
def test_nobody_can_change_history_not_even_the_owner(clean, role, sql):
    append(clean["lease_agent"])
    with clean[role].connect() as conn:
        with pytest.raises(DBAPIError) as info:
            conn.execute(text(sql))
        conn.rollback()
    message = str(info.value.orig)
    assert "append-only" in message or "permission denied" in message


def test_tampering_with_triggers_disabled_is_named_by_seq(clean):
    rows = [append(clean["lease_agent"], subject=str(i)) for i in range(4)]
    target = rows[2].seq
    with clean["owner"].begin() as conn:
        execute_raw(conn, "ALTER TABLE audit_event DISABLE TRIGGER USER;"
                          "UPDATE audit_event SET reason = 'quietly changed' WHERE seq = %d;"
                          "ALTER TABLE audit_event ENABLE TRIGGER USER;" % target)
    seq, problem = broken(clean["lease_reader"])
    assert seq == target
    assert "contents" in problem


def test_deleting_an_event_breaks_the_link_after_it(clean):
    rows = [append(clean["lease_agent"], subject=str(i)) for i in range(4)]
    with clean["owner"].begin() as conn:
        execute_raw(conn, "ALTER TABLE audit_event DISABLE TRIGGER USER;"
                          "DELETE FROM audit_event WHERE seq = %d;"
                          "ALTER TABLE audit_event ENABLE TRIGGER USER;" % rows[1].seq)
    seq, problem = broken(clean["lease_reader"])
    assert seq == rows[2].seq
    assert "prev_hash" in problem


def test_writes_outside_read_committed_are_refused(clean):
    """A snapshot taken at transaction start could miss a concurrent event and
    fork the chain, so the trigger refuses rather than risk it."""
    with clean["lease_agent"].connect() as conn:
        conn = conn.execution_options(isolation_level="REPEATABLE READ")
        with pytest.raises(DBAPIError, match="READ COMMITTED"):
            conn.execute(INSERT, dict(actor="a", action="x", subject="1", allowed=True,
                                      reason=None, diff="{}"))


def test_concurrent_writers_keep_one_unbroken_chain(clean):
    errors = []

    def writer(n):
        try:
            for i in range(10):
                append(clean["lease_agent"], subject="%d-%d" % (n, i))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    with clean["lease_reader"].connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_event")).scalar_one() == 60
    assert broken(clean["lease_reader"]) is None
