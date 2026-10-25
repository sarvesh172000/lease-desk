"""Upgrade and API regressions for investigation-backed modifications."""

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.api import items
from app.settings import get_settings
from app.work import gateway, modifications

BACKEND = Path(__file__).resolve().parents[2]
REVISION = "0008_investigation_actor"
ACTOR_ID = "agent:investigation"


def _config(database: str | None = None) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    if database is not None:
        cfg.set_main_option("sqlalchemy.url", get_settings().db_url("owner", database))
    return cfg


def _actor(owner):
    with owner.connect() as conn:
        return tuple(conn.execute(text("""
            SELECT name, role, email, region_id, entity_id, password_hash, active
              FROM actor WHERE id = :id
        """), {"id": ACTOR_ID}).one())


def _gateway_engine(kind: str, evidence: dict):
    engine = MagicMock()
    conn = engine.begin.return_value.__enter__.return_value
    kind_result = MagicMock()
    kind_result.scalar_one.return_value = kind
    event_result = MagicMock()
    event_result.scalar.return_value = evidence
    conn.execute.side_effect = [kind_result, event_result]
    return engine


def test_investigation_actor_migration_is_the_only_head():
    assert ScriptDirectory.from_config(_config()).get_heads() == [REVISION]


def test_investigation_actor_upgrade_is_idempotent_and_downgrade_is_lossless(database):
    cfg = _config(database)
    owner = create_engine(get_settings().db_url("owner", database))
    canonical = ("Investigation agent", "agent", None, None, None, None, True)
    upgraded = ("Investigation agent", "agent", None, None, None, "keep-this-hash", True)

    try:
        command.downgrade(cfg, "0007_pairing")
        with owner.begin() as conn:
            conn.execute(text("DELETE FROM pairing WHERE actor_id = :id"), {"id": ACTOR_ID})
            conn.execute(text("DELETE FROM actor WHERE id = :id"), {"id": ACTOR_ID})
        command.upgrade(cfg, "head")
        assert _actor(owner) == canonical

        command.downgrade(cfg, "0007_pairing")
        assert _actor(owner) == canonical
        with owner.begin() as conn:
            conn.execute(text("""
                UPDATE actor
                   SET name = 'Stale investigation actor', email = 'stale@example.test',
                       password_hash = 'keep-this-hash', active = false
                 WHERE id = :id
            """), {"id": ACTOR_ID})
        command.upgrade(cfg, "head")
        assert _actor(owner) == upgraded
    finally:
        try:
            command.upgrade(cfg, "head")
        finally:
            owner.dispose()


def test_successful_modification_post_has_no_accounts_payable_amount(monkeypatch):
    engine = _gateway_engine(modifications.MODIFICATION_KIND, {})
    monkeypatch.setattr(gateway, "post_approved_modification", lambda conn, item_id: 41)

    def reject_journal_total(_engine, _entry_id):
        raise AssertionError("a lease modification must not use total journal debits as AP")

    monkeypatch.setattr(items, "_entry_amount", reject_journal_total)
    result = items.ActionResult(
        state="POSTED",
        item={},
        posting=items._post(engine, 7),
    )

    assert result.posting is not None
    assert (result.posting.status, result.posting.journal_entry_id) == ("posted", 41)
    assert result.posting.amount is None


def test_charge_post_keeps_accounts_payable_amount_fallback(monkeypatch):
    engine = _gateway_engine(gateway.CHARGE_CHECK, {})
    monkeypatch.setattr(gateway, "post_approved_charge", lambda conn, item_id: 42)
    monkeypatch.setattr(items, "_entry_amount", lambda engine, entry_id: Decimal("123.45"))

    posting = items._post(engine, 8)

    assert (posting.status, posting.journal_entry_id) == ("posted", 42)
    assert posting.amount == 123.45
