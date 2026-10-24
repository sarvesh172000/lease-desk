"""Match what was actually paid against what the schedule expected.

A variance is the trigger for everything else: it is the only reason the system
goes looking for an amendment.
"""

from dataclasses import dataclass
from datetime import date
from typing import List
import csv

from .schedule import Schedule

TOLERANCE = 1.00  # dollars; below this a difference is rounding, not a variance


@dataclass
class Payment:
    period: date
    lease_id: str
    amount: float
    reference: str = ""


@dataclass
class Variance:
    period: date
    lease_id: str
    expected: float
    actual: float

    @property
    def delta(self) -> float:
        return round(self.actual - self.expected, 2)

    @property
    def direction(self) -> str:
        return "underpaid" if self.delta < 0 else "overpaid"

    def describe(self) -> str:
        return (
            "{} {}: expected ${:,.2f}, paid ${:,.2f} ({} ${:,.2f})".format(
                self.lease_id,
                self.period.strftime("%b %Y"),
                self.expected,
                self.actual,
                self.direction,
                abs(self.delta),
            )
        )


def load_payments(path: str) -> List[Payment]:
    out = []
    with open(path) as fh:
        for row in csv.DictReader(fh):
            out.append(
                Payment(
                    period=date.fromisoformat(row["period"]),
                    lease_id=row["lease_id"],
                    amount=float(row["amount"]),
                    reference=row.get("reference", ""),
                )
            )
    return out


def check(schedule: Schedule, payments: List[Payment]) -> List[Variance]:
    """Return every month where cash and schedule disagree by more than tolerance."""
    variances = []
    for pay in payments:
        if pay.lease_id != schedule.lease_id:
            continue
        period = schedule.period_for(pay.period)
        if period is None:
            continue
        if abs(pay.amount - period.payment) > TOLERANCE:
            variances.append(
                Variance(
                    period=pay.period,
                    lease_id=pay.lease_id,
                    expected=period.payment,
                    actual=pay.amount,
                )
            )
    return variances


def first_break(variances: List[Variance]) -> Variance:
    """The earliest variance — where the investigation starts."""
    return sorted(variances, key=lambda v: v.period)[0]
