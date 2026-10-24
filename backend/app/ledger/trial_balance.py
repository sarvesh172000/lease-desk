"""Trial balance: debit and credit totals per account for an entity and a
range of periods, with the double-entry check made explicit.

The database already refuses an unbalanced entry, so a trial balance that does
not balance means something went around the database (a disabled trigger, a
hand edit). That is worth stopping on, so `trial_balance()` raises rather than
returning a report whose bottom line is wrong.

Read-only: any role with SELECT on the ledger can run it, the auditor included.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List

from sqlalchemy import text
from sqlalchemy.engine import Connection

ZERO = Decimal("0.00")


class OutOfBalance(AssertionError):
    """Total debits differ from total credits."""


@dataclass(frozen=True)
class Row:
    code: str
    name: str
    type: str
    debit: Decimal
    credit: Decimal

    @property
    def balance(self) -> Decimal:
        """Debit-positive: assets and expenses are positive, liabilities negative."""
        return self.debit - self.credit


@dataclass(frozen=True)
class TrialBalance:
    entity_id: str
    first_period: date
    last_period: date
    rows: List[Row]

    @property
    def total_debits(self) -> Decimal:
        return sum((r.debit for r in self.rows), ZERO)

    @property
    def total_credits(self) -> Decimal:
        return sum((r.credit for r in self.rows), ZERO)

    def row(self, name: str) -> Row:
        for r in self.rows:
            if r.name == name:
                return r
        raise KeyError(name)


def trial_balance(conn: Connection, entity_id: str, first_period: date,
                  last_period: date = None) -> TrialBalance:
    """Every account of the entity with activity in [first_period, last_period],
    ordered by account code. Raises OutOfBalance if debits <> credits."""
    last_period = last_period or first_period
    _check_range(first_period, last_period)
    rows = conn.execute(text("""
        SELECT a.code, a.name, a.type,
               coalesce(sum(l.debit), 0) AS debit, coalesce(sum(l.credit), 0) AS credit
          FROM journal_line l
          JOIN journal_entry e ON e.id = l.journal_entry_id
          JOIN account a ON a.id = l.account_id
         WHERE e.entity_id = :entity AND e.period BETWEEN :first AND :last
         GROUP BY a.code, a.name, a.type
         ORDER BY a.code
    """), {"entity": entity_id, "first": first_period, "last": last_period}).mappings().all()
    tb = TrialBalance(entity_id=entity_id, first_period=first_period, last_period=last_period,
                      rows=[Row(**r) for r in rows])
    if tb.total_debits != tb.total_credits:
        raise OutOfBalance("trial balance for %s %s..%s is out of balance: debits %s <> credits %s"
                           % (entity_id, first_period, last_period,
                              tb.total_debits, tb.total_credits))
    return tb


def _check_range(first: date, last: date) -> None:
    for p in (first, last):
        if not isinstance(p, date) or p.day != 1:
            raise ValueError("periods must be first-of-month dates, got %r" % (p,))
    if first > last:
        raise ValueError("first period %s is after last period %s" % (first, last))
