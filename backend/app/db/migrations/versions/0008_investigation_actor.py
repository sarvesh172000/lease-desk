"""Provision the investigation agent for databases upgraded without reseeding.

Revision ID: 0008_investigation_actor
Revises: 0007_pairing
"""

from alembic import op

from app.db.bootstrap import execute_raw

revision = "0008_investigation_actor"
down_revision = "0007_pairing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_raw(op.get_bind(), """
        INSERT INTO actor (id, name, role, email, region_id, entity_id, active)
        VALUES ('agent:investigation', 'Investigation agent', 'agent', NULL, NULL, NULL, true)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            role = EXCLUDED.role,
            email = EXCLUDED.email,
            region_id = EXCLUDED.region_id,
            entity_id = EXCLUDED.entity_id,
            active = EXCLUDED.active;
    """)


def downgrade() -> None:
    # Golden-data seeding may have created this actor before the migration, and
    # audit history may already name it. Retaining the identity is lossless and
    # remains valid under 0007, while deleting it cannot be reversed safely.
    pass
