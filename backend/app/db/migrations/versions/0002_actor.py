"""Actors: the people and agents who act, with role and scope.

Revision ID: 0002_actor
Revises: 0001_platform
"""

from alembic import op

from app.db.bootstrap import SQL_DIR, apply_roles, apply_sql_file

revision = "0002_actor"
down_revision = "0001_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    apply_sql_file(conn, SQL_DIR / "003_actor.sql")
    apply_roles(conn)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS actor CASCADE")
