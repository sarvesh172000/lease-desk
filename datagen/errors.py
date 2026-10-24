"""The error catalog, as code.

Phase 1 plants six charges across January 2026: five that are wrong and must be
held, and one that looks wrong and is right. That last one is the important
test — a checker that holds everything unusual is no more useful than one that
holds nothing, and the eval scores false holds as failures.

Each entry records what was billed, what the lease supports, and the clause
that proves it. The clause text is matched back to a page and a bounding box by
the document pipeline, so the answer key says not just "this is wrong" but
"here is where the lease says so".

Only `eval/` may import this module. A test enforces that.
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

# Routing targets, per the Phase 2 resolver.
AUTO = "auto"
REGIONAL_MANAGER = "regional_manager"
CONTROLLER = "controller"

# Outcomes the checker may propose.
APPROVE = "approve"
HOLD = "hold"


@dataclass(frozen=True)
class PlantedError:
    error_id: str
    kind: str
    clinic_id: str
    period: date
    charge_type: str
    billed: float
    correct: float
    lease_section: str
    proof_quote: str
    expected_route: str
    expected_outcome: str
    description: str

    @property
    def variance(self) -> float:
        return round(self.billed - self.correct, 2)

    @property
    def is_error(self) -> bool:
        """False for the correct-but-odd charge."""
        return abs(self.variance) >= 0.01


JANUARY_2026: List[PlantedError] = [
    PlantedError(
        error_id="E1",
        kind="cam_estimate_above_lease",
        clinic_id="CLINIC-01",
        period=date(2026, 1, 1),
        charge_type="cam_estimate",
        billed=6_458.33,          # $12.50 psf
        correct=5_941.67,         # $11.50 psf, per the lease
        lease_section="4.1",
        proof_quote="Landlord’s current estimate of Operating Expenses is $11.50 per rentable square foot per annum",
        expected_route=REGIONAL_MANAGER,
        expected_outcome=HOLD,
        description="Operating expense estimate billed at $12.50 psf against a lease estimate of $11.50 psf.",
    ),
    PlantedError(
        error_id="E2",
        kind="duplicate_rent_invoice",
        clinic_id="CLINIC-01",
        period=date(2026, 1, 1),
        charge_type="base_rent",
        billed=19_626.65,         # a second invoice for the same month
        correct=0.00,
        lease_section="3.2",
        proof_quote="Base Rent shall be due and payable in advance on the first (1st) day of each calendar month during the Term",
        expected_route=REGIONAL_MANAGER,
        expected_outcome=HOLD,
        description="January base rent invoiced twice under two invoice numbers.",
    ),
    PlantedError(
        error_id="E3",
        kind="charge_for_unleased_suite",
        clinic_id="CLINIC-02",
        period=date(2026, 1, 1),
        charge_type="base_rent",
        billed=4_820.00,
        correct=0.00,
        lease_section="1.1",
        proof_quote="those certain premises designated as Suite 115",
        expected_route=REGIONAL_MANAGER,
        expected_outcome=HOLD,
        description="Rent billed for Suite 118, which is not the leased premises.",
    ),
    PlantedError(
        error_id="E4",
        kind="escalation_applied_early",
        clinic_id="CLINIC-03",
        period=date(2026, 1, 1),
        charge_type="base_rent",
        billed=17_270.11,         # the April 2026 rate
        correct=16_726.50,        # the rate in effect until 31 March
        lease_section="3.3",
        proof_quote="Commencing on the first anniversary of the Commencement Date and on each anniversary thereafter during the Term",
        expected_route=REGIONAL_MANAGER,
        expected_outcome=HOLD,
        description="Escalation applied on 1 January although the commencement anniversary is 1 April.",
    ),
    PlantedError(
        error_id="E5",
        kind="escalation_compounded_too_often",
        clinic_id="CLINIC-05",
        period=date(2026, 1, 1),
        billed=8_572.74,          # escalated again on 1 January
        correct=8_343.30,         # the October 2025 rate, good until September 2026
        charge_type="base_rent",
        lease_section="3.3",
        proof_quote="is not compounded more frequently than annually",
        expected_route=REGIONAL_MANAGER,
        expected_outcome=HOLD,
        description="Escalated twice in fifteen months: once on the October anniversary and again on 1 January.",
    ),
    PlantedError(
        error_id="E6",
        kind="correct_but_odd",
        clinic_id="CLINIC-04",
        period=date(2026, 1, 1),
        charge_type="base_rent",
        billed=13_680.00,
        correct=13_680.00,        # a $400 step, exactly as written
        lease_section="3.3",
        proof_quote="the Monthly Base Rent shall increase by $400.00 per month",
        expected_route=AUTO,
        expected_outcome=APPROVE,
        description=(
            "Rent rose $400.00 (3.01%) on 1 January. Looks like an unexplained "
            "increase; it is exactly the fixed step the lease specifies. Must not be held."
        ),
    ),
]


def for_period(period: date) -> List[PlantedError]:
    return [e for e in JANUARY_2026 if e.period == period]


def for_clinic(clinic_id: str, period: Optional[date] = None) -> List[PlantedError]:
    return [
        e for e in JANUARY_2026
        if e.clinic_id == clinic_id and (period is None or e.period == period)
    ]


def real_errors() -> List[PlantedError]:
    """Everything that should be held. Excludes the correct-but-odd charge."""
    return [e for e in JANUARY_2026 if e.is_error]
