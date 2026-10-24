"""Safety: decisions belong to people and the gateway (B10, defense in depth).

Triggers that stop lease_agent recording or projecting a decision, and
lease_api posting, even with can() bypassed. See db/sql/005_safety.sql.

Revision ID: 0004_safety
Revises: 0003_work
"""

from alembic import op

from app.db.bootstrap import SQL_DIR, apply_sql_file, execute_raw

revision = "0004_safety"
down_revision = "0003_work"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No grant changes, so roles.sql is not re-applied: ALTER ROLE touches
    # cluster-wide catalog rows, and every extra one is a chance to collide
    # with another database's migration on the same server.
    apply_sql_file(op.get_bind(), SQL_DIR / "005_safety.sql")


def downgrade() -> None:
    execute_raw(op.get_bind(), """
        DROP TRIGGER IF EXISTS audit_event_guard ON audit_event;
        DROP TRIGGER IF EXISTS work_item_guard ON work_item;
        DROP TRIGGER IF EXISTS lease_version_guard ON lease_version;
        DROP FUNCTION IF EXISTS audit_event_guard();
        DROP FUNCTION IF EXISTS work_item_guard();
        DROP FUNCTION IF EXISTS lease_version_guard();
    """)
