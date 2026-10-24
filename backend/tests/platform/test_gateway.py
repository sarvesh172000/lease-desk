"""post_journal(): the gateway turns an APPROVED item into a balanced entry
and POSTED, and refuses everything else before it writes a thing.

Phase 1 group 4 at the API level: unbalanced fails, a closed period rejects,
a duplicate idempotency key posts once. (The agent role failing even with raw
SQL is test_roles.py's job.)
"""

from datetime import date
from decimal import Decimal

import ledger_world as w
import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.work.events import events_for, verify_chain
from app.work.gateway import (
    GatewayError,
    PeriodClosed,
    PostingError,
    WrongState,
    post_approved,
    post_approved_charge,
    post_journal,
)

JAN, DEC = date(2026, 1, 1), date(2025, 12, 1)
RENT_LINES = [{"account": "Lease cost", "debit": "19626.65", "clinic_id": "CLINIC-01"},
              {"account": "Accounts payable", "credit": "19626.65", "clinic_id": "CLINIC-01"}]


@pytest.fixture
def world(books):
    w.build(books["owner"])
    return books


def post(eng, item_id, lines=RENT_LINES, key="rent-jan", period=JAN, day=None, **kw):
    with eng["lease_gateway"].begin() as conn:
        return post_journal(conn, item_id, lines, key, entity_id=kw.pop("entity_id", "ENT-CA"),
                            date=day or period, period=period, memo="January rent", **kw)


def state(eng, item_id):
    return w.scalar(eng["lease_reader"], "SELECT state FROM work_item WHERE id = :i", i=item_id)


def entries(eng):
    return w.scalar(eng["lease_reader"], "SELECT count(*) FROM journal_entry")


# ----------------------------------------------------------------- happy path

def test_an_approved_item_posts_and_becomes_posted(world):
    item = w.item(world["owner"], w.RENT)
    entry = post(world, item, entry_type="phase1_period_cost")

    assert state(world, item) == "POSTED"
    lines = w.rows(world["lease_reader"], """
        SELECT a.name, l.debit, l.credit, l.clinic_id FROM journal_line l
          JOIN account a ON a.id = l.account_id WHERE l.journal_entry_id = :e ORDER BY l.id
    """, e=entry)
    assert [(r["name"], r["debit"], r["credit"]) for r in lines] == [
        ("Lease cost", Decimal("19626.65"), Decimal("0")),
        ("Accounts payable", Decimal("0"), Decimal("19626.65"))]
    assert w.scalar(world["lease_reader"], "SELECT work_item_id FROM journal_entry WHERE id = :e",
                    e=entry) == item


def test_posting_appends_the_work_layer_event_and_keeps_the_chain(world):
    item = w.item(world["owner"], w.RENT)
    entry = post(world, item)
    with world["lease_reader"].connect() as conn:
        (event,) = events_for(conn, "work_item", item)
        assert verify_chain(conn) is None
    assert (event.actor_id, event.action) == ("system:gateway", "post")
    assert event.diff == {"from": "APPROVED", "to": "POSTED", "set": {}}
    assert event.evidence == {"journal_entry_id": entry}
    assert w.scalar(world["lease_reader"], "SELECT last_event_seq FROM work_item WHERE id = :i",
                    i=item) == event.seq


def test_engine_line_objects_and_tuples_are_accepted(world):
    from app.engine.journal import Line

    a, b = w.item(world["owner"], w.RENT), w.item(world["owner"], w.CAM)
    post(world, a, [Line("Lease cost", debit=10.5), Line("Accounts payable", credit=10.5)], key="a")
    post(world, b, [("CAM expense", 7, 0), ("Accounts payable", 0, 7, "CLINIC-01")], key="b")
    assert entries(world) == 2


# ------------------------------------------------------------- idempotency

def test_a_duplicate_key_posts_once_and_returns_the_original(world):
    item = w.item(world["owner"], w.RENT)
    first = post(world, item)
    again = post(world, item)                       # item is POSTED now: still no error
    assert again == first
    assert entries(world) == 1
    assert w.scalar(world["lease_reader"], "SELECT count(*) FROM journal_line") == 2
    assert len(w.rows(world["lease_reader"], "SELECT 1 FROM audit_event")) == 1


def test_a_key_reused_for_a_different_item_is_refused(world):
    a, b = w.item(world["owner"], w.RENT), w.item(world["owner"], w.CAM)
    post(world, a)
    with pytest.raises(GatewayError, match="already posted entry"):
        post(world, b)
    assert state(world, b) == "APPROVED"


def test_two_concurrent_posts_of_one_key_post_once(world):
    import threading

    item = w.item(world["owner"], w.RENT)
    results, errors = [], []

    def run():
        try:
            results.append(post(world, item))
        except Exception as exc:                    # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(set(results)) == 1
    assert entries(world) == 1


# ------------------------------------------------------------- refusals

@pytest.mark.parametrize("bad_state", ["NEW", "PROPOSED", "HELD", "REJECTED", "NEEDS_INFO", "CLOSED"])
def test_only_approved_items_post(world, bad_state):
    item = w.item(world["owner"], w.RENT, state=bad_state)
    with pytest.raises(WrongState, match="only APPROVED"):
        post(world, item)
    assert entries(world) == 0 and state(world, item) == bad_state


def test_an_unbalanced_entry_is_refused_before_the_database(world):
    item = w.item(world["owner"], w.RENT)
    with pytest.raises(PostingError, match="unbalanced"):
        post(world, item, [("Lease cost", "100.00", 0), ("Accounts payable", 0, "99.99")])
    assert entries(world) == 0 and state(world, item) == "APPROVED"


def test_a_closed_period_rejects(world):
    item = w.item(world["owner"], w.RENT_DEC, period="2025-12-01")
    with pytest.raises(PeriodClosed, match="2025-12 for entity ENT-CA is closed"):
        post(world, item, period=DEC)
    assert entries(world) == 0 and state(world, item) == "APPROVED"


def test_a_period_never_opened_rejects(world):
    item = w.item(world["owner"], w.RENT)
    with pytest.raises(PeriodClosed, match="not open"):
        post(world, item, period=date(2030, 1, 1))


def test_an_unknown_account_name_is_named_in_the_error(world):
    item = w.item(world["owner"], w.RENT)
    with pytest.raises(PostingError, match="unknown account.*'Lease Cost'.*ENT-CA"):
        post(world, item, [("Lease Cost", 5, 0), ("Accounts payable", 0, 5)])
    assert entries(world) == 0


@pytest.mark.parametrize("lines,message", [
    ([], "at least 2"),
    ([("Lease cost", 5, 0)], "at least 2"),
    ([("Lease cost", 5, 5), ("Accounts payable", 0, 0)], "exactly one"),
    ([("Lease cost", -5, 0), ("Accounts payable", 0, -5)], "negative"),
    ([("Lease cost", 0.1 + 0.2, 0), ("Accounts payable", 0, 0.3)], "whole number of cents"),
    ([("Lease cost", "abc", 0), ("Accounts payable", 0, 1)], "not a number"),
    ([("Lease cost", float("nan"), 0), ("Accounts payable", 0, 1)], "finite"),
    ([("Lease cost", True, 0), ("Accounts payable", 0, 1)], "must be a number"),
    ([("", 5, 0), ("Accounts payable", 0, 5)], "account name"),
    (["Lease cost", "Accounts payable"], "not a journal line"),
    ("Lease cost", "list of journal lines"),
])
def test_malformed_lines_are_refused(world, lines, message):
    item = w.item(world["owner"], w.RENT)
    with pytest.raises(PostingError, match=message):
        post(world, item, lines)
    assert entries(world) == 0


@pytest.mark.parametrize("kwargs,message", [
    (dict(period=date(2026, 1, 15)), "first of a month"),
    (dict(day=date(2026, 2, 3)), "outside period"),
    (dict(key=""), "idempotency_key"),
    (dict(entity_id="ENT-NV"), "belongs to entity ENT-CA"),
])
def test_bad_arguments_are_refused(world, kwargs, message):
    item = w.item(world["owner"], w.RENT)
    with pytest.raises((PostingError, GatewayError), match=message):
        post(world, item, **kwargs)
    assert entries(world) == 0


@pytest.mark.parametrize("item_id", [999999, "1", None, True])
def test_a_missing_or_malformed_item_is_refused(world, item_id):
    with pytest.raises(GatewayError, match="work item"):
        post(world, item_id)


def test_the_agent_role_cannot_use_the_gateway(world):
    """The gateway function on the wrong connection is still refused by the
    database: the agent may not write journal_entry."""
    item = w.item(world["owner"], w.RENT)
    with pytest.raises(ProgrammingError, match="permission denied"):
        with world["lease_agent"].begin() as conn:
            post_journal(conn, item, RENT_LINES, "k", entity_id="ENT-CA", date=JAN,
                         period=JAN, memo="x")
    assert entries(world) == 0


# ------------------------------------------------- approved landlord charges

def test_an_approved_january_rent_charge_posts_as_period_cost(world):
    item = w.item(world["owner"], w.RENT)
    with world["lease_gateway"].begin() as conn:
        entry = post_approved_charge(conn, item)
    row = w.rows(world["lease_reader"], "SELECT * FROM journal_entry WHERE id = :e", e=entry)[0]
    assert row["entry_type"] == "phase1_period_cost"
    assert row["period"] == JAN and row["entity_id"] == "ENT-CA"
    lines = w.rows(world["lease_reader"], """
        SELECT a.name, l.debit, l.credit, l.clinic_id FROM journal_line l
          JOIN account a ON a.id = l.account_id WHERE journal_entry_id = :e ORDER BY l.id
    """, e=entry)
    assert [(l["name"], l["debit"] or -l["credit"], l["clinic_id"]) for l in lines] == [
        ("Lease cost", Decimal("19626.65"), "CLINIC-01"),
        ("Accounts payable", Decimal("-19626.65"), "CLINIC-01")]
    assert state(world, item) == "POSTED"
    with world["lease_gateway"].begin() as conn:     # posting again is a no-op
        assert post_approved_charge(conn, item) == entry
    assert entries(world) == 1


def test_an_approved_cam_charge_posts_to_cam_expense(world):
    item = w.item(world["owner"], w.CAM)
    with world["lease_gateway"].begin() as conn:
        entry = post_approved_charge(conn, item)
    assert w.scalar(world["lease_reader"], """
        SELECT a.name FROM journal_line l JOIN account a ON a.id = l.account_id
         WHERE journal_entry_id = :e AND l.debit > 0""", e=entry) == "CAM expense"


@pytest.mark.parametrize("charge,kind,subject_type,message", [
    (w.LATE_FEE, "CHARGE_CHECK", "landlord_charge", "no journal rule"),
    (w.CREDIT, "CHARGE_CHECK", "landlord_charge", "only positive"),
    ("CHG-NOPE", "CHARGE_CHECK", "landlord_charge", "no landlord charge"),
    ("LEASE-01", "LEASE_ABSTRACTION", "lease", "not a landlord charge check"),
])
def test_charges_the_engine_cannot_post_are_refused(world, charge, kind, subject_type, message):
    item = w.item(world["owner"], charge, kind=kind, subject_type=subject_type)
    with pytest.raises((PostingError, GatewayError), match=message):
        with world["lease_gateway"].begin() as conn:
            post_approved_charge(conn, item)
    assert entries(world) == 0


# ------------------------------------------------ the work layer's post

def test_post_is_a_work_layer_transition_by_the_gateway_actor(world):
    """The gateway's actor is created if the actor table lacks it, and the
    move to POSTED is the work layer's own `post` transition."""
    item = w.item(world["owner"], w.RENT)
    assert w.scalar(world["lease_reader"],
                    "SELECT count(*) FROM actor WHERE id = 'system:gateway'") == 0
    post(world, item)
    assert w.scalar(world["lease_reader"],
                    "SELECT role FROM actor WHERE id = 'system:gateway'") == "system"


def test_a_deactivated_gateway_actor_cannot_post(world):
    from app.work.roles import UnknownActor

    with world["owner"].begin() as conn:
        conn.execute(text("INSERT INTO actor (id, name, role, active) "
                          "VALUES ('system:gateway', 'Gateway', 'system', false)"))
    item = w.item(world["owner"], w.RENT)
    with pytest.raises(UnknownActor, match="system:gateway"):
        post(world, item)
    assert entries(world) == 0 and state(world, item) == "APPROVED"


def test_a_concurrently_moved_item_is_not_posted(world):
    """post_journal() checks APPROVED after locking; transition() checks the
    machine again, so an item that is not APPROVED can never become POSTED."""
    from app.work.roles import ensure_gateway_actor
    from app.work.transitions import IllegalTransition, transition

    item = w.item(world["owner"], w.RENT, state="HELD")
    with pytest.raises(IllegalTransition):
        with world["lease_gateway"].begin() as conn:
            transition(conn, ensure_gateway_actor(conn), item, "post")
    assert state(world, item) == "HELD"


# ------------------------------------------------------- post_approved

def test_post_approved_posts_the_periods_approved_charges_once(world):
    rent, cam = w.item(world["owner"], w.RENT), w.item(world["owner"], w.CAM)
    held = w.item(world["owner"], w.LATE_FEE, state="HELD")
    december = w.item(world["owner"], w.RENT_DEC, period="2025-12-01")
    with world["lease_gateway"].begin() as conn:
        posted = post_approved(conn, "ENT-CA", JAN)
    assert [p.work_item_id for p in posted] == [rent, cam]
    assert entries(world) == 2
    assert (state(world, rent), state(world, cam)) == ("POSTED", "POSTED")
    assert (state(world, held), state(world, december)) == ("HELD", "APPROVED")
    assert w.scalar(world["lease_reader"], "SELECT sum(debit) FROM journal_line") == \
        Decimal("21726.65")

    with world["lease_gateway"].begin() as conn:
        assert post_approved(conn, "ENT-CA", JAN) == []
    assert entries(world) == 2


def test_post_approved_for_another_entity_or_month_posts_nothing(world):
    w.item(world["owner"], w.RENT)
    with world["lease_gateway"].begin() as conn:
        assert post_approved(conn, "ENT-NV", JAN) == []
        assert post_approved(conn, "ENT-CA", date(2026, 2, 1)) == []
    assert entries(world) == 0


@pytest.mark.parametrize("entity,period,message", [
    ("", JAN, "entity_id"),
    ("ENT-CA", date(2026, 1, 15), "first of a month"),
    ("ENT-CA", "2026-01", "first of a month"),
])
def test_post_approved_refuses_bad_arguments(world, entity, period, message):
    with pytest.raises((PostingError, GatewayError), match=message):
        with world["lease_gateway"].begin() as conn:
            post_approved(conn, entity, period)


def test_one_unpostable_charge_rolls_the_whole_call_back(world):
    w.item(world["owner"], w.RENT)
    w.item(world["owner"], w.LATE_FEE)              # approved, but no journal rule
    with pytest.raises(PostingError, match="no journal rule"):
        with world["lease_gateway"].begin() as conn:
            post_approved(conn, "ENT-CA", JAN)
    assert entries(world) == 0


def test_the_agent_role_cannot_post_approved(world):
    w.item(world["owner"], w.RENT)
    with pytest.raises(ProgrammingError, match="permission denied"):
        with world["lease_agent"].begin() as conn:
            post_approved(conn, "ENT-CA", JAN)
    assert entries(world) == 0
