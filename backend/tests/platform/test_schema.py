"""The migrated schema: frozen names, models.py in sync, constraints that
make illegal states unstorable."""

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import models

FROZEN_TABLES = {
    "source_document", "raw_row", "sync_cursor",
    "entity", "region", "clinic", "center", "landlord", "lease", "landlord_charge", "payment",
    "lease_version", "lease_term",
    "work_item", "question", "policy", "agent_run", "tool_call", "job",
    "account", "journal_entry", "journal_line", "period",
    "outbox", "audit_event",
}
ADDED_TABLES = {"actor",                  # not in the frozen list; added for can() and login
                "dispute", "obligation",  # Phase 2 groups 11 and 12 (migration 0006)
                "pairing"}                # migration 0007: ASI:One chat pairing (PHASE_3 group 9)


def test_every_frozen_table_exists_and_nothing_else(engines):
    tables = set(inspect(engines["owner"]).get_table_names()) - {"alembic_version"}
    assert tables == FROZEN_TABLES | ADDED_TABLES


def test_models_match_the_migrated_schema(engines):
    """models.py mirrors 001_schema.sql. Drift in either direction fails."""
    inspector = inspect(engines["owner"])
    assert set(models.metadata.tables) == FROZEN_TABLES | ADDED_TABLES
    for name, table in models.metadata.tables.items():
        db_columns = {c["name"] for c in inspector.get_columns(name)}
        assert {c.name for c in table.columns} == db_columns, name


def test_work_states_are_the_frozen_eight(engines):
    with engines["owner"].connect() as conn:
        check = conn.execute(text("""
            SELECT pg_get_constraintdef(oid) FROM pg_constraint
             WHERE conrelid = 'work_item'::regclass AND contype = 'c'
               AND pg_get_constraintdef(oid) LIKE '%state%'""")).scalar_one()
    for state in models.WORK_STATES:
        assert "'%s'" % state in check
    assert len(models.WORK_STATES) == 8


def test_an_unknown_work_state_cannot_be_stored(clean):
    with pytest.raises(IntegrityError):
        with clean["lease_agent"].begin() as conn:
            conn.execute(text("""
                INSERT INTO work_item (kind, state, subject_type, subject_id, title)
                VALUES ('CHARGE_CHECK', 'MAYBE', 'landlord_charge', 'x', 't')"""))


def test_the_same_work_item_cannot_be_created_twice(clean):
    """Running a month twice must add no work items."""
    insert = text("""INSERT INTO work_item (kind, subject_type, subject_id, title)
                     VALUES ('CHARGE_CHECK', 'landlord_charge', 'abc', 't')""")
    with clean["lease_agent"].begin() as conn:
        conn.execute(insert)
    with pytest.raises(IntegrityError):
        with clean["lease_agent"].begin() as conn:
            conn.execute(insert)


def test_money_is_exact_decimal_not_float(engines):
    columns = {c["name"]: c for c in inspect(engines["owner"]).get_columns("journal_line")}
    assert str(columns["debit"]["type"]) == "NUMERIC(14, 2)"


def test_migration_downgrades_and_upgrades_cleanly(database):
    """A migration that cannot be undone and redone is one nobody can fix."""
    from alembic import command
    from alembic.config import Config

    from app.settings import get_settings

    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", get_settings().db_url("owner", database))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_actor_roles_include_system_for_the_gateway(engines):
    """Migration 0003: `post` belongs to role 'system', held by system:gateway."""
    with engines["owner"].connect() as conn:
        check = conn.execute(text("""
            SELECT pg_get_constraintdef(oid) FROM pg_constraint
             WHERE conname = 'actor_role_check'""")).scalar_one()
    for role in models.ACTOR_ROLES:
        assert "'%s'" % role in check


def test_journal_entry_work_item_key_is_deferrable_for_replay(engines):
    with engines["owner"].connect() as conn:
        deferrable = conn.execute(text("""
            SELECT condeferrable FROM pg_constraint
             WHERE conname = 'journal_entry_work_item_id_fkey'""")).scalar_one()
    assert deferrable


def test_policy_status_is_guarded_by_triggers(engines):
    """Migration 0005: a policy is born 'proposed' and its status follows its
    POLICY work item; agent:policy exists to propose them."""
    with engines["owner"].connect() as conn:
        triggers = set(conn.execute(text("""
            SELECT tgname FROM pg_trigger WHERE NOT tgisinternal
               AND tgrelid IN ('policy'::regclass, 'work_item'::regclass)""")).scalars())
        agent = conn.execute(text(
            "SELECT role FROM actor WHERE id = 'agent:policy'")).scalar()
    assert {"policy_insert_proposed", "work_item_policy_status"} <= triggers
    assert agent == "agent"
