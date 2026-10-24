"""Database fixtures for the platform tests.

Each session migrates a throwaway database from empty (proving the migration
works from nothing), runs against it, then drops it. When no Postgres is
reachable every test here is skipped, so the rest of the suite still runs
offline. Start one with `make up`, or point LEASEDESK_DB_* at any Postgres 16
whose owner can create databases and roles.
"""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.db.bootstrap import execute_raw
from app.db.engine import make_engine
from app.settings import DB_ROLES, get_settings

BACKEND = Path(__file__).resolve().parents[2]

# Truncation order does not matter with CASCADE; audit_event's TRUNCATE
# trigger is disabled around it because only tests may ever do this.
ALL_TABLES = (
    "source_document, raw_row, sync_cursor, entity, region, landlord, center, clinic, "
    "lease, landlord_charge, payment, lease_version, lease_term, agent_run, tool_call, "
    "work_item, question, policy, job, account, period, journal_entry, journal_line, "
    "outbox, audit_event, actor"
)


def _admin_engine():
    settings = get_settings()
    url = os.environ.get("LEASEDESK_TEST_ADMIN_URL") or settings.db_url("owner", "postgres")
    return create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 2})


@pytest.fixture(scope="session")
def database():
    admin = _admin_engine()
    try:
        with admin.connect():
            pass
    except OperationalError as exc:
        admin.dispose()
        pytest.skip("no Postgres reachable (%s); run `make up`" % str(exc).splitlines()[0])

    name = "leasedesk_test_%s" % uuid.uuid4().hex[:8]
    with admin.connect() as conn:
        conn.execute(text('CREATE DATABASE "%s"' % name))

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", get_settings().db_url("owner", name))
    command.upgrade(cfg, "head")
    try:
        yield name
    finally:
        with admin.connect() as conn:
            conn.execute(text('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % name))
        admin.dispose()


@pytest.fixture(scope="session")
def engines(database):
    made = {role: make_engine(role, database) for role in DB_ROLES + ("owner",)}
    yield made
    for eng in made.values():
        eng.dispose()


@pytest.fixture
def clean(engines):
    """Empty every table before the test. Only the owner can, and only by
    switching off audit_event's own protection for one statement."""
    with engines["owner"].begin() as conn:
        execute_raw(conn, "ALTER TABLE audit_event DISABLE TRIGGER audit_event_no_truncate;"
                          "TRUNCATE %s RESTART IDENTITY CASCADE;"
                          "ALTER TABLE audit_event ENABLE TRIGGER audit_event_no_truncate;"
                          % ALL_TABLES)
    return engines


@pytest.fixture
def books(clean):
    """The minimum the ledger needs: one entity, its chart, two periods
    (January open, December closed) and one clinic for line tagging."""
    from app.ledger.chart import install_chart

    with clean["owner"].begin() as conn:
        execute_raw(conn, """
            INSERT INTO entity VALUES ('ENT-CA', 'Northbay PT of California', 'CA');
            INSERT INTO period (entity_id, period, status) VALUES
                ('ENT-CA', '2026-01-01', 'open'), ('ENT-CA', '2025-12-01', 'closed');
        """)
        install_chart(conn, "ENT-CA")
    return clean
