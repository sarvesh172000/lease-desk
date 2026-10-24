"""The operating lease subledger.

`leasedesk/schedule.py` builds one lease's amortization. This is the layer
above it: every lease in an entity, every month, as the entries that actually
post — and the balances those entries must tie to.

Operating lease, ASC 842. The monthly entry is:

    Dr  Lease cost              straight-line cost
    Dr  Lease liability         payment less accretion
    Cr  ROU asset               straight-line less accretion
    Cr  Cash / Accounts payable the payment

Two things make this more than arithmetic:

**The liability splits current and non-current.** Anything due within twelve
months of the reporting date is current. A balance sheet that does not split it
is wrong, and nobody notices until an auditor asks.

**Variable payments are not in it at all.** Operating expenses, taxes,
insurance and anything that moves with usage are expensed as incurred, never
capitalized into the liability. Sweeping CAM into the lease liability is one of
the commonest ASC 842 errors and it overstates the balance sheet.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

LEASE_COST = "Lease cost"
LEASE_LIABILITY = "Lease liability"
LEASE_LIABILITY_CURRENT = "Lease liability — current"
LEASE_LIABILITY_NONCURRENT = "Lease liability — non-current"
ROU_ASSET = "ROU asset"
ACCOUNTS_PAYABLE = "Accounts payable"

# Charge types that are variable consideration: expensed as incurred, never
# part of the lease liability.
VARIABLE = {"cam_estimate", "cam_reconciliation", "property_tax",
            "insurance", "late_fee", "credit_memo"}


@dataclass(frozen=True)
class Line:
    account: str
    debit: float = 0.0
    credit: float = 0.0


@dataclass
class MonthlyEntry:
    lease_id: str
    entity_id: str
    period: date
    straight_line_cost: float
    interest: float
    payment: float
    lines: List[Line] = field(default_factory=list)

    @property
    def total_debits(self) -> float:
        return round(sum(l.debit for l in self.lines), 2)

    @property
    def total_credits(self) -> float:
        return round(sum(l.credit for l in self.lines), 2)

    @property
    def balanced(self) -> bool:
        return abs(self.total_debits - self.total_credits) < 0.01

    def idempotency_key(self) -> str:
        return "asc842|%s|%s" % (self.lease_id, self.period.isoformat())


@dataclass
class Balances:
    entity_id: str
    as_of: date
    liability: float
    liability_current: float
    liability_noncurrent: float
    rou_asset: float

    @property
    def splits_correctly(self) -> bool:
        return abs((self.liability_current + self.liability_noncurrent)
                   - self.liability) < 0.01


def monthly_entry(schedule, period: date, lease_id: str, entity_id: str,
                  payable_account: str = ACCOUNTS_PAYABLE) -> Optional[MonthlyEntry]:
    """The entry for one lease in one month, from its amortization schedule."""
    row = schedule.period_for(period)
    if row is None:
        return None

    liability_reduction = round(row.payment - row.interest, 2)
    rou_amortization = round(row.straight_line_cost - row.interest, 2)

    entry = MonthlyEntry(
        lease_id=lease_id,
        entity_id=entity_id,
        period=period,
        straight_line_cost=row.straight_line_cost,
        interest=row.interest,
        payment=row.payment,
        lines=[
            Line(LEASE_COST, debit=row.straight_line_cost),
            Line(LEASE_LIABILITY, debit=liability_reduction),
            Line(ROU_ASSET, credit=rou_amortization),
            Line(payable_account, credit=row.payment),
        ],
    )
    return entry


def split_liability(schedule, as_of: date) -> Tuple[float, float]:
    """Current and non-current portions of the lease liability.

    Current is the principal that will be repaid in the twelve months after the
    reporting date — the payment less the interest accreted in each of those
    months, not the payments themselves.
    """
    closing = schedule.balances_at(as_of)["liability"]
    horizon = _add_months(as_of, 12)

    current = 0.0
    for row in schedule.periods:
        if as_of < row.period <= horizon:
            current += row.payment - row.interest

    current = round(min(current, closing), 2)
    return current, round(closing - current, 2)


def balances(schedules: Dict[str, object], entity_id: str, as_of: date,
             leases_in_entity: Optional[Iterable[str]] = None) -> Balances:
    """Subledger balances for one entity at a reporting date."""
    ids = list(leases_in_entity) if leases_in_entity is not None else list(schedules)

    liability = rou = current = noncurrent = 0.0
    for lease_id in ids:
        schedule = schedules.get(lease_id)
        if schedule is None:
            continue
        at = schedule.balances_at(as_of)
        liability += at["liability"]
        rou += at["rou"]
        c, n = split_liability(schedule, as_of)
        current += c
        noncurrent += n

    return Balances(
        entity_id=entity_id,
        as_of=as_of,
        liability=round(liability, 2),
        liability_current=round(current, 2),
        liability_noncurrent=round(noncurrent, 2),
        rou_asset=round(rou, 2),
    )


def entries_for_month(schedules: Dict[str, object], period: date,
                      entity_of: Dict[str, str]) -> List[MonthlyEntry]:
    out = []
    for lease_id, schedule in sorted(schedules.items()):
        entry = monthly_entry(schedule, period, lease_id,
                              entity_of.get(lease_id, "UNKNOWN"))
        if entry is not None:
            out.append(entry)
    return out


def is_variable(charge_type: str) -> bool:
    """Variable consideration is expensed as incurred, never capitalized.

    Sweeping operating expenses into the lease liability is one of the
    commonest ASC 842 errors, and it overstates the balance sheet.
    """
    return charge_type in VARIABLE


def _add_months(d: date, months: int) -> date:
    from datetime import timedelta

    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    last = 31 if month == 12 else (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))
