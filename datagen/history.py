"""2025: the year before the system existed.

Twelve months of invoices and payments that mostly tie. It matters for three
reasons:

  - **The abstraction agent cross-checks against it.** A rent schedule read out
    of a lease should reproduce what was actually paid last year. When it does
    not, that is a disagreement between two sources and the lease goes to a
    human rather than being silently believed.
  - **Opening balances are real.** A January 2026 liability means nothing
    unless the lease has been running.
  - **The team's habits are in it.** Phase 2 learns policies from how these
    charges were treated, so the few that were wrong and paid anyway are
    deliberate: they are what "the previous accountant always approved this"
    looks like in data.

Mostly correct, not perfectly correct. A clean year teaches nothing.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

from .company import Company, build_company
from .errors import AUTO, HOLD, PlantedError, REGIONAL_MANAGER
from .leases import LeaseTerms, build_leases
from .month import Invoice, Payment, build_month, build_payments

YEAR = 2025


# Charges that were wrong in 2025 and paid anyway. Phase 2 reads these as the
# team's habits; Phase 1 only needs them to exist so the year is not pristine.
PAST_MISTAKES: List[PlantedError] = [
    PlantedError(
        error_id="H1",
        kind="cam_estimate_above_lease",
        clinic_id="STORE-03",
        period=date(2025, 4, 1),
        charge_type="cam_estimate",
        billed=4_612.50,          # $10.25 psf
        correct=4_387.50,         # $9.75 psf per the lease
        lease_section="4.1",
        proof_quote="estimate of Operating Expenses is $9.75 per rentable square foot per annum",
        expected_route=REGIONAL_MANAGER,
        expected_outcome=HOLD,
        description="April 2025 operating expense estimate billed $225 over the lease. Paid.",
    ),
    PlantedError(
        error_id="H2",
        kind="escalation_applied_early",
        clinic_id="STORE-02",
        period=date(2025, 6, 1),
        charge_type="base_rent",
        billed=9_700.00,          # the July rate, billed in June
        correct=9_425.00,
        lease_section="3.3",
        proof_quote="Commencing on the first anniversary of the Commencement Date",
        expected_route=REGIONAL_MANAGER,
        expected_outcome=HOLD,
        description="June 2025 rent billed at the July step. Paid.",
    ),
]


@dataclass
class History:
    invoices: List[Invoice]
    payments: List[Payment]
    mistakes: List[PlantedError]

    @property
    def months(self) -> int:
        return len({(i.period.year, i.period.month) for i in self.invoices})

    def total_billed(self) -> float:
        return round(sum(i.total() for i in self.invoices), 2)

    def total_overbilled(self) -> float:
        return round(sum(m.variance for m in self.mistakes), 2)

    def payments_for(self, lease_id: str, charge_type: str = "base_rent") -> List[Payment]:
        return [p for p in self.payments
                if p.lease_id == lease_id and p.charge_type == charge_type]


def build_history(
    company: Optional[Company] = None,
    leases: Optional[List[LeaseTerms]] = None,
    year: int = YEAR,
) -> History:
    """Every month of `year` for every lease that had commenced."""
    company = company or build_company()
    leases = leases if leases is not None else build_leases(company)

    invoices: List[Invoice] = []
    for month in range(1, 13):
        period = date(year, month, 1)
        running = [l for l in leases if l.commencement <= period <= l.expiration]
        if not running:
            continue
        planted = [m for m in PAST_MISTAKES if m.period == period]
        invoices.extend(build_month(period, company, running, errors=planted))

    return History(
        invoices=invoices,
        payments=build_payments(invoices, company),
        mistakes=list(PAST_MISTAKES),
    )


def paid_rent_by_month(history: History, lease_id: str) -> Dict[str, float]:
    """What was actually paid as rent each month — the series the abstraction
    agent replays its extracted schedule against."""
    out: Dict[str, float] = {}
    for payment in history.payments_for(lease_id, "base_rent"):
        key = payment.period.strftime("%Y-%m")
        out[key] = round(out.get(key, 0.0) + payment.amount, 2)
    return out


def cross_check(terms: LeaseTerms, history: History) -> List[Tuple[str, float, float]]:
    """Replay a lease's rent schedule over the history.

    Returns every month where the schedule and the cash disagree. A non-empty
    result does not mean the lease was read wrongly — it may mean the landlord
    billed wrongly — which is exactly why it opens a work item instead of
    picking a side.
    """
    paid = paid_rent_by_month(history, terms.lease_id)
    out = []
    for key, amount in sorted(paid.items()):
        period = date(int(key[:4]), int(key[5:]), 1)
        due = terms.rent_for(period)
        if abs(amount - due) > 1.00:
            out.append((key, due, amount))
    return out
