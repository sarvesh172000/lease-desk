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

    @property
    def term_years(self) -> int:
        return round((self.expiration - self.commencement).days / 365.25)

    @property
    def cam_estimate_monthly(self) -> float:
        return round(self.rsf * self.cam_estimate_psf_annual / 12, 2)

    def rent_schedule(self) -> List[RentStep]:
        """One step per escalation year, the last truncated at expiration."""
        steps: List[RentStep] = []
        rent = self.base_rent_monthly
        start = self.commencement
        while start <= self.expiration:
            end = min(_add_months(start, 12) - timedelta(days=1), self.expiration)
            steps.append(RentStep(start, end, round(rent, 2)))
            start = end + timedelta(days=1)
            if self.escalation.kind == "fixed_percent":
                rent = round(rent * (1 + self.escalation.amount), 2)
            else:
                rent = round(rent + self.escalation.amount, 2)
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
