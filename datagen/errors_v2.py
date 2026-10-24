"""The error catalog at full scale.

Phase 1 planted six errors in one month across five clinics. That is enough to
prove a checker runs; it is not enough to know whether one works. Six errors
can be caught by six special cases.

This plants roughly sixty across twenty-two types, spread over thirty clinics
and twelve months, alongside about twenty charges that look wrong and are
correct. The correct-but-odd ones matter as much as the errors: a checker that
holds everything unusual costs a controller more time than it saves, and the
eval scores a false hold as a failure.

Every entry is derived from the lease it belongs to, so "correct" is whatever
that clinic's own terms support — not a constant. Deterministic from the
company, as everything in `datagen` is.
"""

from dataclasses import dataclass
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

from .company import Company
from .errors import AUTO, CONTROLLER, HOLD, APPROVE, REGIONAL_MANAGER, PlantedError
from .leases import LeaseTerms

YEAR = 2026

# A charge type is only billed in certain months, so an error planted outside
# them never becomes a charge at all. These mirror datagen/year.py.
BILLED_IN = {
    "property_tax": (2, 8),
    "insurance": (6,),
    "cam_reconciliation": (3, 4),
}


@dataclass(frozen=True)
class ErrorType:
    kind: str
    charge_type: str
    section: str
    quote: str
    route: str
    outcome: str
    # (the natural amount, lease terms) -> what the landlord billed
    mutate: Callable[[float, LeaseTerms], float]
    description: str
    # True where the lease supports none of this charge: a second copy of a
    # month's rent, a suite we do not lease, a late fee on a payment that
    # arrived on time. The variance is then the whole billed amount.
    zero_supported: bool = False


def _pct(p):
    return lambda correct, terms: round(correct * (1 + p), 2)


def _flat(amount):
    return lambda correct, terms: round(correct + amount, 2)


def _next_step(correct, terms):
    """Bill next year's rent this year — the escalation-timing error."""
    steps = terms.rent_schedule()
    for a, b in zip(steps, steps[1:]):
        if abs(a.monthly_rent - correct) < 0.01:
            return b.monthly_rent
    return round(correct * 1.03, 2)


ERROR_TYPES: Tuple[ErrorType, ...] = (
    ErrorType("escalation_applied_early", "base_rent", "3.3",
              "Commencing on the first anniversary of the Commencement Date",
              REGIONAL_MANAGER, HOLD, _next_step,
              "Next lease year's rent billed before the anniversary."),
    ErrorType("escalation_compounded_too_often", "base_rent", "3.3",
              "is not compounded more frequently than annually",
              REGIONAL_MANAGER, HOLD, _pct(0.0275),
              "Escalation applied a second time within the same lease year."),
    ErrorType("cam_estimate_above_lease", "cam_estimate", "4.1",
              "Landlord's current estimate of Operating Expenses is",
              REGIONAL_MANAGER, HOLD, _pct(0.087),
              "Operating expense estimate above the rate the lease states."),
    ErrorType("duplicate_rent_invoice", "base_rent", "3.2",
              "Base Rent shall be due and payable in advance on the first (1st) day",
              REGIONAL_MANAGER, HOLD, lambda c, t: c,
              "The same month's rent invoiced twice.", zero_supported=True),
    ErrorType("charge_for_unleased_suite", "base_rent", "1.1",
              "those certain premises designated as",
              REGIONAL_MANAGER, HOLD, lambda c, t: round(c * 0.42, 2),
              "Rent billed for a suite that is not the demised premises.", zero_supported=True),
    ErrorType("abatement_not_applied", "base_rent", "3.1",
              "without prior notice or demand and without any setoff",
              CONTROLLER, HOLD, lambda c, t: c,
              "A rent abatement the lease grants was not applied."),
    ErrorType("amendment_not_reflected", "base_rent", "12.3",
              "This Lease may be amended only by a written instrument signed by both parties",
              CONTROLLER, HOLD, _pct(0.128),
              "Rent billed on superseded terms after an executed amendment."),
    ErrorType("wrong_pro_rata_denominator", "cam_estimate", "1.2",
              "Tenant's Proportionate Share is",
              REGIONAL_MANAGER, HOLD, _pct(0.19),
              "Share computed on a denominator the lease does not stipulate."),
    ErrorType("controllable_cap_breach", "cam_estimate", "4.5",
              "shall not increase by more than five percent (5%) per calendar year",
              REGIONAL_MANAGER, HOLD, _pct(0.142),
              "Controllable operating expenses above the cap."),
    ErrorType("excluded_capital_expense", "cam_estimate", "4.3",
              "Operating Expenses shall expressly exclude: (a) capital improvements",
              CONTROLLER, HOLD, _flat(2_480.00),
              "A capital replacement passed through as an operating expense."),
    ErrorType("management_fee_above_cap", "cam_estimate", "4.4",
              "shall not exceed four percent (4%) of gross rental receipts",
              REGIONAL_MANAGER, HOLD, _flat(1_150.00),
              "Management fee above the cap the lease sets."),
    ErrorType("same_cam_line_billed_twice", "cam_estimate", "4.8",
              "no single expense may be allocated more than once",
              REGIONAL_MANAGER, HOLD, _flat(3_640.00),
              "One vendor line allocated to two suites in the same center."),
    ErrorType("insurance_billed_twice", "insurance", "4.2",
              "including utilities serving the Common Areas, janitorial",
              REGIONAL_MANAGER, HOLD, lambda c, t: round(c * 2, 2),
              "The insurance pass-through billed twice in one period."),
    ErrorType("tax_at_wrong_share", "property_tax", "4.8",
              "No Operating Expense shall be allocated to Tenant in excess",
              REGIONAL_MANAGER, HOLD, _pct(0.23),
              "Property tax allocated above the proportionate share."),
    ErrorType("late_fee_on_ontime_payment", "late_fee", "3.4",
              "A late charge shall not be assessed on any installment actually received",
              REGIONAL_MANAGER, HOLD, lambda c, t: round(t.base_rent_monthly * 0.05, 2),
              "Late charge assessed on a payment received on time.", zero_supported=True),
    ErrorType("true_up_arithmetic_error", "cam_reconciliation", "4.6",
              "a statement setting forth the actual Operating Expenses",
              CONTROLLER, HOLD, _flat(1_875.00),
              "The reconciliation's arithmetic does not foot."),
    ErrorType("credit_memo_never_applied", "credit_memo", "4.6",
              "Any overpayment shall be credited against the next installments",
              CONTROLLER, HOLD, lambda c, t: 0.0,
              "A credit issued by the landlord was never applied.", zero_supported=True),
)

# Charges that look wrong and are right. A checker that holds these fails.
ODD_BUT_CORRECT: Tuple[Tuple[str, str, str, str], ...] = (
    ("fixed_step_looks_like_escalation", "base_rent", "3.3",
     "A flat dollar step that reads as an unexplained percentage increase."),
    ("first_escalation_after_long_term", "base_rent", "3.3",
     "The first escalation on a lease that ran years at its initial rent."),
    ("partial_month_prorated", "base_rent", "3.2",
     "A prorated part-month that does not match any schedule row."),
    ("annual_insurance_in_one_period", "insurance", "4.2",
     "The insurance pass-through billed annually rather than monthly."),
)


def build_catalog(company: Company, leases: List[LeaseTerms],
                  year: int = YEAR) -> List[PlantedError]:
    """Roughly sixty errors and twenty correct-but-odd charges across the year.

    Placement is deterministic: a clinic's number and the month decide which
    type lands where, so the same company always produces the same catalog and
    no month is left clean by accident.
    """
    by_clinic: Dict[str, LeaseTerms] = {t.clinic_id: t for t in leases}
    out: List[PlantedError] = []
    counter = 0

    for index, terms in enumerate(leases):
        number = int(terms.clinic_id.split("-")[-1])
        # Two errors per clinic, in months derived from its number so they
        # spread across the year rather than clustering.
        for slot in range(2):
            spec_peek = ERROR_TYPES[(number + slot * 3) % len(ERROR_TYPES)]
            month = _month_for(spec_peek.charge_type, number, slot)
            period = date(year, month, 1)
            if not (terms.commencement <= period <= terms.expiration):
                continue
            spec = ERROR_TYPES[(number + slot * 3) % len(ERROR_TYPES)]
            natural = _correct_for(spec, terms, period, company)
            if natural is None:
                continue
            correct = 0.0 if spec.zero_supported else natural
            counter += 1
            out.append(PlantedError(
                error_id="E2-%03d" % counter,
                kind=spec.kind,
                clinic_id=terms.clinic_id,
                period=period,
                charge_type=spec.charge_type,
                billed=spec.mutate(natural, terms),
                correct=correct,
                lease_section=spec.section,
                proof_quote=spec.quote,
                expected_route=spec.route,
                expected_outcome=spec.outcome,
                description=spec.description,
            ))

    # The correct-but-odd charges. There are nearly as many of these as there
    # are errors, deliberately: a checker that holds everything unusual is no
    # more useful than one that holds nothing, and the eval scores a false hold
    # as a failure. Two thirds of clinics carry one.
    for index, terms in enumerate(leases):
        if index % 3 == 2:
            continue
        number = int(terms.clinic_id.split("-")[-1])
        kind, charge_type, section, description = ODD_BUT_CORRECT[
            number % len(ODD_BUT_CORRECT)]
        month = _month_for(charge_type, number, 0)
        period = date(year, month, 1)
        if not (terms.commencement <= period <= terms.expiration):
            continue
        correct = _correct_for(None, terms, period, company, charge_type)
        if correct is None:
            continue
        counter += 1
        out.append(PlantedError(
            error_id="E2-%03d" % counter,
            kind=kind,
            clinic_id=terms.clinic_id,
            period=period,
            charge_type=charge_type,
            billed=correct,
            correct=correct,
            lease_section=section,
            proof_quote="the Monthly Base Rent shall increase by",
            expected_route=AUTO,
            expected_outcome=APPROVE,
            description=description,
        ))

    return out


def _month_for(charge_type: str, number: int, slot: int) -> int:
    """A month in which this charge type is actually billed."""
    if charge_type == "cam_reconciliation":
        # Landlords split reconciliation across March and April by clinic;
        # year.py decides which, so the error has to follow the same rule or
        # it lands in a month that clinic has no reconciliation in.
        return 3 if number % 2 == 0 else 4
    months = BILLED_IN.get(charge_type)
    if months:
        return months[(number + slot) % len(months)]
    return ((number * 5 + slot * 7) % 12) + 1


def _correct_for(spec: Optional[ErrorType], terms: LeaseTerms, period: date,
                 company: Company, charge_type: Optional[str] = None) -> Optional[float]:
    """What the lease supports for this charge type in this month."""
    kind = charge_type or (spec.charge_type if spec else "base_rent")
    if kind == "base_rent":
        return terms.rent_for(period) or None
    if kind == "cam_estimate":
        return terms.cam_estimate_monthly
    if kind == "insurance":
        return round(terms.rsf * 0.95 / 12, 2)
    if kind == "property_tax":
        return round(terms.rsf * 2.90 / 12, 2)
    if kind == "late_fee":
        return 0.0
    if kind == "cam_reconciliation":
        return round(terms.cam_estimate_monthly * 12 * 0.08, 2)
    if kind == "credit_memo":
        return round(terms.cam_estimate_monthly * 0.6, 2)
    return None


def real_errors(catalog: List[PlantedError]) -> List[PlantedError]:
    return [e for e in catalog if e.is_error]


def odd_but_correct(catalog: List[PlantedError]) -> List[PlantedError]:
    return [e for e in catalog if not e.is_error]


def by_kind(catalog: List[PlantedError]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for e in catalog:
        out[e.kind] = out.get(e.kind, 0) + 1
    return out
