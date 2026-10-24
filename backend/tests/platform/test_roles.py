"""The four database roles: exactly the privileges the architecture allows.

`test_grant_matrix_is_exact` is `make check-grants`. It reads what Postgres
actually granted and compares it to the specification below, so an extra
grant fails just as loudly as a missing one.
"""

from collections import defaultdict

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

RECORDS = {"source_document", "raw_row", "sync_cursor"}
GOLDEN = {"entity", "region", "landlord", "center", "clinic", "lease", "landlord_charge", "payment"}
RULEBOOK = {"lease_version", "lease_term"}
WORK = {"work_item", "question", "policy", "agent_run", "tool_call", "job"}
LEDGER = {"account", "period", "journal_entry", "journal_line"}
DISPUTES = {"dispute", "obligation"}                 # migration 0006
PAIRING = {"pairing"}       # migration 0007: chat pairing, API-written, hashes only
ALL = (RECORDS | GOLDEN | RULEBOOK | WORK | LEDGER | DISPUTES | PAIRING
       | {"outbox", "audit_event", "actor"})

# role -> privilege -> tables. Column-level UPDATEs are listed separately.
SPEC = {
    "lease_reader": {"SELECT": ALL - {"actor"}},     # actor: columns only, below
    "lease_agent": {
        "SELECT": RECORDS | GOLDEN | RULEBOOK | WORK | DISPUTES | {"account", "period",
                                                                   "audit_event"},
        "INSERT": {"source_document", "raw_row", "sync_cursor", "lease_version", "lease_term",
                   "work_item", "question", "policy", "agent_run", "tool_call", "job",
                   "audit_event", "dispute", "obligation"},
        "UPDATE": {"sync_cursor", "work_item", "question", "agent_run", "tool_call", "job",
                   "obligation"},
    },
    "lease_api": {
        "SELECT": ALL,
        "INSERT": {"work_item", "question", "job", "audit_event"} | PAIRING,
        "UPDATE": {"work_item", "question"} | PAIRING,
    },
    "lease_gateway": {
        "SELECT": ALL,
        "INSERT": GOLDEN | {"account", "period", "journal_entry", "journal_line", "outbox",
                            "audit_event", "actor"},
        "UPDATE": GOLDEN | {"actor"},
    },
}
COLUMN_UPDATES = {
    "lease_api": {
        "lease_version": {"confirmed_by", "confirmed_at"},
        "dispute": {"status", "credited_amount", "credits", "credit_memo_ref", "refusal_reason",
                    "updated_at"},
    },
    "lease_gateway": {
        "dispute": {"status", "letter_outbox_id", "sent_at", "receivable_entry_id",
                    "writeoff_entry_id", "updated_at"},
        "period": {"status", "closed_at", "closed_by"},
        "outbox": {"status", "attempts", "sent_at"},
        "work_item": {"state", "updated_at", "last_event_seq"},
    },
}


def _table_grants(conn):
    rows = conn.execute(text("""
        SELECT grantee, privilege_type, table_name
          FROM information_schema.role_table_grants
         WHERE table_schema = 'public' AND grantee LIKE 'lease\\_%'
    """)).all()
    got = defaultdict(lambda: defaultdict(set))
    for grantee, privilege, table in rows:
        got[grantee][privilege].add(table)
    return got


def _column_updates(conn, role):
    rows = conn.execute(text("""
        SELECT table_name, column_name FROM information_schema.column_privileges
         WHERE table_schema = 'public' AND grantee = :role AND privilege_type = 'UPDATE'
    """), {"role": role}).all()
    got = defaultdict(set)
    for table, column in rows:
        got[table].add(column)
    return got


def test_grant_matrix_is_exact(engines):
    with engines["owner"].connect() as conn:
        got = _table_grants(conn)
        for role, privileges in SPEC.items():
            assert dict(got[role]) == privileges, role
        for role, tables in COLUMN_UPDATES.items():
            columns = _column_updates(conn, role)
            for table, expected in tables.items():
                assert columns[table] == expected, (role, table)


def test_only_api_and_gateway_can_read_password_hashes(engines):
    with engines["owner"].connect() as conn:
        rows = conn.execute(text("""
            SELECT grantee FROM information_schema.column_privileges
             WHERE table_name = 'actor' AND column_name = 'password_hash'
               AND privilege_type = 'SELECT' AND grantee LIKE 'lease\\_%'""")).scalars()
        assert set(rows) == {"lease_api", "lease_gateway"}


def test_no_role_may_delete_or_truncate_anything(engines):
    with engines["owner"].connect() as conn:
        got = _table_grants(conn)
    for role in SPEC:
        assert not got[role]["DELETE"], role
        assert not got[role]["TRUNCATE"], role


def test_only_the_gateway_may_insert_into_the_ledger_or_outbox(engines):
    with engines["owner"].connect() as conn:
        got = _table_grants(conn)
    for table in ("journal_entry", "journal_line", "outbox"):
        writers = {role for role in SPEC if table in got[role]["INSERT"]}
        assert writers == {"lease_gateway"}, table


# --- the A5 gate, as the demo shows it -------------------------------------

def _denied(eng, sql, params=None):
    with eng.connect() as conn:
        with pytest.raises(ProgrammingError) as info:
            conn.execute(text(sql), params or {})
        conn.rollback()
    return str(info.value.orig)


def test_agent_insert_into_journal_entry_is_permission_denied(engines):
    """The one-statement demo beat: the agent process physically cannot write
    to the ledger, even with raw SQL that bypasses every line of Python."""
    message = _denied(engines["lease_agent"], """
        INSERT INTO journal_entry (entity_id, date, period, memo, idempotency_key)
        VALUES ('ENT-CA', '2026-01-31', '2026-01-01', 'agent tries to post', 'k1')""")
    assert "permission denied for table journal_entry" in message


@pytest.mark.parametrize("sql", [
    "INSERT INTO journal_line (journal_entry_id, account_id, debit) VALUES (1, 1, 1)",
    "INSERT INTO outbox (kind, payload, idempotency_key) VALUES ('ap_batch', '{}', 'k')",
    "UPDATE landlord_charge SET amount = 0",
    "INSERT INTO entity VALUES ('X', 'x', 'CA')",
    "UPDATE period SET status = 'open'",
])
def test_agent_cannot_write_ledger_outbox_or_golden_records(engines, sql):
    assert "permission denied" in _denied(engines["lease_agent"], sql)


def test_api_cannot_post_to_the_ledger(engines):
    message = _denied(engines["lease_api"],
                      "INSERT INTO journal_line (journal_entry_id, account_id, debit) VALUES (1, 1, 1)")
    assert "permission denied" in message


def test_reader_cannot_write_anything(engines):
    message = _denied(engines["lease_reader"], """
        INSERT INTO audit_event (actor_id, action, subject_type, subject_id, allowed)
        VALUES ('auditor', 'approve', 'work_item', '1', true)""")
    assert "permission denied" in message


def test_each_role_logs_in_as_itself(engines):
    for role in ("lease_agent", "lease_gateway", "lease_api", "lease_reader"):
        with engines[role].connect() as conn:
            assert conn.execute(text("SELECT current_user")).scalar_one() == role


def test_reapplying_roles_is_idempotent_and_keeps_the_matrix(engines):
    """roles.sql is desired state: running it again must change nothing."""
    from app.db.bootstrap import apply_roles

    with engines["owner"].begin() as conn:
        apply_roles(conn)
    test_grant_matrix_is_exact(engines)


def test_everyone_can_verify_the_chain(engines):
    for role in ("lease_agent", "lease_gateway", "lease_api", "lease_reader"):
        with engines[role].connect() as conn:
            try:
                conn.execute(text("SELECT * FROM audit_verify_chain()")).all()
            except DBAPIError as exc:  # pragma: no cover - the assertion message is the point
                pytest.fail("%s cannot verify the chain: %s" % (role, exc.orig))


def test_only_agents_may_draw_work_item_and_question_ids(engines):
    """transitions.py draws an id before the row exists, so the creating
    event can carry it. Only agents create items and ask questions."""
    with engines["owner"].connect() as conn:
        rows = conn.execute(text("""
            SELECT r.rolname, s.relname FROM pg_class s, pg_roles r
             WHERE s.relkind = 'S' AND s.relname IN ('work_item_id_seq', 'question_id_seq')
               AND r.rolname LIKE 'lease\\_%' AND has_sequence_privilege(r.oid, s.oid, 'USAGE')
        """)).all()
    assert {tuple(row) for row in rows} == {("lease_agent", "work_item_id_seq"),
                                             ("lease_agent", "question_id_seq")}
