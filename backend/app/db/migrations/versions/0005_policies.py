"""Policy engine: the policy learner actor, policies born 'proposed', and a
policy's status following its POLICY work item (006_policies.sql).

Revision ID: 0005_policies
Revises: 0003_work
"""

from alembic import op

from app.db.bootstrap import SQL_DIR, apply_roles, apply_sql_file, execute_raw

revision = "0005_policies"
down_revision = "0003_work"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    apply_sql_file(conn, SQL_DIR / "006_policies.sql")
    apply_roles(conn)


def downgrade() -> None:
    # agent:policy's events stay in audit_event; history is never deleted.
    execute_raw(op.get_bind(), """
        DROP TRIGGER IF EXISTS work_item_policy_status ON work_item;
        DROP FUNCTION IF EXISTS policy_follow_work_item();
        DROP TRIGGER IF EXISTS policy_insert_proposed ON policy;
        DROP FUNCTION IF EXISTS policy_born_proposed();
        REVOKE INSERT ON policy FROM lease_agent;
        DELETE FROM actor WHERE id = 'agent:policy'
           AND NOT EXISTS (SELECT 1 FROM audit_event WHERE actor_id = 'agent:policy');
    """)
