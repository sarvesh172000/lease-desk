"""A small company for the work-layer tests: two entities, two regions, and
one actor of every kind, each connecting as the database role its process
would really use. Driving every action through its real role means these
tests also prove the grants in roles.sql are enough, and no more than enough.
"""

import pytest
from sqlalchemy import text

from app.db.bootstrap import execute_raw
from app.work.roles import Actor, ensure_gateway_actor

ACTORS = {
    "agent:checker": Actor("agent:checker", "agent", None, None),
    "agent:abstraction": Actor("agent:abstraction", "agent", None, None),
    "RM-BAY": Actor("RM-BAY", "regional_manager", "REG-BAY", None),
    "RM-DESERT": Actor("RM-DESERT", "regional_manager", "REG-DESERT", None),
    "CTRL": Actor("CTRL", "controller", None, None),
    "CTRL-NV": Actor("CTRL-NV", "controller", None, "ENT-NV"),
    "AP": Actor("AP", "ap_clerk", None, None),
    "AUD": Actor("AUD", "auditor", None, None),
    "system:gateway": Actor("system:gateway", "system", None, None),
}

# Which process, and so which database role, each kind of actor acts through.
DB_ROLE = {"agent": "lease_agent", "system": "lease_gateway"}


def engine_for(engines, actor: Actor):
    return engines[DB_ROLE.get(actor.role, "lease_api")]


def seed_world(conn) -> None:
    execute_raw(conn, """
        INSERT INTO entity VALUES ('ENT-CA', 'Northbay PT of California', 'CA'),
                                  ('ENT-NV', 'Northbay PT of Nevada', 'NV');
        INSERT INTO region (id, name) VALUES ('REG-BAY', 'Bay Area'), ('REG-DESERT', 'Desert');
    """)
    conn.execute(text("""
        INSERT INTO actor (id, name, role, region_id, entity_id)
        VALUES (:id, :id, :role, :region_id, :entity_id)
    """), [vars(a) for a in ACTORS.values() if a.role != "system"])
    ensure_gateway_actor(conn)


@pytest.fixture(name="world")
def world_fixture(clean):
    with clean["owner"].begin() as conn:
        seed_world(conn)
    return clean


def bay_item(**overrides):
    fields = dict(kind="CHARGE_CHECK", subject_type="landlord_charge", subject_id="chg-1",
                  title="January base rent, Suite 100", entity_id="ENT-CA", region_id="REG-BAY",
                  period="2026-01-01", amount="12500.00", evidence={"invoice": "inv-1", "page": 1})
    fields.update(overrides)
    return fields
