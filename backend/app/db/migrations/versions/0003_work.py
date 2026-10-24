"""Work layer: the gateway actor, and a deferrable journal_entry -> work_item
key so replay can rebuild work items in place.

Revision ID: 0003_work
Revises: 0002_actor
"""

from alembic import op

from app.db.bootstrap import SQL_DIR, apply_roles, apply_sql_file, execute_raw

revision = "0003_work"
down_revision = "0002_actor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    apply_sql_file(conn, SQL_DIR / "004_work.sql")
    apply_roles(conn)


def downgrade() -> None:
    # The gateway's events stay in audit_event (nothing deletes history); only
    # the actor row and the role it needed go.
    execute_raw(op.get_bind(), """
        ALTER TABLE journal_entry ALTER CONSTRAINT journal_entry_work_item_id_fkey
            NOT DEFERRABLE;
        DELETE FROM actor WHERE role = 'system';
        ALTER TABLE actor DROP CONSTRAINT actor_role_check;
        ALTER TABLE actor ADD CONSTRAINT actor_role_check
            CHECK (role IN ('regional_manager', 'ap_clerk', 'controller', 'auditor', 'agent'));
    """)
