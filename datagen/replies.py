"""What the landlord writes back.

A dispute is not resolved when the letter goes out. It is resolved weeks later,
by a reply that may grant the credit, grant part of it, refuse outright, or ask
a question that restarts the whole thing. Each outcome has to be handled, and
a system tested only on disputes that are cheerfully granted has not been
tested.

Partial credits are the interesting case. The landlord agrees $1,200 of a
$4,820 claim, which means the dispute is neither open nor closed: a receivable
for the agreed part, and a decision still to make on the rest.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from email.message import EmailMessage
from typing import List, Optional

FULL_CREDIT = "full_credit"
PARTIAL_CREDIT = "partial_credit"
REFUSED = "refused"
QUERIED = "queried"

OUTCOMES = (FULL_CREDIT, PARTIAL_CREDIT, REFUSED, QUERIED)


@dataclass(frozen=True)
class Reply:
    message_id: str
    in_reply_to: str
    sender: str
    sender_name: str
    sent: date
    subject: str
    body: str
    outcome: str
    clinic_id: str
    claimed: float
    granted: float
    is_authorized: bool = True

    @property
    def settles(self) -> bool:
        """Whether this reply closes the dispute on its own."""
        return self.outcome in (FULL_CREDIT, REFUSED)

    @property
    def outstanding(self) -> float:
        return round(self.claimed - self.granted, 2)

    def to_eml(self) -> str:
        msg = EmailMessage()
        msg["Message-ID"] = "<%s>" % self.message_id
        msg["In-Reply-To"] = "<%s>" % self.in_reply_to
        msg["From"] = "%s <%s>" % (self.sender_name, self.sender)
        msg["To"] = "ap@northbaypt.example"
        msg["Date"] = self.sent.strftime("%a, %d %b %Y 11:02:00 -0700")
        msg["Subject"] = self.subject
        msg.set_content(self.body)
        return msg.as_string()


def build_replies(company, disputes: Optional[List[dict]] = None) -> List[Reply]:
    """One reply per dispute, cycling through every outcome.

    `disputes` is a list of {clinic_id, claimed, about, sent, message_id}. The
    default set covers the January findings.
    """
    disputes = disputes if disputes is not None else _default_disputes()
    out: List[Reply] = []

    for index, dispute in enumerate(disputes):
        outcome = OUTCOMES[index % len(OUTCOMES)]
        clinic = company.clinic(dispute["clinic_id"])
        landlord = company.landlord_for(dispute["clinic_id"])
        claimed = float(dispute["claimed"])
        granted = _granted(outcome, claimed)
        sent = dispute["sent"] + timedelta(days=11 + index * 3)

        out.append(Reply(
            message_id="eml-%s-reply-%02d" % (sent.strftime("%Y%m%d"), index + 1),
            in_reply_to=dispute["message_id"],
            sender=landlord.authorized_rep_email,
            sender_name=landlord.authorized_rep,
            sent=sent,
            subject="RE: Disputed charge — %s, %s" % (clinic.suite, dispute["about"]),
            body=_body(outcome, landlord, clinic, dispute, claimed, granted),
            outcome=outcome,
            clinic_id=dispute["clinic_id"],
            claimed=claimed,
            granted=granted,
        ))
    return out


def _granted(outcome: str, claimed: float) -> float:
    if outcome == FULL_CREDIT:
        return claimed
    if outcome == PARTIAL_CREDIT:
        return round(claimed * 0.25, 2)
    return 0.0


def _body(outcome, landlord, clinic, dispute, claimed, granted) -> str:
    about = dispute["about"]
    sign_off = "\n\nRegards,\n%s\n%s\n" % (landlord.authorized_rep, landlord.name)

    if outcome == FULL_CREDIT:
        return (
            "Thank you for your letter regarding %s at %s.\n\n"
            "We have reviewed the charge and agree it was billed in error. A "
            "credit of $%s will appear on your next statement. We apologise "
            "for the inconvenience." % (about, clinic.suite, _money(claimed))
        ) + sign_off

    if outcome == PARTIAL_CREDIT:
        return (
            "Thank you for your letter regarding %s at %s.\n\n"
            "We have reviewed our records. We agree that $%s was billed in "
            "error and will credit that amount on the next statement. The "
            "balance of $%s we believe is correctly chargeable under Section "
            "4.2 of the Lease, and we are not in a position to credit it."
            % (about, clinic.suite, _money(granted), _money(claimed - granted))
        ) + sign_off

    if outcome == REFUSED:
        return (
            "Thank you for your letter regarding %s at %s.\n\n"
            "Having reviewed the Lease and our records, we do not agree that "
            "this charge was billed in error. The amount is properly payable "
            "and remains due. Please remit at your earliest convenience."
            % (about, clinic.suite)
        ) + sign_off

    return (
        "Thank you for your letter regarding %s at %s.\n\n"
        "Before we can respond, could you confirm which lease year you are "
        "referring to, and provide a copy of the statement in question? Our "
        "records show a different figure and we would like to reconcile."
        % (about, clinic.suite)
    ) + sign_off


def _default_disputes() -> List[dict]:
    return [
        {"clinic_id": "STORE-01", "claimed": 516.66, "about": "operating expense estimate",
         "sent": date(2026, 2, 3), "message_id": "eml-20260203-dispute-01"},
        {"clinic_id": "STORE-02", "claimed": 4_820.00, "about": "rent for Suite 118",
         "sent": date(2026, 2, 3), "message_id": "eml-20260203-dispute-02"},
        {"clinic_id": "STORE-03", "claimed": 543.61, "about": "escalation timing",
         "sent": date(2026, 2, 4), "message_id": "eml-20260204-dispute-03"},
        {"clinic_id": "STORE-05", "claimed": 229.44, "about": "escalation frequency",
         "sent": date(2026, 2, 4), "message_id": "eml-20260204-dispute-04"},
    ]


def _money(v: float) -> str:
    return "{:,.2f}".format(v)
