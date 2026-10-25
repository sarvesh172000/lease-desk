"""Format C: a CSV export from the landlord's tenant portal.

Its own column names, its own charge codes, its own date format, and a total
row the parser must not mistake for a line item. Nothing about it matches our
vocabulary, which is the point: the mapping has to live somewhere, explicitly.
"""

import csv
from io import StringIO
from typing import Dict

# The portal's charge codes, and what they mean to us.
CODE_TO_CHARGE_TYPE: Dict[str, str] = {
    "RNT": "base_rent",
    "OPX": "cam_estimate",
    "RET": "property_tax",
    "INS": "insurance",
    "REC": "cam_reconciliation",
    "LTE": "late_fee",
    "CRD": "credit_memo",
}

CHARGE_TYPE_TO_CODE = {v: k for k, v in CODE_TO_CHARGE_TYPE.items()}

COLUMNS = ["TenantRef", "PropertyCode", "ChargeCode", "ChargeDesc",
           "PostDate", "DueDate", "UnitRef", "ChargeAmt", "DocNo"]


def render(invoice, company) -> str:
    clinic = company.clinic(invoice.clinic_id)
    center = company.center(clinic.center_id)

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(COLUMNS)

    for charge in invoice.charges:
        writer.writerow([
            clinic.clinic_id.replace("STORE-", "T"),
            center.center_id.replace("CTR-", ""),
            CHARGE_TYPE_TO_CODE.get(charge.charge_type, "OTH"),
            charge.description,
            invoice.issue_date.strftime("%m/%d/%Y"),
            invoice.due_date.strftime("%m/%d/%Y"),
            charge.suite.replace("Suite ", ""),
            "%.2f" % charge.amount,
            invoice.invoice_id,
        ])

    # A total row that looks like a line item but is not one.
    writer.writerow([clinic.clinic_id.replace("STORE-", "T"),
                     center.center_id.replace("CTR-", ""), "TOT",
                     "STATEMENT TOTAL", "", "", "",
                     "%.2f" % invoice.total(), invoice.invoice_id])
    return buf.getvalue()
