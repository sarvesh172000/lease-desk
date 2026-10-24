"""Journal mechanics: check a set of lines, resolve account names, write the entry.

This module knows how to put a balanced entry into the books and nothing about
*whether* it should: the work-item state, who asked and the outbox belong to
`work/gateway.py`, which is the only caller.

Everything a caller can get wrong is caught here, in Python, before the first
INSERT, so the error names the mistake ("unknown account 'Lease Cost'")
instead of surfacing as a constraint violation at commit. The database
triggers in db/sql/002_integrity.sql remain the backstop: if this code were
wrong, the commit would still be refused.

Amounts become Decimal through their string form and must be whole cents. A
float such as 0.1 + 0.2 is rejected rather than silently rounded, because a
rounding the caller did not choose is how books stop tying out.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..agents.checker import APPROVE, Charge, Finding
from ..engine import journal as engine_journal

CENT = Decimal("0.01")


class PostingError(ValueError):
    """The entry cannot be posted as given. Nothing was written."""


class PeriodClosed(PostingError):
    """The period is closed, or was never opened, for this entity."""


@dataclass(frozen=True)
class Line:
    """One journal line, by account *name*, as the gateway accepts it."""
    account: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    clinic_id: Optional[str] = None


@dataclass(frozen=True)
class Posted:
    entry_id: int
    created: bool     # False when the idempotency key had already posted


# ------------------------------------------------------------ validation

def normalize_lines(lines: Iterable[Any]) -> List[Line]:
    """Accept engine `Line`s, gateway `Line`s, mappings or (account, debit,
    credit[, clinic_id]) tuples, and return checked gateway `Line`s."""
    if lines is None or isinstance(lines, (str, bytes, Mapping)):
        raise PostingError("lines must be a list of journal lines")
    out = [_one_line(raw, i) for i, raw in enumerate(lines)]
    check_balanced(out)
    return out


def check_balanced(lines: List[Line]) -> None:
    if len(lines) < 2:
        raise PostingError("a journal entry needs at least 2 lines, got %d" % len(lines))
    debits = sum((l.debit for l in lines), Decimal("0"))
    credits = sum((l.credit for l in lines), Decimal("0"))
    if debits != credits:
        raise PostingError("unbalanced entry: debits %s <> credits %s" % (debits, credits))


def _one_line(raw: Any, index: int) -> Line:
    account, debit, credit, clinic_id = _fields(raw, index)
    if not isinstance(account, str) or not account.strip():
        raise PostingError("line %d: account name is required" % index)
    debit, credit = _money(debit, index, "debit"), _money(credit, index, "credit")
    if (debit == 0) == (credit == 0):
        raise PostingError("line %d: exactly one of debit and credit must be non-zero" % index)
    return Line(account=account, debit=debit, credit=credit, clinic_id=clinic_id or None)


def _fields(raw: Any, index: int) -> Tuple[Any, Any, Any, Any]:
    if isinstance(raw, Mapping):
        return (raw.get("account"), raw.get("debit", 0), raw.get("credit", 0),
                raw.get("clinic_id"))
    if isinstance(raw, (tuple, list)) and len(raw) in (3, 4):
        return tuple(raw) + (None,) * (4 - len(raw))
    if hasattr(raw, "account"):
        return (raw.account, getattr(raw, "debit", 0), getattr(raw, "credit", 0),
                getattr(raw, "clinic_id", None))
    raise PostingError("line %d: not a journal line: %r" % (index, raw))


def _money(value: Any, index: int, side: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise PostingError("line %d: %s must be a number, got %r" % (index, side, value))
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PostingError("line %d: %s is not a number: %r" % (index, side, value)) from None
    if not amount.is_finite():
        raise PostingError("line %d: %s must be finite" % (index, side))
    if amount < 0:
        raise PostingError("line %d: %s cannot be negative (%s)" % (index, side, amount))
    if amount != amount.quantize(CENT):
        raise PostingError("line %d: %s %s is not a whole number of cents" % (index, side, amount))
    return amount.quantize(CENT)


def check_dates(entry_date: date, period: date) -> None:
    if not isinstance(entry_date, date) or not isinstance(period, date):
        raise PostingError("date and period must be dates")
    if period.day != 1:
        raise PostingError("period must be the first of a month, got %s" % period)
    if (entry_date.year, entry_date.month) != (period.year, period.month):
        raise PostingError("date %s is outside period %s" % (entry_date, period.strftime("%Y-%m")))


# ------------------------------------------------------------- database

def require_open_period(conn: Connection, entity_id: str, period: date) -> None:
    status = conn.execute(text(
        "SELECT status FROM period WHERE entity_id = :e AND period = :p"),
        {"e": entity_id, "p": period}).scalar()
    if status is None:
        raise PeriodClosed("period %s is not open for entity %s"
                           % (period.strftime("%Y-%m"), entity_id))
    if status != "open":
        raise PeriodClosed("period %s for entity %s is closed"
                           % (period.strftime("%Y-%m"), entity_id))


def resolve_accounts(conn: Connection, entity_id: str, names: Iterable[str]) -> Dict[str, int]:
    """Account name -> id in this entity's chart. Any unknown name fails."""
    chart = dict(conn.execute(text(
        "SELECT name, id FROM account WHERE entity_id = :e"), {"e": entity_id}).all())
    missing = sorted(set(n for n in names if n not in chart))
    if missing:
        raise PostingError("unknown account(s) %s in the chart of entity %s"
                           % (", ".join(repr(n) for n in missing), entity_id))
    return chart


def existing_entry(conn: Connection, idempotency_key: str) -> Optional[Mapping]:
    return conn.execute(text(
        "SELECT id, work_item_id FROM journal_entry WHERE idempotency_key = :k"),
        {"k": idempotency_key}).mappings().first()


def write_entry(conn: Connection, *, entity_id: str, entry_date: date, period: date,
                memo: str, entry_type: str, idempotency_key: str,
                work_item_id: Optional[int], lines: List[Line]) -> Posted:
    """Insert the entry and its lines in the caller's transaction.

    ON CONFLICT DO NOTHING makes a racing second post with the same key wait
    for the first to commit and then return the original instead of failing.
    """
    accounts = resolve_accounts(conn, entity_id, (l.account for l in lines))
    entry_id = conn.execute(text("""
        INSERT INTO journal_entry (entity_id, date, period, memo, entry_type,
                                   idempotency_key, work_item_id)
        VALUES (:entity, :date, :period, :memo, :type, :key, :item)
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id
    """), dict(entity=entity_id, date=entry_date, period=period, memo=memo,
               type=entry_type, key=idempotency_key, item=work_item_id)).scalar()
    if entry_id is None:
        return Posted(entry_id=existing_entry(conn, idempotency_key)["id"], created=False)
    conn.execute(text("""
        INSERT INTO journal_line (journal_entry_id, account_id, debit, credit, clinic_id)
        VALUES (:entry, :account, :debit, :credit, :clinic)
    """), [dict(entry=entry_id, account=accounts[l.account], debit=l.debit,
                credit=l.credit, clinic=l.clinic_id) for l in lines])
    return Posted(entry_id=entry_id, created=True)


# ------------------------------------------------ approved landlord charges

@dataclass(frozen=True)
class ChargeEntry:
    """What the engine says to post for one approved landlord charge."""
    entity_id: str
    period: date
    memo: str
    entry_type: str
    idempotency_key: str
    lines: List[Line]


def entry_for_charge(conn: Connection, charge_id: str) -> ChargeEntry:
    """Build the entry for an approved landlord charge with the engine's own
    journal rules (engine/journal.py), so the books and the engine agree on
    accounts and entry type."""
    row = conn.execute(text("""
        SELECT c.id, c.invoice_id, c.lease_id, c.clinic_id, c.period, c.charge_type,
               c.suite, c.amount, c.description, k.entity_id
          FROM landlord_charge c JOIN clinic k ON k.id = c.clinic_id
         WHERE c.id = :id
    """), {"id": charge_id}).mappings().first()
    if row is None:
        raise PostingError("no landlord charge %r" % charge_id)
    if row["amount"] <= 0:
        raise PostingError("charge %s has amount %s; only positive charges post as cost"
                           % (charge_id, row["amount"]))
    entries = engine_journal.entries_for([_approved_finding(row)])
    if not entries:
        raise PostingError("charge type %r of charge %s has no journal rule"
                           % (row["charge_type"], charge_id))
    entry = entries[0]
    return ChargeEntry(entity_id=row["entity_id"], period=entry.period, memo=entry.memo,
                       entry_type=entry.entry_type, idempotency_key=entry.idempotency_key(),
                       lines=normalize_lines(entry.lines))


def _approved_finding(row: Mapping) -> Finding:
    """The checker's own Finding for a charge a human approved: the item
    reached APPROVED, so the decision is made and the proposal is approve."""
    amount = float(row["amount"])
    charge = Charge(charge_id=row["id"], invoice_id=row["invoice_id"],
                    lease_id=row["lease_id"], clinic_id=row["clinic_id"],
                    period=row["period"], charge_type=row["charge_type"],
                    suite=row["suite"] or "", amount=amount,
                    description=row["description"] or "")
    return Finding(finding_id="approved:%s" % row["id"], rule="approved", charge=charge,
                   proposal=APPROVE, reason="approved", billed=amount, supported=amount)
