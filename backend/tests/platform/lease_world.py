"""Drafting and confirming the seeded leases, for tests that need checked charges.

The checker only reads confirmed lease versions, so a test that wants
January's twelve CHARGE_CHECK items first has the abstraction step draft the
five versions (as lease_agent) and the Bay Area manager confirm them (as
lease_api, through transition()), exactly as the product does.
"""

from datetime import date
from pathlib import Path

from app.jobs import lease_versions
from app.jobs.lease_versions import draft_versions
from app.work.confirm_leases import confirm_all
from app.work.roles import load_actor

ENTITY = "ENT-CA"
RM_BAY = "PER-RM-BAY"
JAN = date(2026, 1, 1)


def use_documents(monkeypatch, generated) -> None:
    """Point the abstraction job (run by the worker) at the generated store."""
    monkeypatch.setattr(lease_versions, "data_dir", lambda: Path(generated))


def draft(engines, generated, entity=ENTITY):
    with engines["lease_agent"].begin() as conn:
        return draft_versions(conn, entity, root=Path(generated), history_until=JAN)


def confirm(engines, actor_id=RM_BAY, entity=ENTITY):
    with engines["lease_api"].begin() as conn:
        return confirm_all(conn, load_actor(conn, actor_id), entity)


def draft_and_confirm(engines, generated, entity=ENTITY):
    draft(engines, generated, entity)
    return confirm(engines, entity=entity)
