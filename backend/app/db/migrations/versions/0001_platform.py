"""Platform: schema, integrity triggers and the four database roles.

Revision ID: 0001_platform
Revises:
"""

from alembic import op

from app.db.bootstrap import SQL_DIR, apply_roles, apply_sql_file

revision = "0001_platform"
down_revision = None
branch_labels = None
depends_on = None

TABLES = [
    # Reverse dependency order, for downgrade.
    "audit_event", "outbox", "journal_line", "journal_entry", "period", "account",
    "job", "policy", "question", "work_item", "tool_call", "lease_term",
    "agent_run", "lease_version", "payment", "landlord_charge", "lease", "clinic",
    "center", "landlord", "region", "entity", "sync_cursor", "raw_row",
    "source_document",
]

FUNCTIONS = [
    "audit_event_reject_change()", "audit_event_chain()", "audit_verify_chain()",
    "audit_hash(text, audit_event)", "audit_canonical(audit_event)",
    "journal_line_balanced()", "journal_entry_balanced()", "journal_check_balanced(bigint)",
    "journal_entry_period_open()", "journal_line_period_open()",
    "period_check_open(text, date)",
]


def upgrade() -> None:
    conn = op.get_bind()
    apply_sql_file(conn, SQL_DIR / "001_schema.sql")
    apply_sql_file(conn, SQL_DIR / "002_integrity.sql")
    apply_roles(conn)


def downgrade() -> None:
    # Roles are cluster-wide and may serve other databases, so they stay.
    conn = op.get_bind()
    # Functions first: two take audit_event as an argument type, and that type
    # disappears with the table.
    for function in FUNCTIONS:
        conn.exec_driver_sql("DROP FUNCTION IF EXISTS %s CASCADE" % function)
    for table in TABLES:
        conn.exec_driver_sql("DROP TABLE IF EXISTS %s CASCADE" % table)
