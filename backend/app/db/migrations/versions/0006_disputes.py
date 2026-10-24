"""Disputes and obligations: the dispute register, the lease's critical
dates, and the two agents that keep them.

Revision ID: 0006_disputes
Revises: 0004_safety
"""

from alembic import op

from app.db.bootstrap import SQL_DIR, apply_roles, apply_sql_file, execute_raw

revision = "0006_disputes"
down_revision = "0004_safety"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    apply_sql_file(conn, SQL_DIR / "007_disputes.sql")
    apply_roles(conn)


def downgrade() -> None:
    # The agents' events stay in audit_event (nothing deletes history).
    execute_raw(op.get_bind(), """
        DROP TABLE obligation;
        DROP TABLE dispute;
        DELETE FROM actor WHERE id IN ('agent:disputes', 'agent:obligations');
    """)
