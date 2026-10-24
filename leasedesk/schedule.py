"""ASC 842 schedule math.

Deliberately plain arithmetic: no model gets to invent a number here. The LLM
decides *what the lease says*; this module decides *what the lease costs*.

Operating lease, payments in advance (rent due on the first of the month):

    liability_0   = PV of all payments at the IBR
    rou_0         = liability_0 + prepaid - incentives
    straight_line = total payments / term months
    interest_t    = (liability_t - payment_t) * monthly_rate
    liability_t+1 = liability_t - payment_t + interest_t
    rou_amort_t   = straight_line - interest_t     (the ROU plug)
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from .models import Lease


@dataclass
class Period:
    index: int
    period: date
    payment: float
    interest: float
    liability_open: float
    liability_close: float
    rou_open: float
    rou_amortization: float
    rou_close: float
    straight_line_cost: float


@dataclass
class Schedule:
    lease_id: str
    as_of: date
    opening_liability: float
    opening_rou: float
    periods: List[Period]

    def period_for(self, when: date) -> Optional[Period]:
        for p in self.periods:
            if p.period.year == when.year and p.period.month == when.month:
                return p
        return None

    def balances_at(self, when: date) -> dict:
        """Closing balances for the month containing `when`."""
        last = None
        for p in self.periods:
            if (p.period.year, p.period.month) > (when.year, when.month):
                break
            last = p
        if last is None:
            return {"liability": self.opening_liability, "rou": self.opening_rou}
        return {"liability": last.liability_close, "rou": last.rou_close}


def month_starts(start: date, end: date) -> List[date]:
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(date(y, m, 1))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def payments(lease: Lease) -> List[tuple]:
    return [(p, lease.rent_for(p)) for p in month_starts(lease.commencement, lease.end)]


def present_value(cashflows: List[float], annual_rate: float, in_advance: bool = True) -> float:
    """PV of monthly cashflows. In advance means the first payment is not discounted."""
    r = annual_rate / 12.0
    pv = 0.0
    for i, cf in enumerate(cashflows):
        n = i if in_advance else i + 1
        pv += cf / ((1 + r) ** n)
    return pv


def build(lease: Lease, opening_liability: Optional[float] = None,
          opening_rou: Optional[float] = None, start_from: Optional[date] = None) -> Schedule:
    """Build the full amortization schedule for `lease`.

    `opening_*` and `start_from` are used for remeasurement: after an amendment
    the schedule restarts from the modification date with adjusted balances
    rather than from commencement.
    """
    rows = payments(lease)
    if start_from:
        rows = [(p, amt) for p, amt in rows if (p.year, p.month) >= (start_from.year, start_from.month)]

    cash = [amt for _, amt in rows]
    liability = opening_liability if opening_liability is not None else present_value(cash, lease.discount_rate)
    rou = opening_rou if opening_rou is not None else liability + lease.prepaid - lease.incentives

    total_cost = sum(cash) + lease.prepaid - lease.incentives if start_from is None else None
    if total_cost is None:
        # Remeasured: remaining cost is remaining payments plus the ROU already carried.
        straight_line = (sum(cash) + (rou - liability)) / len(rows) if rows else 0.0
    else:
        straight_line = total_cost / len(rows) if rows else 0.0

    rate = lease.discount_rate / 12.0
    periods = []
    for i, (period, payment) in enumerate(rows):
        lia_open, rou_open = liability, rou
        interest = (lia_open - payment) * rate
        lia_close = lia_open - payment + interest
        rou_amort = straight_line - interest
        rou_close = rou_open - rou_amort
        periods.append(
            Period(
                index=i + 1,
                period=period,
                payment=round(payment, 2),
                interest=round(interest, 2),
                liability_open=round(lia_open, 2),
                liability_close=round(lia_close, 2),
                rou_open=round(rou_open, 2),
                rou_amortization=round(rou_amort, 2),
                rou_close=round(rou_close, 2),
                straight_line_cost=round(straight_line, 2),
            )
        )
        liability, rou = lia_close, rou_close

    return Schedule(
        lease_id=lease.lease_id,
        as_of=rows[0][0] if rows else lease.commencement,
        opening_liability=round(periods[0].liability_open, 2) if periods else 0.0,
        opening_rou=round(periods[0].rou_open, 2) if periods else 0.0,
        periods=periods,
    )
