"""A full year of billing, the way a landlord actually sends it.

Rent and the operating expense estimate arrive monthly together, because that
is what these leases say: Article 4.1 makes the estimate "payable in monthly
installments concurrently with Base Rent". The prior year's reconciliation
lands in March or April, once the landlord has closed its own books — which is
why a CAM dispute is always about a year you have already closed. Tax and
insurance pass-throughs come when the bills do. Credit memos and late notices
arrive whenever.

Twelve months of that across thirty clinics is around eight hundred charges,
which is the point: a checker that works on six charges in one month has not
been tested.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from .company import Company, build_company
from .errors import PlantedError
from .errors_v2 import build_catalog
from .leases import LeaseTerms, build_leases
from .month import Invoice, Payment, build_month, build_payments

# The prior year's reconciliation, once the landlord has closed its books.
RECONCILIATION_MONTHS = (3, 4)
# Tax and insurance pass-throughs follow the billing cycle, not the rent.
TAX_MONTHS = (2, 8)
INSURANCE_MONTHS = (6,)


@dataclass
class Year:
    year: int
    invoices: List[Invoice]
    payments: List[Payment]
    catalog: List[PlantedError] = field(default_factory=list)

    @property
    def charges(self) -> int:
        return sum(len(i.charges) for i in self.invoices)

    def total_billed(self) -> float:
        return round(sum(i.total() for i in self.invoices), 2)

    def by_month(self) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for invoice in self.invoices:
            out[invoice.period.month] = out.get(invoice.period.month, 0) + len(invoice.charges)
        return out

    def by_charge_type(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for invoice in self.invoices:
            for charge in invoice.charges:
                out[charge.charge_type] = out.get(charge.charge_type, 0) + 1
        return out

    def month(self, month: int) -> List[Invoice]:
        return [i for i in self.invoices if i.period.month == month]


def build_year(
    year: int = 2026,
    company: Optional[Company] = None,
    leases: Optional[List[LeaseTerms]] = None,
    catalog: Optional[List[PlantedError]] = None,
) -> Year:
    company = company or build_company()
    leases = leases if leases is not None else build_leases(company)
    catalog = catalog if catalog is not None else build_catalog(company, leases, year)

    invoices: List[Invoice] = []
    for month in range(1, 13):
        period = date(year, month, 1)
        running = [t for t in leases if t.commencement <= period <= t.expiration]
        if not running:
            continue

        planted = [e for e in catalog if e.period == period]
        invoices.extend(build_month(period, company, running, errors=planted))
        invoices.extend(_periodic(period, company, running, planted))

    return Year(year, invoices, build_payments(invoices, company), catalog)


def _periodic(period: date, company: Company, leases: List[LeaseTerms],
              planted: List[PlantedError]) -> List[Invoice]:
    """The charges that are not monthly rent."""
    out: List[Invoice] = []
    month = period.month

    for terms in leases:
        extras = []

        if month in TAX_MONTHS:
            extras.append(("property_tax",
                           "Real property tax pass-through — %s" % period.strftime("%B %Y"),
                           round(terms.rsf * 2.90 / len(TAX_MONTHS), 2)))

        if month in INSURANCE_MONTHS:
            extras.append(("insurance",
                           "Insurance pass-through — %d" % period.year,
                           round(terms.rsf * 0.95, 2)))

        if month in RECONCILIATION_MONTHS and _reconciles(terms, month):
            extras.append(("cam_reconciliation",
                           "Operating expense reconciliation — %d" % (period.year - 1),
                           round(terms.cam_estimate_monthly * 12 * 0.08, 2)))

        for charge_type, description, amount in extras:
            override = _planted_for(planted, terms.clinic_id, charge_type)
            out.append(_single_charge_invoice(
                company, terms, period, charge_type, description,
                override.billed if override else amount,
                override.error_id if override else None))

    # Late notices and credit memos, planted only.
    for error in planted:
        if error.charge_type not in ("late_fee", "credit_memo") or not error.is_error:
            continue
        terms = next((t for t in leases if t.clinic_id == error.clinic_id), None)
        if terms is None:
            continue
        out.append(_single_charge_invoice(
            company, terms, period, error.charge_type,
            "Late charge — %s" % period.strftime("%B %Y") if error.charge_type == "late_fee"
            else "Credit memo — operating expense overpayment",
            error.billed, error.error_id))

    return out


def _reconciles(terms: LeaseTerms, month: int) -> bool:
    """Landlords split reconciliation across March and April; which month a
    clinic falls in depends on its landlord, not on chance."""
    return (int(terms.clinic_id.split("-")[-1]) % 2 == 0) == (month == 3)


def _planted_for(planted, clinic_id: str, charge_type: str):
    """The error that changes this charge, if any.

    A correct-but-odd charge is excluded: it overrides nothing, and tagging it
    would make a charge the checker is supposed to approve look like a planted
    error to the eval.
    """
    for error in planted:
        if (error.clinic_id == clinic_id and error.charge_type == charge_type
                and error.is_error):
            return error
    return None


def _single_charge_invoice(company: Company, terms: LeaseTerms, period: date,
                           charge_type: str, description: str, amount: float,
                           error_id) -> Invoice:
    from .month import Charge

    clinic = company.clinic(terms.clinic_id)
    prefix = terms.landlord_id.split("-")[-1][:5].upper()
    invoice_id = "%s-%s-%s-%s" % (
        prefix, period.strftime("%Y%m"), charge_type[:3].upper(),
        terms.clinic_id.split("-")[-1])

    invoice = Invoice(
        invoice_id=invoice_id,
        landlord_id=terms.landlord_id,
        clinic_id=terms.clinic_id,
        period=period,
        issue_date=period - timedelta(days=10),
        due_date=period,
    )
    invoice.charges.append(Charge(
        charge_id="%s-L1" % invoice_id,
        invoice_id=invoice_id,
        clinic_id=terms.clinic_id,
        lease_id=terms.lease_id,
        landlord_id=terms.landlord_id,
        period=period,
        charge_type=charge_type,
        description=description,
        suite=clinic.suite,
        amount=round(amount, 2),
        error_id=error_id,
    ))
    return invoice
