"""One month of landlord invoices, and the cash that went out against them.

The monthly cycle this models is the one that actually goes wrong: the landlord
invoices, AP pays the invoice because it looks ordinary, and nobody compares
either of them to the lease. Accounting finds out later, or not at all.

So the generator produces three things that disagree on purpose:

  - **Invoices** — what the landlord billed, carrying the planted errors.
  - **The AP export** — what AP coded and approved, which follows the invoice.
  - **The bank export** — what actually left the account, which follows AP.

Nothing here consults the lease. That is the point: `engine/charges.py`
computes what the lease supports, and the checker compares the two.
"""

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from .company import Company, build_company
from .errors import PlantedError, for_period
from .leases import LeaseTerms, build_leases

CHARGE_LABELS = {
    "base_rent": "Base Rent",
    "cam_estimate": "Operating Expense Estimate",
}


@dataclass(frozen=True)
class Charge:
    charge_id: str
    invoice_id: str
    clinic_id: str
    lease_id: str
    landlord_id: str
    period: date
    charge_type: str
    description: str
    suite: str
    amount: float
    error_id: Optional[str] = None


@dataclass
class Invoice:
    invoice_id: str
    landlord_id: str
    clinic_id: str
    period: date
    issue_date: date
    due_date: date
    charges: List[Charge] = field(default_factory=list)
    document_sha256: Optional[str] = None

    def total(self) -> float:
        return round(sum(c.amount for c in self.charges), 2)

    def period_label(self) -> str:
        return self.period.strftime("%B %Y")


@dataclass(frozen=True)
class Payment:
    payment_id: str
    period: date
    paid_on: date
    clinic_id: str
    lease_id: str
    charge_type: str
    amount: float
    reference: str
    counterparty: str
    invoice_id: str


def build_month(
    period: date,
    company: Optional[Company] = None,
    leases: Optional[List[LeaseTerms]] = None,
    errors: Optional[List[PlantedError]] = None,
) -> List[Invoice]:
    """Invoices for one month, with the planted errors applied."""
    company = company or build_company()
    leases = leases if leases is not None else build_leases(company)
    errors = errors if errors is not None else for_period(period)

    by_clinic: Dict[str, List[PlantedError]] = {}
    for err in errors:
        by_clinic.setdefault(err.clinic_id, []).append(err)

    issue_date = _previous_month_day(period, 20)
    invoices: List[Invoice] = []
    counter = 0

    for lease in leases:
        clinic = company.clinic(lease.clinic_id)
        landlord_id = lease.landlord_id
        planted = by_clinic.get(lease.clinic_id, [])
        counter += 1
        invoice = Invoice(
            invoice_id=_invoice_id(company, landlord_id, period, counter),
            landlord_id=landlord_id,
            clinic_id=lease.clinic_id,
            period=period,
            issue_date=issue_date,
            due_date=period,
        )

        # Base rent: the lease amount unless an error overrides it.
        rent = lease.rent_for(period)
        rent_error = _find(planted, "base_rent", override_kinds=(
            "escalation_applied_early", "escalation_compounded_too_often"))
        if rent_error:
            rent = rent_error.billed
        invoice.charges.append(_charge(
            invoice, lease, clinic.suite, "base_rent",
            "%s — %s" % (CHARGE_LABELS["base_rent"], invoice.period_label()),
            rent, rent_error.error_id if rent_error else None))

        # Operating expense estimate.
        cam = lease.cam_estimate_monthly
        cam_error = _find(planted, "cam_estimate",
                          override_kinds=("cam_estimate_above_lease",))
        if cam_error:
            cam = cam_error.billed
        invoice.charges.append(_charge(
            invoice, lease, clinic.suite, "cam_estimate",
            "%s — %s" % (CHARGE_LABELS["cam_estimate"], invoice.period_label()),
            cam, cam_error.error_id if cam_error else None))

        # A line for premises this tenant does not lease.
        stray = _of_kind(planted, "charge_for_unleased_suite")
        if stray:
            invoice.charges.append(_charge(
                invoice, lease, "Suite 118", "base_rent",
                "Base Rent — Suite 118 — %s" % invoice.period_label(),
                stray.billed, stray.error_id))

        invoices.append(invoice)

        # A duplicate invoice is a second document, not a second line.
        duplicate = _of_kind(planted, "duplicate_rent_invoice")
        if duplicate:
            counter += 1
            dupe = Invoice(
                invoice_id=_invoice_id(company, landlord_id, period, counter),
                landlord_id=landlord_id,
                clinic_id=lease.clinic_id,
                period=period,
                issue_date=issue_date + timedelta(days=4),
                due_date=period,
            )
            dupe.charges.append(_charge(
                dupe, lease, clinic.suite, "base_rent",
                "%s — %s" % (CHARGE_LABELS["base_rent"], dupe.period_label()),
                duplicate.billed, duplicate.error_id))
            invoices.append(dupe)

    return invoices


def build_payments(invoices: List[Invoice], company: Optional[Company] = None) -> List[Payment]:
    """AP pays what the landlord billed. That is the whole problem.

    One bank line per charge, because AP codes each line to its own GL account —
    which is also what lets the checker compare rent against the rent schedule
    without netting the operating expense estimate into it.
    """
    company = company or build_company()
    payments: List[Payment] = []
    for invoice in invoices:
        landlord = company.landlord(invoice.landlord_id)
        paid_on = invoice.due_date + timedelta(days=_payment_delay(invoice.invoice_id))
        for index, charge in enumerate(invoice.charges, start=1):
            payments.append(Payment(
                payment_id="%s-P%02d" % (invoice.invoice_id, index),
                period=invoice.period,
                paid_on=paid_on,
                clinic_id=charge.clinic_id,
                lease_id=charge.lease_id,
                charge_type=charge.charge_type,
                amount=charge.amount,
                reference="ACH-%s" % _ach(invoice.invoice_id, index),
                counterparty=landlord.name,
                invoice_id=invoice.invoice_id,
            ))
    return payments


def write_ap_export(invoices: List[Invoice], path) -> None:
    """What AP approved: one row per invoice line."""
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "invoice_id", "vendor_id", "clinic_id", "lease_id", "period",
            "charge_type", "description", "suite", "amount", "issue_date",
            "due_date", "status",
        ])
        for invoice in invoices:
            for charge in invoice.charges:
                writer.writerow([
                    invoice.invoice_id, invoice.landlord_id, charge.clinic_id,
                    charge.lease_id, invoice.period.isoformat(), charge.charge_type,
                    charge.description, charge.suite, "%.2f" % charge.amount,
                    invoice.issue_date.isoformat(), invoice.due_date.isoformat(),
                    "approved",
                ])


def write_bank_export(payments: List[Payment], path) -> None:
    """What left the account.

    The first four columns are the shape `leasedesk.reconcile.load_payments`
    already reads, so the existing engine can consume this file unchanged.
    """
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "period", "lease_id", "amount", "reference",
            "payment_id", "paid_on", "clinic_id", "charge_type",
            "counterparty", "invoice_id",
        ])
        for p in payments:
            writer.writerow([
                p.period.isoformat(), p.lease_id, "%.2f" % p.amount, p.reference,
                p.payment_id, p.paid_on.isoformat(), p.clinic_id, p.charge_type,
                p.counterparty, p.invoice_id,
            ])


def expected_charges(
    period: date,
    company: Optional[Company] = None,
    leases: Optional[List[LeaseTerms]] = None,
) -> Dict[str, Dict[str, float]]:
    """What the leases support for this month, by clinic and charge type.

    This is the answer, not the input. It exists so tests and the eval can
    assert on variances without re-deriving the arithmetic.
    """
    company = company or build_company()
    leases = leases if leases is not None else build_leases(company)
    return {
        lease.clinic_id: {
            "base_rent": lease.rent_for(period),
            "cam_estimate": lease.cam_estimate_monthly,
        }
        for lease in leases
    }


# --- helpers ---------------------------------------------------------------

def _charge(invoice, lease, suite, charge_type, description, amount, error_id):
    return Charge(
        # Line number, not charge type: one invoice can carry two lines of the
        # same type (E3's stray suite), and ingestion keys on this id.
        charge_id="%s-L%d" % (invoice.invoice_id, len(invoice.charges) + 1),
        invoice_id=invoice.invoice_id,
        clinic_id=lease.clinic_id,
        lease_id=lease.lease_id,
        landlord_id=lease.landlord_id,
        period=invoice.period,
        charge_type=charge_type,
        description=description,
        suite=suite,
        amount=round(amount, 2),
        error_id=error_id,
    )


def _find(planted, charge_type, override_kinds):
    for err in planted:
        if err.charge_type == charge_type and err.kind in override_kinds:
            return err
    return None


def _of_kind(planted, kind):
    for err in planted:
        if err.kind == kind:
            return err
    return None


def _invoice_id(company, landlord_id, period, counter):
    prefix = landlord_id.split("-")[-1][:5].upper()
    return "%s-%s-%04d" % (prefix, period.strftime("%Y%m"), counter)


def _previous_month_day(period: date, day: int) -> date:
    first = date(period.year, period.month, 1)
    previous = first - timedelta(days=1)
    return date(previous.year, previous.month, min(day, 28))


def _payment_delay(invoice_id: str) -> int:
    """Deterministic 1-4 days, so payments are not all on the same date."""
    return sum(ord(c) for c in invoice_id) % 4 + 1


def _ach(invoice_id: str, index: int) -> str:
    return "%05d" % ((sum(ord(c) for c in invoice_id) * 37 + index * 11) % 100000)
