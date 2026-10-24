"""Chat pairing: one-time codes that link an ASI:One user to an actor, and the
scoped bearer token the Fetch.ai front desk gets for it (PHASE_3.md group 9).

Revision ID: 0007_pairing
Revises: 0003_work
"""

from alembic import op

from app.db.bootstrap import SQL_DIR, apply_roles, apply_sql_file, execute_raw

revision = "0007_pairing"
down_revision = "0003_work"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    apply_sql_file(conn, SQL_DIR / "008_pairing.sql")
    apply_roles(conn)


def downgrade() -> None:
    # The pair / unpair events stay in audit_event; only the live pairings go.
    execute_raw(op.get_bind(), "DROP TABLE IF EXISTS pairing")
