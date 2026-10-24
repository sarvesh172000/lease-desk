"""What the lease supports for a given month. Deterministic, no model.

This is the other half of every comparison the checker makes. The landlord's
invoice says one thing; this says what the lease says. Neither consults the
other.

A `LeaseRule` is a *confirmed* lease: terms a human has signed off, each
carrying the clause that proves it. Unconfirmed abstractions never reach here —
that is what the citation check in `agents/abstraction.py` is for.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

TOLERANCE = 1.00  # dollars; below this a difference is rounding, not a variance


@dataclass(frozen=True)
class Proof:
    """Where in the lease a term is stated."""
    section: str
    quote: str
    page: Optional[int] = None
    box: Optional[Tuple[float, float, float, float]] = None


@dataclass(frozen=True)
class RentStep:
    start: date
    end: date
    monthly_rent: float


@dataclass
class LeaseRule:
    lease_id: str
    clinic_id: str
    suite: str
    commencement: date
    expiration: date
    steps: List[RentStep]
    cam_estimate_monthly: float
    cam_estimate_psf_annual: float
    proof: Dict[str, Proof] = field(default_factory=dict)

    def rent_for(self, period: date) -> float:
        for step in self.steps:
            if step.start <= period <= step.end:
                return step.monthly_rent
        return 0.0

    def covers(self, period: date) -> bool:
        return self.commencement <= period <= self.expiration

    def proof_for(self, field_name: str) -> Optional[Proof]:
        return self.proof.get(field_name)


@dataclass(frozen=True)
class Expected:
    lease_id: str
    clinic_id: str
    period: date
    base_rent: float
    cam_estimate: float

    def for_type(self, charge_type: str) -> float:
        if charge_type == "base_rent":
            return self.base_rent
        if charge_type == "cam_estimate":
            return self.cam_estimate
        return 0.0


def expected(rule: LeaseRule, period: date) -> Expected:
    """Base rent and operating expense estimate the lease supports this month."""
    if not rule.covers(period):
        return Expected(rule.lease_id, rule.clinic_id, period, 0.0, 0.0)
    return Expected(
        lease_id=rule.lease_id,
        clinic_id=rule.clinic_id,
        period=period,
        base_rent=round(rule.rent_for(period), 2),
        cam_estimate=round(rule.cam_estimate_monthly, 2),
    )


def within_tolerance(billed: float, supported: float) -> bool:
    return abs(billed - supported) <= TOLERANCE
