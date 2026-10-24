"""How much a source is worth, decided in code rather than by the model.

The lease says who can change the lease. Its notices clause names one
authorized representative, and states that correspondence from anyone else is
informational only. So "which source do we believe" is not a judgement call —
it is a rule, and it belongs here where it can be tested and shown to a
controller, not inside a prompt where it can be argued with.

The model's job is to find candidate documents and quote them. This decides
what those documents are worth, and whether they settle the question or have
to go to a human.

Ranks, highest authority first:

  1. Executed amendment or side letter signed by both parties
  2. The original executed lease
  3. Written confirmation from the landlord's authorized representative
  4. Email from property management without stated authority
  5. A landlord invoice or statement
  6. Payment history, or the previous accountant's notes
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence

EXECUTED_AMENDMENT = 1
ORIGINAL_LEASE = 2
AUTHORIZED_REP = 3
PROPERTY_MANAGER = 4
LANDLORD_INVOICE = 5
PAYMENT_HISTORY = 6

RANK_NAMES = {
    EXECUTED_AMENDMENT: "executed amendment signed by both parties",
    ORIGINAL_LEASE: "the original executed lease",
    AUTHORIZED_REP: "written confirmation from the authorized representative",
    PROPERTY_MANAGER: "email from property management without stated authority",
    LANDLORD_INVOICE: "a landlord invoice or statement",
    PAYMENT_HISTORY: "payment history",
}

# Words that indicate a message carries an executed instrument rather than a
# description of one.
EXECUTED_MARKERS = (
    "countersigned", "executed", "fully signed", "signed by both",
)


@dataclass(frozen=True)
class Source:
    source_id: str
    rank: int
    sender: Optional[str]
    sent: Optional[date]
    claim: str
    quote: str
    reason: str
    is_suspect: bool = False

    @property
    def rank_name(self) -> str:
        return RANK_NAMES.get(self.rank, "unranked source")


@dataclass
class Decision:
    """What the sources, taken together, allow us to do."""
    settled: bool
    trusted: Optional[Source]
    conflicting: List[Source]
    reason: str

    @property
    def needs_human(self) -> bool:
        return not self.settled


def classify_email(
    source_id: str,
    sender: str,
    body: str,
    authorized_rep_email: str,
    landlord_domain: str,
    has_attachment: bool = False,
    sent: Optional[date] = None,
    claim: str = "",
    quote: str = "",
) -> Source:
    """Rank one message by who sent it and what it carries."""
    sender = (sender or "").lower().strip()
    rep = (authorized_rep_email or "").lower().strip()
    domain = sender.split("@")[-1] if "@" in sender else ""
    lowered = body.lower()

    # A display name proves nothing. If the address claims to be the
    # representative but the domain is not the landlord's, that is a forgery
    # signal, not a rank.
    if sender != rep and rep and sender.split("@")[0] == rep.split("@")[0]:
        return Source(
            source_id, PROPERTY_MANAGER, sender, sent, claim, quote,
            "Sent from %s, which is not the landlord's domain (%s), while using "
            "the authorized representative's name. Treated as unverified and "
            "not acted on." % (domain or "an unknown domain", landlord_domain),
            is_suspect=True,
        )

    if sender == rep:
        carries_instrument = has_attachment and any(m in lowered for m in EXECUTED_MARKERS)
        if carries_instrument:
            return Source(
                source_id, EXECUTED_AMENDMENT, sender, sent, claim, quote,
                "From %s, the representative the lease names as authorized to "
                "execute amendments, attaching the countersigned instrument."
                % sender,
            )
        return Source(
            source_id, AUTHORIZED_REP, sender, sent, claim, quote,
            "Written confirmation from %s, the authorized representative, but "
            "without an executed instrument attached." % sender,
        )

    return Source(
        source_id, PROPERTY_MANAGER, sender, sent, claim, quote,
        "From %s, who is not named in the lease's notices clause. The lease "
        "provides that such correspondence is informational only and does not "
        "modify the lease." % sender,
    )


def decide(sources: Sequence[Source]) -> Decision:
    """Which source governs, or whether a human has to.

    Two rules, both from the lease rather than from preference. A higher-ranked
    source governs over a lower-ranked one. Two sources of equal rank that
    disagree settle nothing.
    """
    usable = [s for s in sources if not s.is_suspect]
    if not usable:
        return Decision(False, None, list(sources),
                        "No source survived verification." if sources
                        else "No source was found.")

    best = min(s.rank for s in usable)
    top = [s for s in usable if s.rank == best]

    if len(top) > 1 and len({s.claim for s in top}) > 1:
        return Decision(
            False, None, top,
            "Two sources of equal authority (%s) disagree, so neither governs."
            % RANK_NAMES.get(best, "same rank"),
        )

    trusted = top[0]
    lower = [s for s in usable if s.rank > best and s.claim != trusted.claim]

    if lower:
        return Decision(
            True, trusted, lower,
            "Trusted %s over %s, because the lease provides that the latter "
            "does not modify its terms."
            % (trusted.rank_name, lower[0].rank_name),
        )

    if trusted.rank > AUTHORIZED_REP:
        return Decision(
            False, trusted, [],
            "The only source is %s, which the lease does not treat as capable "
            "of modifying it." % trusted.rank_name,
        )

    return Decision(True, trusted, [],
                    "Relied on %s, uncontradicted." % trusted.rank_name)
