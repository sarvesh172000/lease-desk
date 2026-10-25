"""Lease terms for the five Northbay clinics, and the rent schedules they imply.

The terms here are the *truth*. The lease PDF renders them into prose and
tables; the abstraction agent reads the PDF and tries to recover them; the eval
compares what it recovered against this file. Nothing downstream may import
this module except `eval/` and the renderer — that is what keeps the benchmark
honest.

CLINIC-01 deliberately reproduces the Store 14 figures the demo was rehearsed
on: $18,500 commencing 2024-01-01 with 3% annual escalation, which steps to
$19,055, $19,626.65, $20,215.45 and $20,821.91. The amendment that cuts it to
$17,400 and extends the term three years is the moment.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from .company import Company, build_company

# IBR by remaining term at commencement, documented as an assumption and shown
# on every schedule. Phase 2 replaces this with a real table.
IBR_BY_TERM_YEARS = {3: 0.0665, 4: 0.0695, 5: 0.0720, 6: 0.0745, 8: 0.0780}


@dataclass(frozen=True)
class Escalation:
    kind: str  # "fixed_percent" | "fixed_step"
    amount: float  # 0.03 for 3%, or 275.00 for a dollar step
    anniversary_month: int

    def describe(self) -> str:
        if self.kind == "fixed_percent":
            return "%.2f%% per annum" % (self.amount * 100)
        return "$%s per month" % _money(self.amount)


@dataclass(frozen=True)
class RenewalOption:
    count: int
    years: int
    notice_days: int


@dataclass(frozen=True)
class RentStep:
    start: date
    end: date
    monthly_rent: float


@dataclass(frozen=True)
class LeaseTerms:
    lease_id: str
    clinic_id: str
    landlord_id: str
    commencement: date
    expiration: date
    rsf: int
    base_rent_monthly: float
    escalation: Escalation
    cam_estimate_psf_annual: float
    security_deposit: float
    renewal: RenewalOption
    discount_rate: float
    amendment: Optional["Amendment"] = None

    @property
    def term_years(self) -> int:
        return round((self.expiration - self.commencement).days / 365.25)

    @property
    def cam_estimate_monthly(self) -> float:
        return round(self.rsf * self.cam_estimate_psf_annual / 12, 2)

    def rent_schedule(self) -> List[RentStep]:
        """One step per escalation year, the last truncated at expiration.

        With an amendment, the original schedule is cut short on the day before
        the amendment takes effect and a fresh schedule runs from the new base.
        """
        if self.amendment is None:
            return self._steps_from(
                self.commencement, self.expiration,
                self.base_rent_monthly, self.escalation)

        cut = self.amendment.effective - timedelta(days=1)
        before = self._steps_from(
            self.commencement, cut, self.base_rent_monthly, self.escalation)
        after = self._steps_from(
            self.amendment.effective,
            self.amendment.new_expiration or self.expiration,
            self.amendment.new_base_rent
            if self.amendment.new_base_rent is not None else self.base_rent_monthly,
            self.amendment.new_escalation or self.escalation,
        )
        return before + after

    def _steps_from(self, start: date, end: date, rent: float,
                    escalation: "Escalation") -> List[RentStep]:
        steps: List[RentStep] = []
        while start <= end:
            stop = min(_add_months(start, 12) - timedelta(days=1), end)
            steps.append(RentStep(start, stop, round(rent, 2)))
            start = stop + timedelta(days=1)
            if escalation.kind == "fixed_percent":
                rent = round(rent * (1 + escalation.amount), 2)
            else:
                rent = round(rent + escalation.amount, 2)
        return steps

    def rent_for(self, period: date) -> float:
        for step in self.rent_schedule():
            if step.start <= period <= step.end:
                return step.monthly_rent
        return 0.0

    def to_engine_json(self, company: Company) -> dict:
        """The shape `leasedesk.models.load_lease` already reads."""
        clinic = company.clinic(self.clinic_id)
        landlord = company.landlord(self.landlord_id)
        return {
            "lease_id": self.lease_id,
            "location": "%s — %s" % (clinic.name, clinic.suite),
            "lessor": landlord.name,
            "commencement": self.commencement.isoformat(),
            "end": self.expiration.isoformat(),
            "discount_rate": self.discount_rate,
            "classification": "operating",
            "prepaid": 0.0,
            "incentives": 0.0,
            "steps": [
                {
                    "start": s.start.isoformat(),
                    "end": s.end.isoformat(),
                    "monthly_rent": s.monthly_rent,
                }
                for s in self.rent_schedule()
            ],
            "amendments": [],
        }


# Lease terms for the clinics beyond the Phase 1 five, cycled deterministically
# so every run produces the same leases while no two read alike.
#
# The cycle lengths are deliberately co-prime. Square footage runs on 8 in
# company.py; indexing rent per square foot on 8 as well made the two move
# together, so thirty leases carried only thirteen distinct rents and the
# documents were near-duplicates. An extraction benchmark on near-duplicates
# measures pattern-matching, not reading.
_PSF_CYCLE = (34.50, 29.75, 41.00, 26.25, 37.80, 31.40, 44.20)        # 7
_TERM_YEARS_CYCLE = (5, 7, 3, 10, 4, 6)                               # 6
_START_MONTHS = ((2023, 2), (2024, 5), (2024, 9), (2025, 3), (2023, 11))  # 5
_ESCALATIONS = (                                                      # 7
    ("fixed_percent", 0.030), ("fixed_step", 325.00), ("fixed_percent", 0.0275),
    ("fixed_step", 450.00), ("fixed_percent", 0.035), ("fixed_percent", 0.025),
    ("fixed_step", 280.00),
)
_CAM_PSF_CYCLE = (10.25, 12.75, 8.90, 11.40, 9.60, 13.20, 10.80, 12.10, 9.15, 11.95, 8.40)  # 11
_RENEWALS = (
    RenewalOption(1, 5, 270), RenewalOption(2, 3, 180), RenewalOption(1, 3, 240),
    RenewalOption(2, 5, 365), RenewalOption(1, 5, 180), RenewalOption(0, 0, 0),
)


def build_leases(company: Optional[Company] = None) -> List[LeaseTerms]:
    company = company or build_company()
    specs = [
        # CLINIC-01 reproduces the rehearsed Store 14 numbers exactly.
        ("LEASE-01", "CLINIC-01", date(2024, 1, 1), date(2028, 12, 31),
         18_500.00, Escalation("fixed_percent", 0.03, 1), 11.50, 37_000.00,
         RenewalOption(1, 3, 270)),
        ("LEASE-02", "CLINIC-02", date(2023, 7, 1), date(2028, 6, 30),
         9_150.00, Escalation("fixed_step", 275.00, 7), 11.50, 18_300.00,
         RenewalOption(2, 3, 180)),
        ("LEASE-03", "CLINIC-03", date(2024, 4, 1), date(2029, 3, 31),
         16_200.00, Escalation("fixed_percent", 0.0325, 4), 9.75, 32_400.00,
         RenewalOption(1, 5, 270)),
        ("LEASE-04", "CLINIC-04", date(2025, 1, 1), date(2029, 12, 31),
         13_280.00, Escalation("fixed_step", 400.00, 1), 9.75, 26_560.00,
         RenewalOption(2, 3, 180)),
        ("LEASE-05", "CLINIC-05", date(2024, 10, 1), date(2027, 9, 30),
         8_120.00, Escalation("fixed_percent", 0.0275, 10), 9.75, 16_240.00,
         RenewalOption(1, 3, 120)),
    ]

    known = {spec[1] for spec in specs}
    for index, clinic in enumerate(company.clinics):
        if clinic.clinic_id in known:
            continue
        specs.append(_derived_spec(index, clinic))

    leases = []
    for lease_id, clinic_id, start, end, rent, esc, cam, deposit, renewal in specs:
        years = round((end - start).days / 365.25)
        leases.append(
            LeaseTerms(
                lease_id=lease_id,
                clinic_id=clinic_id,
                landlord_id=company.center(company.clinic(clinic_id).center_id).landlord_id,
                commencement=start,
                expiration=end,
                rsf=company.clinic(clinic_id).rsf,
                base_rent_monthly=rent,
                escalation=esc,
                cam_estimate_psf_annual=cam,
                security_deposit=deposit,
                renewal=renewal,
                discount_rate=IBR_BY_TERM_YEARS.get(years, 0.0720),
            )
        )
    return leases


def _derived_spec(index: int, clinic):
    """Terms for a clinic beyond the Phase 1 five.

    Deterministic from the clinic's position, so the same company always
    produces the same leases, and varied enough that an extractor cannot
    succeed by pattern-matching one shape.
    """
    number = int(clinic.clinic_id.split("-")[1])

    year, month = _START_MONTHS[number % len(_START_MONTHS)]
    start = date(year, month, 1)
    years = _TERM_YEARS_CYCLE[number % len(_TERM_YEARS_CYCLE)]
    end = _add_months(start, years * 12) - timedelta(days=1)

    psf = _PSF_CYCLE[number % len(_PSF_CYCLE)]
    monthly = round(clinic.rsf * psf / 12, 2)
    kind, amount = _ESCALATIONS[number % len(_ESCALATIONS)]

    return (
        "LEASE-%02d" % number,
        clinic.clinic_id,
        start,
        end,
        monthly,
        Escalation(kind, amount, start.month),
        _CAM_PSF_CYCLE[number % len(_CAM_PSF_CYCLE)],
        round(monthly * 2, 2),
        _RENEWALS[number % len(_RENEWALS)],
    )


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def _money(value: float) -> str:
    return "{:,.2f}".format(value)


@dataclass(frozen=True)
class Amendment:
    """A change to a lease that accounting was never told about.

    This is the whole product in one object. It was signed, it was filed by
    facilities, the landlord invoiced the new amount and AP paid it — and the
    rent schedule in the books still runs the old terms.
    """

    amendment_id: str
    lease_id: str
    effective: date
    executed: date
    summary: str
    new_expiration: Optional[date] = None
    new_base_rent: Optional[float] = None
    new_escalation: Optional[Escalation] = None
    # The sentence in the source document that states the change.
    proof_quote: str = ""

    def applies_to(self, period: date) -> bool:
        return period >= self.effective


# CLINIC-01's second amendment: three more years in exchange for lower rent.
# Effective 1 July 2026, which is where the books start disagreeing with cash.
SECOND_AMENDMENT = Amendment(
    amendment_id="LEASE-01-A2",
    lease_id="LEASE-01",
    effective=date(2026, 7, 1),
    executed=date(2026, 6, 18),
    summary=("Term extended three years to 31 December 2031. Base rent reduced "
             "to $17,400.00 per month effective 1 July 2026, with the annual "
             "escalation reduced from 3.00% to 2.50%."),
    new_expiration=date(2031, 12, 31),
    new_base_rent=17_400.00,
    new_escalation=Escalation("fixed_percent", 0.025, 7),
    proof_quote=("Base rent reduced to $17,400 per month effective July 1, 2026"),
)

AMENDMENTS: List[Amendment] = [SECOND_AMENDMENT]


def amendment_for(lease_id: str) -> Optional[Amendment]:
    for amendment in AMENDMENTS:
        if amendment.lease_id == lease_id:
            return amendment
    return None


def amended(terms: "LeaseTerms", amendment: Amendment) -> "LeaseTerms":
    """The lease as it stands after an amendment.

    Rent before the effective date is untouched; the schedule restarts from the
    new base on the effective date and escalates on its own anniversary.
    """
    return LeaseTerms(
        lease_id=terms.lease_id,
        clinic_id=terms.clinic_id,
        landlord_id=terms.landlord_id,
        commencement=terms.commencement,
        expiration=amendment.new_expiration or terms.expiration,
        rsf=terms.rsf,
        base_rent_monthly=terms.base_rent_monthly,
        escalation=terms.escalation,
        cam_estimate_psf_annual=terms.cam_estimate_psf_annual,
        security_deposit=terms.security_deposit,
        renewal=terms.renewal,
        discount_rate=terms.discount_rate,
        amendment=amendment,
    )
