"""Render a landlord invoice as a PDF.

Phase 1 uses one invoice format; Phase 2 adds the letter and portal-CSV
variants. The line items are a table so the parser has something structured to
read, and every amount appears once so a citation can box it.

`invariant=1` for the same reason as the lease renderer: the store is
content-addressed and the answer key cites documents by sha256.
"""

from io import BytesIO
from typing import List

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

STYLES = getSampleStyleSheet()
BODY = ParagraphStyle("ibody", parent=STYLES["Normal"], fontSize=9, leading=12.5)
SMALL = ParagraphStyle("ismall", parent=BODY, fontSize=8, textColor=colors.HexColor("#555555"))
TITLE = ParagraphStyle("ititle", parent=STYLES["Heading1"], fontSize=20, leading=24,
                       alignment=TA_RIGHT, textColor=colors.HexColor("#222222"))
LANDLORD = ParagraphStyle("illord", parent=STYLES["Heading2"], fontSize=12, leading=15)


def render_invoice(invoice, company) -> bytes:
    landlord = company.landlord(invoice.landlord_id)
    clinic = company.clinic(invoice.clinic_id)
    center = company.center(clinic.center_id)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
        topMargin=0.8 * inch, bottomMargin=0.8 * inch,
        title="Invoice %s" % invoice.invoice_id,
        author=landlord.name,
        invariant=1,
    )

    story: List = []
    story.append(Table(
        [[Paragraph(landlord.name, LANDLORD), Paragraph("INVOICE", TITLE)],
         [Paragraph(landlord.notice_address.replace(", ", "<br/>"), SMALL), ""]],
        colWidths=[4.0 * inch, 2.8 * inch],
        style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                          ("BOTTOMPADDING", (0, 0), (-1, 0), 2)]),
    ))
    story.append(Spacer(1, 0.18 * inch))

    story.append(Table(
        [["Invoice Number", invoice.invoice_id, "Invoice Date", _long(invoice.issue_date)],
         ["Property", center.name, "Due Date", _long(invoice.due_date)],
         ["Billing Period", invoice.period_label(), "Terms", "Due on the 1st"]],
        colWidths=[1.25 * inch, 2.45 * inch, 1.1 * inch, 2.0 * inch],
        style=TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
            ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#555555")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]),
    ))
    story.append(Spacer(1, 0.16 * inch))

    story.append(Paragraph("<b>BILL TO</b>", SMALL))
    story.append(Paragraph(
        "%s<br/>%s, %s<br/>%s" % (company.entity.name, clinic.name, clinic.suite, center.address),
        BODY))
    story.append(Spacer(1, 0.22 * inch))

    rows = [["Description", "Suite", "Period", "Amount"]]
    for charge in invoice.charges:
        rows.append([
            Paragraph(charge.description, BODY),
            charge.suite,
            invoice.period_label(),
            "$%s" % _money(charge.amount),
        ])
    rows.append(["", "", Paragraph("<b>TOTAL DUE</b>", BODY),
                 Paragraph("<b>$%s</b>" % _money(invoice.total()), BODY)])

    table = Table(rows, colWidths=[3.1 * inch, 0.95 * inch, 1.5 * inch, 1.25 * inch],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("ALIGN", (1, 0), (2, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -2), 0.4, colors.HexColor("#aaaaaa")),
        ("LINEABOVE", (2, -1), (-1, -1), 1.0, colors.HexColor("#333333")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.3 * inch))

    story.append(Paragraph(
        "Remit payment to %s at the address above, referencing invoice %s. "
        "Questions regarding this statement may be directed to %s (%s)."
        % (landlord.name, invoice.invoice_id, landlord.property_manager,
           landlord.property_manager_email),
        SMALL))

    doc.build(story)
    return buf.getvalue()


def _long(d):
    return d.strftime("%B %-d, %Y")


def _money(v):
    return "{:,.2f}".format(v)
