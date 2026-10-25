"""Defense in depth: each layer below can() holds on its own.

`can()` is the first line. These tests switch it off (monkeypatched to allow
everything, the way a bug or a compromised agent would) and show that what
it guards still cannot happen, one layer at a time:

  LAYER 1  the lease_agent database role cannot write the journal, the
           outbox, golden tables or periods, and cannot make or record a
           decision (approve, reject, post, close) that would let the gateway
           post on its behalf
  LAYER 2  the lease_api database role cannot post
  LAYER 3  the gateway refuses an unbalanced entry and a closed period, and
           the database refuses them again if the gateway's checks are skipped

Each test is labelled with its layer. The world is the ledger world (one
clinic, its January charges, a chart of accounts, January open and December
closed) plus a checker agent and an auditor.
"""

from datetime import date

import ledger_world as w
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.bootstrap import execute_raw
from app.work import gateway, roles, transitions
from app.work.events import append_event, verify_chain
from app.work.gateway import PeriodClosed, PostingError, post_approved_charge, post_journal
from app.work.roles import Actor
from app.work.transitions import create_item, transition

JAN, DEC = date(2026, 1, 1), date(2025, 12, 1)
CHECKER = Actor("agent:checker", "agent", None, None)
RM = Actor("PER-RM-BAY", "regional_manager", "REG-BAY", "ENT-CA")
CTRL = Actor("PER-CTRL", "controller", None, None)
LINES = [{"account": "Lease cost", "debit": "19626.65", "clinic_id": "STORE-01"},
         {"account": "Accounts payable", "credit": "19626.65", "clinic_id": "STORE-01"}]

GOLDEN = ("entity", "region", "landlord", "center", "clinic", "lease", "landlord_charge",
          "payment")
LEDGER = ("account", "period", "journal_entry", "journal_line")
PROTECTED = GOLDEN + LEDGER + ("outbox",)


@pytest.fixture
def world(books):
    w.build(books["owner"])
    with books["owner"].begin() as conn:
        execute_raw(conn, """
            INSERT INTO actor (id, name, role, active) VALUES
              ('agent:checker', 'Charge checker', 'agent', true),
              ('PER-AUD', 'Auditor', 'auditor', true);
        """)
        roles.ensure_gateway_actor(conn)
    return books


@pytest.fixture
def bypass_can(monkeypatch):
    """can() says yes to everyone, for everything."""
    def always(actor, action, item):
        return True, "can() bypassed by the test harness"
    monkeypatch.setattr(roles, "can", always)
    monkeypatch.setattr(transitions, "can", always)
    return always


def proposed_item(engines, charge_id=w.RENT, proposal="approve"):
    """A charge check the checker opened and proposed, through the work layer."""
    with engines["lease_agent"].begin() as conn:
        item = create_item(conn, CHECKER, kind="CHARGE_CHECK", subject_type="landlord_charge",
                           subject_id=charge_id, title="check %s" % charge_id,
                           entity_id="ENT-CA", region_id="REG-BAY", clinic_id="STORE-01",
                           period=JAN, amount="19626.65",
                           evidence={"billed": 19626.65, "supported": 19626.65})
        transition(conn, CHECKER, item["id"], "propose", patch={"proposal": proposal})
    return item["id"]


def refused(eng, sql, params=None) -> str:
    """Run one statement as a role, expect the database to refuse it, return why."""
    with eng.connect() as conn:
        with pytest.raises(DBAPIError) as info:
            with conn.begin():
                conn.execute(text(sql), params or {})
    return str(info.value.orig).splitlines()[0]


def q(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def ledger_rows(engines):
    return (q(engines["owner"], "SELECT count(*) FROM journal_entry"),
            q(engines["owner"], "SELECT count(*) FROM journal_line"),
            q(engines["owner"], "SELECT count(*) FROM outbox"))


def chain_ok(engines):
    with engines["lease_reader"].connect() as conn:
        return verify_chain(conn) is None


# ===================================================================== LAYER 1
# The lease_agent database role, with can() bypassed.

def test_layer1_agent_role_holds_no_write_privilege_on_ledger_outbox_golden_or_period(world):
    """Not just INSERT on the obvious tables: no INSERT, UPDATE, DELETE or
    TRUNCATE, on any column, of anything the books or AP are made of."""
    with world["owner"].connect() as conn:
        held = [(table, privilege) for table in PROTECTED
                for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE")
                if conn.execute(text("SELECT has_table_privilege('lease_agent', :t, :p)"),
                                {"t": table, "p": privilege}).scalar()]
        held += [(table, "column %s" % privilege) for table in PROTECTED
                 for privilege in ("INSERT", "UPDATE")
                 if conn.execute(text(
                     "SELECT has_any_column_privilege('lease_agent', :t, :p)"),
                     {"t": table, "p": privilege}).scalar()]
    assert held == []


@pytest.mark.parametrize("sql", [
    "INSERT INTO journal_entry (entity_id, date, period, memo, idempotency_key) "
    "VALUES ('ENT-CA', '2026-01-31', '2026-01-01', 'agent posts', 'L1')",
    "INSERT INTO journal_line (journal_entry_id, account_id, debit) VALUES (1, 1, 1)",
    "INSERT INTO outbox (kind, payload, idempotency_key) VALUES ('ap_batch', '{}', 'L1')",
    "UPDATE outbox SET status = 'sent'",
    "UPDATE period SET status = 'open' WHERE period = '2025-12-01'",
    "INSERT INTO period (entity_id, period, status) VALUES ('ENT-CA', '2026-02-01', 'open')",
    "INSERT INTO payment (id, clinic_id, lease_id, period, paid_on, charge_type, amount, raw_ref) "
    "VALUES ('P-X', 'STORE-01', 'LEASE-01', '2026-01-01', '2026-01-02', 'base_rent', 1, 'RAW-1')",
    "UPDATE landlord_charge SET amount = 0",
    "UPDATE landlord SET name = 'Wire it to 4471-99812'",
    "INSERT INTO entity VALUES ('ENT-X', 'x', 'CA')",
])
def test_layer1_agent_role_raw_sql_on_the_books_is_permission_denied(world, sql, bypass_can):
    assert "permission denied" in refused(world["lease_agent"], sql)
    assert ledger_rows(world) == (0, 0, 0)


def test_layer1_agent_role_cannot_post_even_by_calling_the_gateway_itself(world, bypass_can):
    """The gateway's own code, run on the agent's connection: the INSERT into
    journal_entry is refused by Postgres, so nothing posts."""
    item_id = w.item(world["owner"], w.RENT, state="APPROVED")
    with pytest.raises(DBAPIError, match="permission denied"):
        with world["lease_agent"].begin() as conn:
            post_journal(conn, item_id, LINES, "agent-key", entity_id="ENT-CA", date=JAN,
                         period=JAN, memo="agent posts")
    assert ledger_rows(world) == (0, 0, 0)


def test_layer1_agent_cannot_approve_even_when_can_says_yes(world, bypass_can):
    """With can() bypassed, transition() would record the agent's approve and
    project APPROVED, after which the gateway would post it. The database
    refuses the event: approving is a person's decision, and lease_agent may
    not record it."""
    item_id = proposed_item(world)
    with pytest.raises(DBAPIError, match="lease_agent may not record"):
        with world["lease_agent"].begin() as conn:
            transition(conn, CHECKER, item_id, "approve")
    assert q(world["owner"], "SELECT state FROM work_item WHERE id = :i", i=item_id) == "PROPOSED"
    with world["lease_gateway"].begin() as conn:
        assert gateway.post_approved(conn, "ENT-CA", JAN) == []
    assert ledger_rows(world) == (0, 0, 0)
    assert chain_ok(world)


@pytest.mark.parametrize("action", ["approve", "reject", "close", "post", "resume", "answer"])
def test_layer1_agent_cannot_record_a_decision_in_anyones_name(world, action):
    """Raw INSERT INTO audit_event as lease_agent: an allowed decision, here
    in the controller's name, is refused. Refusals (allowed = false) and the
    agent's own moves are still recorded normally."""
    item_id = proposed_item(world)
    why = refused(world["lease_agent"], """
        INSERT INTO audit_event (actor_id, action, subject_type, subject_id, allowed, diff)
        VALUES ('PER-CTRL', :a, 'work_item', :i, true,
                '{"from": "PROPOSED", "to": "APPROVED", "set": {}}')
    """, {"a": action, "i": str(item_id)})
    assert "lease_agent may not record" in why
    with world["lease_agent"].begin() as conn:
        append_event(conn, actor_id=CHECKER.id, action=action, subject_type="work_item",
                     subject_id=item_id, allowed=False, reason="refused, and on record")
    assert chain_ok(world)


def test_layer1_agent_cannot_forge_an_approved_state_for_the_gateway_to_post(world):
    """The work_item row is a projection the agent role may update (it moves
    its own items). It may not move one into a decided state: a raw UPDATE
    to APPROVED is refused, so the gateway never sees an approval nobody made."""
    item_id = proposed_item(world)
    for state in ("APPROVED", "POSTED", "REJECTED", "CLOSED"):
        why = refused(world["lease_agent"], "UPDATE work_item SET state = :s WHERE id = :i",
                      {"s": state, "i": item_id})
        assert "lease_agent may not put work item" in why
    why = refused(world["lease_agent"], """
        INSERT INTO work_item (kind, state, subject_type, subject_id, entity_id, title)
        VALUES ('CHARGE_CHECK', 'APPROVED', 'landlord_charge', 'CHG-CAM-01', 'ENT-CA', 'forged')
    """)
    assert "lease_agent may not put work item" in why
    with world["lease_gateway"].begin() as conn:
        assert gateway.post_approved(conn, "ENT-CA", JAN) == []
    assert ledger_rows(world) == (0, 0, 0)


def test_layer1_agent_cannot_edit_an_item_a_person_already_approved(world):
    """Once a person approves, the agent cannot touch the row (say, raising
    the undisputed amount the gateway will post), only pull it back to HELD,
    which needs a person again."""
    item_id = proposed_item(world, proposal="hold")
    with world["lease_api"].begin() as conn:
        transition(conn, RM, item_id, "approve")
    why = refused(world["lease_agent"], """
        UPDATE work_item SET evidence = evidence || '{"supported": 99999}' WHERE id = :i
    """, {"i": item_id})
    assert "lease_agent may not put work item" in why
    with world["lease_agent"].begin() as conn:
        transition(conn, CHECKER, item_id, "hold", reason="new information")
    assert q(world["owner"], "SELECT state FROM work_item WHERE id = :i", i=item_id) == "HELD"


def test_layer1_agent_cannot_insert_a_lease_version_already_confirmed(world):
    """The agent drafts lease versions; a person confirms them. A draft that
    arrives with confirmed_by already set is refused, because the checker
    trusts a confirmed version's terms."""
    why = refused(world["lease_agent"], """
        INSERT INTO lease_version (lease_id, version, effective_from, confirmed_by, confirmed_at)
        VALUES ('LEASE-01', 1, '2024-01-01', 'PER-RM-BAY', now())
    """)
    assert "lease_agent may not confirm" in why
    with world["lease_agent"].begin() as conn:
        conn.execute(text("INSERT INTO lease_version (lease_id, version, effective_from) "
                          "VALUES ('LEASE-01', 1, '2024-01-01')"))
    assert q(world["owner"], "SELECT count(*) FROM lease_version WHERE confirmed_by IS NULL") == 1


# ===================================================================== LAYER 2
# The lease_api database role, with can() bypassed.

def test_layer2_api_role_holds_no_write_privilege_on_the_ledger_or_outbox(world):
    with world["owner"].connect() as conn:
        held = [(t, p) for t in ("journal_entry", "journal_line", "outbox", "period", "account")
                for p in ("INSERT", "UPDATE", "DELETE", "TRUNCATE")
                if conn.execute(text("SELECT has_table_privilege('lease_api', :t, :p)"),
                                {"t": t, "p": p}).scalar()]
    assert held == []


def test_layer2_api_role_cannot_post_through_the_gateway_code(world, bypass_can):
    item_id = w.item(world["owner"], w.RENT, state="APPROVED")
    with pytest.raises(DBAPIError, match="permission denied"):
        with world["lease_api"].begin() as conn:
            post_approved_charge(conn, item_id)
    assert ledger_rows(world) == (0, 0, 0)


@pytest.mark.parametrize("sql", [
    "INSERT INTO journal_line (journal_entry_id, account_id, debit) VALUES (1, 1, 1)",
    "INSERT INTO journal_entry (entity_id, date, period, memo, idempotency_key) "
    "VALUES ('ENT-CA', '2026-01-31', '2026-01-01', 'api posts', 'L2')",
    "INSERT INTO outbox (kind, payload, idempotency_key) VALUES ('ap_batch', '{}', 'L2')",
])
def test_layer2_api_role_raw_sql_on_the_ledger_is_permission_denied(world, sql):
    assert "permission denied" in refused(world["lease_api"], sql)


def test_layer2_a_person_cannot_mark_an_item_posted_when_can_says_yes(world, bypass_can):
    """Posting is the gateway's: with can() bypassed, a controller's `post`
    through the API role is refused by the database, so no item reads POSTED
    without an entry behind it."""
    item_id = proposed_item(world)
    with world["lease_api"].begin() as conn:
        transition(conn, RM, item_id, "approve")
    with pytest.raises(DBAPIError, match="lease_api may not record"):
        with world["lease_api"].begin() as conn:
            transition(conn, CTRL, item_id, "post")
    why = refused(world["lease_api"], "UPDATE work_item SET state = 'POSTED' WHERE id = :i",
                  {"i": item_id})
    assert "only the gateway posts" in why
    assert q(world["owner"], "SELECT state FROM work_item WHERE id = :i", i=item_id) == "APPROVED"
    assert ledger_rows(world) == (0, 0, 0)


# ===================================================================== LAYER 3
# The gateway, with can() bypassed: its own checks, then the database's.

def test_layer3_gateway_refuses_an_unbalanced_entry(world, bypass_can):
    item_id = w.item(world["owner"], w.RENT, state="APPROVED")
    lines = [dict(LINES[0]), dict(LINES[1], credit="19000.00")]
    with pytest.raises(PostingError, match="balance"):
        with world["lease_gateway"].begin() as conn:
            post_journal(conn, item_id, lines, "unbalanced", entity_id="ENT-CA", date=JAN,
                         period=JAN, memo="unbalanced")
    assert ledger_rows(world) == (0, 0, 0)


def test_layer3_gateway_refuses_a_closed_period(world, bypass_can):
    item_id = w.item(world["owner"], w.RENT_DEC, state="APPROVED", period="2025-12-01")
    with pytest.raises(PeriodClosed):
        with world["lease_gateway"].begin() as conn:
            post_journal(conn, item_id, LINES, "closed", entity_id="ENT-CA", date=DEC,
                         period=DEC, memo="into December")
    assert ledger_rows(world) == (0, 0, 0)


def test_layer3_database_refuses_an_unbalanced_entry_the_gateway_code_skipped(world):
    """Raw SQL as lease_gateway, no Python checks at all: the deferred
    balance trigger refuses the entry at commit."""
    with pytest.raises(DBAPIError, match="balance"):
        with world["lease_gateway"].begin() as conn:
            entry = conn.execute(text("""
                INSERT INTO journal_entry (entity_id, date, period, memo, idempotency_key)
                VALUES ('ENT-CA', '2026-01-31', '2026-01-01', 'raw', 'L3-unbalanced')
                RETURNING id""")).scalar_one()
            conn.execute(text("""
                INSERT INTO journal_line (journal_entry_id, account_id, debit)
                SELECT :e, id, 100 FROM account WHERE entity_id = 'ENT-CA' LIMIT 1
            """), {"e": entry})
    assert ledger_rows(world) == (0, 0, 0)


def test_layer3_database_refuses_a_closed_period_the_gateway_code_skipped(world):
    why = refused(world["lease_gateway"], """
        INSERT INTO journal_entry (entity_id, date, period, memo, idempotency_key)
        VALUES ('ENT-CA', '2025-12-31', '2025-12-01', 'raw', 'L3-closed')""")
    assert "closed" in why
    assert ledger_rows(world) == (0, 0, 0)
