"""Format B: a letter with the amounts in prose.

Some landlords do not send a statement. They send a letter from the property
manager that mentions the figures in sentences, and the amounts have to be read
out of the text rather than lifted from a table. This is the format that breaks
a parser written against a tidy grid.
"""

from io import BytesIO
from typing import List

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

STYLES = getSampleStyleSheet()
BODY = ParagraphStyle("letter", parent=STYLES["Normal"], fontSize=10.5, leading=15.5,
                      spaceAfter=11)


def render(invoice, company) -> bytes:
    landlord = company.landlord(invoice.landlord_id)
    clinic = company.clinic(invoice.clinic_id)
    center = company.center(clinic.center_id)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=1.2 * inch, rightMargin=1.2 * inch,
        topMargin=1.1 * inch, bottomMargin=1.0 * inch,
        title="Statement letter %s" % invoice.invoice_id,
        author=landlord.name, invariant=1,
    )

    # Every charge gets a sentence. Picking the first of each type silently
    # dropped a second rent line — for a suite the tenant does not lease —
    # while the stated total still included it.
    rents = [c for c in invoice.charges if c.charge_type == "base_rent"]
    cams = [c for c in invoice.charges if c.charge_type == "cam_estimate"]
    other = [c for c in invoice.charges
             if c.charge_type not in ("base_rent", "cam_estimate")]

    story: List = [
        Paragraph("<b>%s</b>" % landlord.name, BODY),
        Paragraph(landlord.notice_address.replace(", ", "<br/>"), BODY),
        Spacer(1, 0.25 * inch),
        Paragraph(invoice.issue_date.strftime("%B %-d, %Y"), BODY),
        Spacer(1, 0.15 * inch),
        Paragraph("%s<br/>Attn: Accounts Payable<br/>%s, %s"
                  % (company.entity.name, clinic.name, clinic.suite), BODY),
        Spacer(1, 0.2 * inch),
        Paragraph("Re: <b>Statement for %s — %s, %s</b>"
                  % (invoice.period_label(), clinic.suite, center.name), BODY),
        Spacer(1, 0.1 * inch),
        Paragraph("Dear Accounts Payable,", BODY),
    ]

    sentences = []
    for index, charge in enumerate(rents):
        if index == 0:
            sentences.append(
                "Base rent for %s is due in the amount of $%s, payable on the "
                "first of the month in accordance with the Lease."
                % (invoice.period_label(), _money(charge.amount)))
        else:
            sentences.append(
                "Base rent of $%s is also due for %s for the same period."
                % (_money(charge.amount), charge.suite))
    for charge in cams:
        sentences.append(
            "In addition, your estimated share of operating expenses for the "
            "same period is $%s." % _money(charge.amount))
    for charge in other:
        sentences.append(
            "We are also billing $%s in respect of %s."
            % (_money(charge.amount), charge.description.split("—")[0].strip().lower()))

    sentences.append(
        "The total amount now due is $%s. Please remit by the due date of %s, "
        "referencing statement number %s."
        % (_money(invoice.total()), invoice.due_date.strftime("%B %-d, %Y"),
           invoice.invoice_id))

    for sentence in sentences:
        story.append(Paragraph(sentence, BODY))

    story += [
        Spacer(1, 0.2 * inch),
        Paragraph("Should you have any questions regarding this statement, "
                  "please contact the undersigned.", BODY),
        Spacer(1, 0.3 * inch),
        Paragraph("Sincerely,", BODY),
        Spacer(1, 0.3 * inch),
        Paragraph("%s<br/>Property Manager" % landlord.property_manager, BODY),
    ]

    doc.build(story)
    return buf.getvalue()


def _of(invoice, charge_type):
    for charge in invoice.charges:
        if charge.charge_type == charge_type:
            return charge
    return None


def _money(v: float) -> str:
    return "{:,.2f}".format(v)
