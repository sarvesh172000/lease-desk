"""Render a LeaseTerms into a lease PDF that reads like a real one.

This is the input side of the benchmark: the abstraction agent sees only this
PDF, never `leases.py`. So the terms have to be stated the way leases state
them — a rent table rather than a field list, a notices clause naming the
authorized representative, escalation described in prose in one article and
implied by the table in another.

Everything the agent must extract appears exactly once, in a quotable sentence
or a table row, so a citation can box it on the page.
"""

from io import BytesIO
from typing import List

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from .company import Company
from .leases import LeaseTerms

STYLES = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=STYLES["Normal"], fontSize=9.5, leading=14,
                      alignment=TA_JUSTIFY, spaceAfter=8)
H1 = ParagraphStyle("h1", parent=STYLES["Heading1"], fontSize=15, leading=19,
                    alignment=TA_CENTER, spaceAfter=14)
H2 = ParagraphStyle("h2", parent=STYLES["Heading2"], fontSize=10.5, leading=14,
                    spaceBefore=12, spaceAfter=6)
CENTERED = ParagraphStyle("centered", parent=BODY, alignment=TA_CENTER)


def render_lease(terms: LeaseTerms, company: Company) -> bytes:
    clinic = company.clinic(terms.clinic_id)
    landlord = company.landlord(terms.landlord_id)
    center = company.center(clinic.center_id)
    pro_rata = company.pro_rata_for(terms.clinic_id)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=1.1 * inch, rightMargin=1.1 * inch,
        topMargin=1.0 * inch, bottomMargin=0.9 * inch,
        title="Office Lease Agreement — %s" % clinic.name,
        author=landlord.name,
        # Without this ReportLab stamps a creation time and a random document
        # id, so the same lease would hash differently on every run. The store
        # is content-addressed and the answer key cites documents by sha256,
        # so the bytes have to be reproducible.
        invariant=1,
    )

    story: List = []
    _cover(story, terms, company, clinic, landlord, center)
    _premises(story, terms, clinic, center, pro_rata)
    _term(story, terms)
    _base_rent(story, terms)
    _operating_expenses(story, terms, pro_rata)
    _security_deposit(story, terms)
    _use_and_maintenance(story, clinic)
    _insurance_and_default(story, landlord)
    _options(story, terms, landlord)
    _notices(story, company, landlord, center)
    _signatures(story, company, landlord)

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawCentredString(LETTER[0] / 2, 0.55 * inch, "Page %d" % doc.page)
    canvas.restoreState()


def _cover(story, terms, company, clinic, landlord, center):
    story += [
        Spacer(1, 0.7 * inch),
        Paragraph("OFFICE LEASE AGREEMENT", H1),
        Paragraph("%s<br/>%s" % (center.name, center.address), CENTERED),
        Spacer(1, 0.35 * inch),
        Paragraph(
            "THIS OFFICE LEASE AGREEMENT (this &ldquo;Lease&rdquo;) is entered into by and "
            "between <b>%s</b>, a California limited liability company "
            "(&ldquo;Landlord&rdquo;), and <b>%s</b>, a California corporation "
            "(&ldquo;Tenant&rdquo;), and is effective as of %s."
            % (landlord.name, company.entity.name, _long(terms.commencement)),
            BODY,
        ),
        Spacer(1, 0.2 * inch),
        Paragraph("BASIC LEASE INFORMATION", H2),
    ]
    rows = [
        ["Premises", "%s, %s" % (clinic.suite, center.name)],
        ["Rentable Square Feet", "{:,} rentable square feet".format(terms.rsf)],
        ["Commencement Date", _long(terms.commencement)],
        ["Expiration Date", _long(terms.expiration)],
        ["Initial Term", "%d years" % terms.term_years],
        ["Initial Monthly Base Rent", "$%s" % _money(terms.base_rent_monthly)],
        ["Annual Escalation", terms.escalation.describe()],
        ["Estimated Operating Expenses", "$%.2f per rentable square foot per annum"
            % terms.cam_estimate_psf_annual],
        ["Security Deposit", "$%s" % _money(terms.security_deposit)],
        ["Permitted Use", "Retail coffee shop and café, with the sale of food and beverages"],
    ]
    story += [_kv_table(rows), PageBreak()]


def _premises(story, terms, clinic, center, pro_rata):
    story += [
        Paragraph("ARTICLE 1. PREMISES", H2),
        Paragraph(
            "1.1 <b>Demise.</b> Landlord hereby leases to Tenant, and Tenant hereby leases "
            "from Landlord, those certain premises designated as %s (the &ldquo;Premises&rdquo;) "
            "in the building commonly known as %s and located at %s (the &ldquo;Building&rdquo;), "
            "together with the non-exclusive right to use the Common Areas."
            % (clinic.suite, center.name, center.address),
            BODY,
        ),
        Paragraph(
            "1.2 <b>Rentable Area.</b> The Premises are stipulated to contain {:,} rentable "
            "square feet. The Building is stipulated to contain {:,} rentable square feet. "
            "Tenant&rsquo;s Proportionate Share is {:.2f}%, computed as the rentable area of the "
            "Premises divided by the rentable area of the Building. The foregoing measurements "
            "are conclusive and binding on the parties and shall not be subject to remeasurement "
            "during the Term."
            .format(terms.rsf, center.total_rsf, pro_rata * 100),
            BODY,
        ),
        Paragraph(
            "1.3 <b>Common Areas.</b> &ldquo;Common Areas&rdquo; means all areas of the Building "
            "and the surrounding land made available by Landlord for the common use of tenants, "
            "including lobbies, corridors, elevators, restrooms, parking areas, driveways and "
            "landscaped areas. Landlord reserves the right to modify the Common Areas provided "
            "such modification does not materially and adversely affect Tenant&rsquo;s access to "
            "the Premises.",
            BODY,
        ),
    ]


def _term(story, terms):
    story += [
        Paragraph("ARTICLE 2. TERM", H2),
        Paragraph(
            "2.1 <b>Initial Term.</b> The term of this Lease (the &ldquo;Term&rdquo;) shall "
            "commence on %s (the &ldquo;Commencement Date&rdquo;) and shall expire at 11:59 p.m. "
            "on %s (the &ldquo;Expiration Date&rdquo;), unless sooner terminated or extended in "
            "accordance with the provisions of this Lease. The Initial Term is %d years."
            % (_long(terms.commencement), _long(terms.expiration), terms.term_years),
            BODY,
        ),
        Paragraph(
            "2.2 <b>Delivery.</b> Landlord shall deliver the Premises to Tenant on or before the "
            "Commencement Date in broom-clean condition with all building systems serving the "
            "Premises in good working order. Tenant&rsquo;s taking of possession shall constitute "
            "acceptance of the Premises, subject to latent defects and to any punch-list items "
            "delivered to Landlord within thirty (30) days following the Commencement Date.",
            BODY,
        ),
        Paragraph(
            "2.3 <b>Holding Over.</b> If Tenant remains in possession after the Expiration Date "
            "without Landlord&rsquo;s written consent, such possession shall be a tenancy at "
            "sufferance terminable at will, and Base Rent shall be one hundred fifty percent "
            "(150%) of the Base Rent in effect immediately prior to the Expiration Date.",
            BODY,
        ),
    ]


def _base_rent(story, terms):
    schedule = terms.rent_schedule()
    rows = [["Lease Year", "Period", "Monthly Base Rent", "Annual Base Rent"]]
    for i, step in enumerate(schedule, start=1):
        months = _months_between(step.start, step.end)
        rows.append([
            str(i),
            "%s – %s" % (_short(step.start), _short(step.end)),
            "$%s" % _money(step.monthly_rent),
            "$%s" % _money(step.monthly_rent * months),
        ])

    story += [
        PageBreak(),
        Paragraph("ARTICLE 3. BASE RENT", H2),
        Paragraph(
            "3.1 <b>Base Rent.</b> Tenant shall pay to Landlord as base rent for the Premises "
            "(&ldquo;Base Rent&rdquo;) the amounts set forth in the Base Rent Schedule below, "
            "without prior notice or demand and without any setoff, abatement or deduction "
            "whatsoever, in lawful money of the United States. The initial Monthly Base Rent is "
            "$%s per month."
            % _money(terms.base_rent_monthly),
            BODY,
        ),
        Paragraph(
            "3.2 <b>Time of Payment.</b> Base Rent shall be due and payable in advance on the "
            "first (1st) day of each calendar month during the Term. Rent for any partial "
            "calendar month shall be prorated on the basis of a thirty (30) day month.",
            BODY,
        ),
        Paragraph(
            "3.3 <b>Escalation.</b> Commencing on the first anniversary of the Commencement Date "
            "and on each anniversary thereafter during the Term, the Monthly Base Rent shall "
            "increase by %s. For the avoidance of doubt, each such increase is applied to the "
            "Monthly Base Rent in effect immediately prior to the applicable anniversary, and is "
            "not compounded more frequently than annually."
            % terms.escalation.describe(),
            BODY,
        ),
        Spacer(1, 0.08 * inch),
        KeepTogether([
            Paragraph("<b>BASE RENT SCHEDULE</b>", BODY),
            _rent_table(rows),
        ]),
        Paragraph(
            "3.4 <b>Late Charge.</b> If any installment of Base Rent is not received by Landlord "
            "within five (5) days after the date due, Tenant shall pay a late charge equal to "
            "five percent (5%) of the overdue amount. A late charge shall not be assessed on any "
            "installment actually received by Landlord on or before the date due, regardless of "
            "the date on which such payment is posted by Landlord.",
            BODY,
        ),
    ]


def _operating_expenses(story, terms, pro_rata):
    story += [
        PageBreak(),
        Paragraph("ARTICLE 4. OPERATING EXPENSES AND ADDITIONAL RENT", H2),
        Paragraph(
            "4.1 <b>Estimated Operating Expenses.</b> In addition to Base Rent, Tenant shall pay "
            "Tenant&rsquo;s Proportionate Share of Operating Expenses. Landlord&rsquo;s current "
            "estimate of Operating Expenses is $%.2f per rentable square foot per annum, payable "
            "in monthly installments of $%s concurrently with Base Rent."
            % (terms.cam_estimate_psf_annual, _money(terms.cam_estimate_monthly)),
            BODY,
        ),
        Paragraph(
            "4.2 <b>Definition.</b> &ldquo;Operating Expenses&rdquo; means all costs actually "
            "incurred by Landlord in owning, operating, maintaining, repairing and managing the "
            "Building and Common Areas, including utilities serving the Common Areas, janitorial "
            "and landscaping services, security, non-structural repairs, property management "
            "fees, real property taxes and insurance premiums.",
            BODY,
        ),
        Paragraph(
            "4.3 <b>Exclusions.</b> Operating Expenses shall expressly exclude: (a) capital "
            "improvements and capital replacements, except that the cost of a capital item "
            "required by law or installed to reduce Operating Expenses may be amortized over its "
            "useful life and included at the annual amortized amount; (b) leasing commissions, "
            "marketing costs and tenant improvement allowances; (c) costs reimbursed by insurance "
            "proceeds, warranty or any other tenant; (d) interest and principal on any mortgage; "
            "and (e) costs arising from Landlord&rsquo;s negligence or willful misconduct.",
            BODY,
        ),
        Paragraph(
            "4.4 <b>Management Fee Cap.</b> The property management fee included in Operating "
            "Expenses shall not exceed four percent (4%) of gross rental receipts for the "
            "Building in any calendar year.",
            BODY,
        ),
        Paragraph(
            "4.5 <b>Controllable Expense Cap.</b> Tenant&rsquo;s Proportionate Share of "
            "Controllable Operating Expenses shall not increase by more than five percent (5%) "
            "per calendar year on a cumulative, compounding basis over the amount payable for the "
            "prior calendar year. &ldquo;Controllable Operating Expenses&rdquo; means all "
            "Operating Expenses other than real property taxes, insurance premiums, utilities and "
            "snow removal.",
            BODY,
        ),
        Paragraph(
            "4.6 <b>Reconciliation.</b> Within one hundred twenty (120) days after the end of each "
            "calendar year, Landlord shall deliver to Tenant a statement setting forth the actual "
            "Operating Expenses for such year and Tenant&rsquo;s Proportionate Share thereof. Any "
            "overpayment shall be credited against the next installments of Additional Rent; any "
            "underpayment shall be paid by Tenant within thirty (30) days after delivery of the "
            "statement.",
            BODY,
        ),
        Paragraph(
            "4.7 <b>Audit Right.</b> Tenant shall have the right, exercisable not later than one "
            "hundred eighty (180) days after receipt of Landlord&rsquo;s annual statement, to "
            "audit Landlord&rsquo;s books and records relating to Operating Expenses for the "
            "calendar year covered by such statement. If such audit discloses an overstatement "
            "exceeding three percent (3%), Landlord shall bear the reasonable cost of the audit.",
            BODY,
        ),
        Paragraph(
            "4.8 <b>Proportionate Share.</b> Tenant&rsquo;s Proportionate Share for purposes of "
            "this Article 4 is {:.2f}%. No Operating Expense shall be allocated to Tenant in "
            "excess of Tenant&rsquo;s Proportionate Share of the expense actually incurred, and "
            "no single expense may be allocated more than once among the tenants of the Building."
            .format(pro_rata * 100),
            BODY,
        ),
    ]


def _security_deposit(story, terms):
    story += [
        PageBreak(),
        Paragraph("ARTICLE 5. SECURITY DEPOSIT", H2),
        Paragraph(
            "5.1 <b>Deposit.</b> Concurrently with Tenant&rsquo;s execution of this Lease, Tenant "
            "shall deposit with Landlord the sum of $%s as a security deposit for the faithful "
            "performance of Tenant&rsquo;s obligations hereunder."
            % _money(terms.security_deposit),
            BODY,
        ),
        Paragraph(
            "5.2 <b>Return.</b> Landlord shall return the security deposit, less any amounts "
            "properly applied, within thirty (30) days after the later of the expiration of the "
            "Term and Tenant&rsquo;s surrender of the Premises.",
            BODY,
        ),
    ]


def _use_and_maintenance(story, clinic):
    story += [
        Paragraph("ARTICLE 6. USE AND COMPLIANCE", H2),
        Paragraph(
            "6.1 <b>Permitted Use.</b> Tenant shall use the Premises solely for the operation "
            "of a retail coffee shop (%s), the sale of food and beverages for consumption on "
            "and off the Premises, and related retail use, and for no other purpose "
            "without Landlord&rsquo;s prior written consent." % clinic.service_line,
            BODY,
        ),
        Paragraph(
            "6.2 <b>Compliance.</b> Tenant shall comply with all applicable laws, including the "
            "Americans with Disabilities Act and all federal and state health information privacy "
            "requirements, in its use and occupancy of the Premises.",
            BODY,
        ),
        Paragraph("ARTICLE 7. MAINTENANCE AND REPAIRS", H2),
        Paragraph(
            "7.1 <b>Landlord Obligations.</b> Landlord shall maintain in good order and repair "
            "the structural elements of the Building, the roof, exterior walls, foundations and "
            "the base building mechanical, electrical and plumbing systems serving the Premises.",
            BODY,
        ),
        Paragraph(
            "7.2 <b>Tenant Obligations.</b> Tenant shall maintain the interior non-structural "
            "portions of the Premises in good condition, including all fixtures and equipment "
            "installed by Tenant, and shall surrender the Premises in the condition required by "
            "Article 12, ordinary wear and tear excepted.",
            BODY,
        ),
    ]


def _insurance_and_default(story, landlord):
    story += [
        PageBreak(),
        Paragraph("ARTICLE 8. INSURANCE AND INDEMNITY", H2),
        Paragraph(
            "8.1 <b>Tenant Insurance.</b> Tenant shall maintain commercial general liability "
            "insurance with limits of not less than $2,000,000 per occurrence and $4,000,000 in "
            "the aggregate, naming Landlord as an additional insured, together with professional "
            "liability coverage customary for retail food and beverage operations.",
            BODY,
        ),
        Paragraph(
            "8.2 <b>Waiver of Subrogation.</b> Landlord and Tenant each waive all rights of "
            "recovery against the other for any loss covered by property insurance required to be "
            "carried under this Lease.",
            BODY,
        ),
        Paragraph("ARTICLE 9. ASSIGNMENT AND SUBLETTING", H2),
        Paragraph(
            "9.1 Tenant shall not assign this Lease or sublet all or any portion of the Premises "
            "without Landlord&rsquo;s prior written consent, which shall not be unreasonably "
            "withheld, conditioned or delayed. Assignment to an entity controlling, controlled by "
            "or under common control with Tenant shall not require consent, provided Tenant gives "
            "Landlord not less than fifteen (15) days&rsquo; prior written notice.",
            BODY,
        ),
        Paragraph("ARTICLE 10. DEFAULT AND REMEDIES", H2),
        Paragraph(
            "10.1 <b>Events of Default.</b> Each of the following constitutes an event of default: "
            "(a) failure to pay any installment of Base Rent or Additional Rent within five (5) "
            "days after written notice that the same is past due; (b) failure to perform any other "
            "obligation under this Lease within thirty (30) days after written notice; and (c) any "
            "general assignment by Tenant for the benefit of creditors.",
            BODY,
        ),
        Paragraph(
            "10.2 <b>Remedies.</b> Upon an event of default, %s may pursue any remedy available at "
            "law or in equity, including termination of this Lease and recovery of damages as "
            "provided in California Civil Code Section 1951.2." % landlord.name,
            BODY,
        ),
    ]


def _options(story, terms, landlord):
    r = terms.renewal
    story += [
        PageBreak(),
        Paragraph("ARTICLE 11. OPTION TO EXTEND", H2),
        Paragraph(
            "11.1 <b>Grant of Option.</b> Provided no event of default is then continuing, Tenant "
            "shall have %s to extend the Term, each for an additional period of %d years, on all "
            "of the terms and conditions of this Lease except that Base Rent during each extension "
            "period shall be determined under Section 11.3."
            % (_option_phrase(r.count), r.years),
            BODY,
        ),
        Paragraph(
            "11.2 <b>Exercise.</b> Each option shall be exercised, if at all, by written notice "
            "delivered to Landlord not less than %d days prior to the then-current Expiration "
            "Date. Time is of the essence with respect to the delivery of such notice, and the "
            "failure to deliver notice within the period provided shall render the option null "
            "and void." % r.notice_days,
            BODY,
        ),
        Paragraph(
            "11.3 <b>Extension Rent.</b> Monthly Base Rent for the first year of each extension "
            "period shall equal the greater of (a) the Monthly Base Rent in effect during the "
            "final month of the preceding period, and (b) ninety-five percent (95%) of the fair "
            "market rental rate for comparable retail space in the submarket, as "
            "reasonably determined by Landlord and Tenant. Thereafter the escalation provisions "
            "of Section 3.3 shall continue to apply.",
            BODY,
        ),
    ]


def _notices(story, company, landlord, center):
    story += [
        Paragraph("ARTICLE 12. NOTICES", H2),
        Paragraph(
            "12.1 <b>Manner of Notice.</b> All notices, demands, consents and approvals required "
            "or permitted under this Lease shall be in writing and shall be deemed given when "
            "delivered personally, one business day after deposit with a nationally recognized "
            "overnight courier, or three business days after deposit in the United States mail, "
            "certified, return receipt requested, addressed as set forth below.",
            BODY,
        ),
        Paragraph(
            "12.2 <b>Authorized Representative.</b> Landlord designates <b>%s</b> as the sole "
            "representative authorized to deliver and receive notices, grant consents and execute "
            "amendments on Landlord&rsquo;s behalf under this Lease. No modification, waiver or "
            "concession shall bind Landlord unless given in writing by such authorized "
            "representative. Correspondence from any property manager, agent or other person "
            "shall be informational only and shall not modify this Lease."
            % landlord.authorized_rep,
            BODY,
        ),
        Spacer(1, 0.06 * inch),
        _kv_table([
            ["Notices to Landlord",
             "%s<br/>Attn: %s, Authorized Representative<br/>%s<br/>%s"
             % (landlord.name, landlord.authorized_rep, landlord.notice_address,
                landlord.authorized_rep_email)],
            ["Notices to Tenant",
             "%s<br/>Attn: Controller<br/>%s<br/>%s"
             % (company.entity.name, center.address, company.person("controller").email)],
        ]),
        Paragraph(
            "12.3 <b>Entire Agreement.</b> This Lease contains the entire agreement of the parties "
            "with respect to the Premises and supersedes all prior negotiations, representations "
            "and agreements, whether written or oral. This Lease may be amended only by a written "
            "instrument signed by both parties.",
            BODY,
        ),
    ]


def _signatures(story, company, landlord):
    story += [
        PageBreak(),
        Paragraph("SIGNATURE PAGE", H2),
        Paragraph(
            "IN WITNESS WHEREOF, the parties have executed this Lease as of the date first "
            "written above.", BODY),
        Spacer(1, 0.3 * inch),
        _signature_block("LANDLORD", landlord.name, landlord.authorized_rep,
                         "Authorized Representative"),
        Spacer(1, 0.35 * inch),
        _signature_block("TENANT", company.entity.name,
                         company.person("controller").name, "Controller"),
    ]


# --- small builders --------------------------------------------------------

def _kv_table(rows):
    data = [[Paragraph("<b>%s</b>" % k, BODY), Paragraph(v, BODY)] for k, v in rows]
    t = Table(data, colWidths=[2.0 * inch, 4.3 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#cccccc")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _rent_table(rows):
    t = Table(rows, colWidths=[0.8 * inch, 2.4 * inch, 1.55 * inch, 1.55 * inch],
              repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _signature_block(label, org, name, title):
    return Table(
        [[Paragraph("<b>%s:</b> %s" % (label, org), BODY)],
         [Paragraph("By: ______________________________", BODY)],
         [Paragraph("Name: %s" % name, BODY)],
         [Paragraph("Title: %s" % title, BODY)]],
        colWidths=[4.6 * inch],
    )


def _option_phrase(count):
    return "one (1) option" if count == 1 else "%s (%d) options" % (_word(count), count)


def _word(n):
    return {2: "two", 3: "three"}.get(n, str(n))


def _months_between(start, end):
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def _long(d):
    return d.strftime("%B %-d, %Y")


def _short(d):
    return d.strftime("%b %-d, %Y")


def _money(v):
    return "{:,.2f}".format(v)
