"""Remeasure a lease after an amendment and propose the adjusting entries.

Under ASC 842 a modification that is not a separate contract is handled by
remeasuring the liability at the revised payments and discount rate, with the
difference booked against the ROU asset (no immediate P&L for an operating
lease). The catch-up for months already closed on the old schedule does hit
rent expense.
"""

from dataclasses import dataclass
from datetime import date
from typing import List

from .models import Lease
from .schedule import Schedule, build


@dataclass
class JournalLine:
    account: str
    debit: float = 0.0
    credit: float = 0.0


@dataclass
class Remeasurement:
    lease_id: str
    effective: date
    old: Schedule
    new: Schedule
    liability_before: float
    liability_after: float
    rou_before: float
    rou_after: float
    expense_catchup: float
    entries: List[JournalLine]

    @property
    def liability_delta(self) -> float:
        return round(self.liability_after - self.liability_before, 2)

    @property
    def rou_delta(self) -> float:
        return round(self.rou_after - self.rou_before, 2)


def remeasure(original: Lease, effective: date, through: date) -> Remeasurement:
    """Compare the pre-amendment schedule to the amended one at `effective`.

    `through` is the last month already closed in the books, used to size the
    rent-expense catch-up for periods booked on the stale schedule.
    """
    before = original.as_of(_day_before(effective))
    after = original.as_of(through)

    old_schedule = build(before)
    carried = old_schedule.balances_at(_day_before(effective))

    new_schedule = build(
        after,
        opening_liability=_pv_remaining(after, effective),
        opening_rou=None,
        start_from=effective,
    )
    # ROU moves by the same amount as the liability for a non-separate modification.
    liability_before = carried["liability"]
    liability_after = new_schedule.opening_liability
    rou_before = carried["rou"]
    rou_after = round(rou_before + (liability_after - liability_before), 2)

    new_schedule = build(
        after,
        opening_liability=liability_after,
        opening_rou=rou_after,
        start_from=effective,
    )

    catchup = _expense_catchup(old_schedule, new_schedule, effective, through)
    entries = _entries(liability_after - liability_before, rou_after - rou_before, catchup)

    return Remeasurement(
        lease_id=original.lease_id,
        effective=effective,
        old=old_schedule,
        new=new_schedule,
        liability_before=round(liability_before, 2),
        liability_after=round(liability_after, 2),
        rou_before=round(rou_before, 2),
        rou_after=rou_after,
        expense_catchup=catchup,
        entries=entries,
    )


def _pv_remaining(lease: Lease, effective: date) -> float:
    from .schedule import month_starts, present_value

    cash = [lease.rent_for(p) for p in month_starts(effective, lease.end)]
    return round(present_value(cash, lease.discount_rate), 2)


def _expense_catchup(old: Schedule, new: Schedule, effective: date, through: date) -> float:
    """Rent expense already booked on the old schedule, less what it should have been."""
    booked = 0.0
    correct = 0.0
    for p in old.periods:
        if effective <= p.period <= through:
            booked += p.straight_line_cost
    for p in new.periods:
        if effective <= p.period <= through:
            correct += p.straight_line_cost
    return round(correct - booked, 2)


def _entries(liability_delta: float, rou_delta: float, catchup: float) -> List[JournalLine]:
    lines = []
    if liability_delta > 0:
        lines.append(JournalLine("Lease liability", credit=round(liability_delta, 2)))
    elif liability_delta < 0:
        lines.append(JournalLine("Lease liability", debit=round(-liability_delta, 2)))
    if rou_delta > 0:
        lines.append(JournalLine("ROU asset", debit=round(rou_delta, 2)))
    elif rou_delta < 0:
        lines.append(JournalLine("ROU asset", credit=round(-rou_delta, 2)))
    if abs(catchup) >= 0.01:
        if catchup > 0:
            lines.append(JournalLine("Rent expense", debit=catchup))
            lines.append(JournalLine("ROU asset", credit=catchup))
        else:
            lines.append(JournalLine("ROU asset", debit=-catchup))
            lines.append(JournalLine("Rent expense", credit=-catchup))
    return lines


def _day_before(d: date) -> date:
    from datetime import timedelta

    return d - timedelta(days=1)
