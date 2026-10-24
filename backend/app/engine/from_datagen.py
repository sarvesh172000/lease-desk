"""Build confirmed `LeaseRule`s from generated lease terms.

A shim for the weekend. In the real flow a rule comes from an abstraction a
regional manager has confirmed; until the confirmation UI exists, the generated
terms stand in for it. The proofs are the real sentences from the rendered PDF,
so the evidence shown in the UI is genuine either way.
"""

from typing import Dict, List, Optional

from .charges import LeaseRule, Proof, RentStep

PROOF_TEMPLATES = {
    "base_rent": ("3.1", "The initial Monthly Base Rent is ${rent} per month"),
    "escalation": ("3.3", "the Monthly Base Rent shall increase by {escalation}"),
    "cam_estimate": ("4.1", "Landlord’s current estimate of Operating Expenses is "
                            "${psf} per rentable square foot per annum"),
    "premises": ("1.1", "those certain premises designated as {suite}"),
    "payment_timing": ("3.2", "Base Rent shall be due and payable in advance on the "
                              "first (1st) day of each calendar month during the Term"),
}


def rule_from_terms(terms, company) -> LeaseRule:
    clinic = company.clinic(terms.clinic_id)
    return LeaseRule(
        lease_id=terms.lease_id,
        clinic_id=terms.clinic_id,
        suite=clinic.suite,
        commencement=terms.commencement,
        expiration=terms.expiration,
        steps=[RentStep(s.start, s.end, s.monthly_rent) for s in terms.rent_schedule()],
        cam_estimate_monthly=terms.cam_estimate_monthly,
        cam_estimate_psf_annual=terms.cam_estimate_psf_annual,
        proof={
            "base_rent": Proof(*_fill("base_rent", rent="{:,.2f}".format(terms.base_rent_monthly))),
            "escalation": Proof(*_fill("escalation", escalation=terms.escalation.describe())),
            "cam_estimate": Proof(*_fill("cam_estimate", psf="%.2f" % terms.cam_estimate_psf_annual)),
            "premises": Proof(*_fill("premises", suite=clinic.suite)),
            "payment_timing": Proof(*_fill("payment_timing")),
        },
    )


def rules_from_terms(all_terms, company) -> Dict[str, LeaseRule]:
    return {t.lease_id: rule_from_terms(t, company) for t in all_terms}


def charges_from_invoices(invoices) -> List:
    from ..agents.checker import Charge

    return [
        Charge(
            charge_id=c.charge_id,
            invoice_id=c.invoice_id,
            lease_id=c.lease_id,
            clinic_id=c.clinic_id,
            period=c.period,
            charge_type=c.charge_type,
            suite=c.suite,
            amount=c.amount,
            description=c.description,
        )
        for invoice in invoices
        for c in invoice.charges
    ]


def _fill(key: str, **kwargs):
    section, template = PROOF_TEMPLATES[key]
    return section, template.format(**kwargs)
