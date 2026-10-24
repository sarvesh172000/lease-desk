"""Why did this stop matching?

A variance is the only thing that starts an investigation, and the mailbox is
the only place the answer lives — the amendment went to facilities and never
reached accounting. So the agent reads the corpus and nominates documents that
might explain the variance, quoting each one.

What it nominates is not what gets believed. `trust.py` ranks the candidates by
who sent them, and the lease's own notices clause decides whether any of them
is capable of modifying the lease. The model finds; the rules decide.

Three outcomes, all of them valid:

  - **Settled** — one source of sufficient authority explains it. A revised
    lease version and the adjusting entries are proposed for sign-off.
  - **Conflicted** — sources disagree, or the only candidate has no authority
    to change anything. Escalated with both sides shown.
  - **Unexplained** — nothing in the corpus accounts for it. Escalated. This
    is not a failure; a system that always finds an explanation is one that
    invents them.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from ..engine.remeasurement import Proposal, ProposedAmendment, propose
from ..llm.client import LLM, RunMeta
from .trust import Decision, Source, classify_email, decide

PROMPT_ID = "amendment_search"

SETTLED = "settled"
CONFLICTED = "conflicted"
UNEXPLAINED = "unexplained"

# How much a source's rank is worth to confidence.
RANK_WEIGHT = {1: 1.00, 2: 0.95, 3: 0.85, 4: 0.45, 5: 0.35, 6: 0.25}


# --- what the model returns ------------------------------------------------

class Candidate(BaseModel):
    source_id: str = Field(description="The document id exactly as given")
    explains_variance: bool
    claim: str = Field(description="What this document says changed, in one line")
    quote: str = Field(description="The exact sentence relied on, copied verbatim")
    effective: Optional[str] = Field(default=None, description="ISO date the change takes effect")
    new_monthly_rent: Optional[float] = None
    new_expiration: Optional[str] = None
    new_escalation_pct: Optional[float] = Field(
        default=None, description="0.025 for 2.5% per annum")


class AmendmentSearch(BaseModel):
    candidates: List[Candidate] = Field(default_factory=list)
    none_explain: bool = Field(
        description="True when nothing in the corpus accounts for the variance")
    note: str = Field(default="", description="One line on what was searched and found")


# --- what this module returns ----------------------------------------------

@dataclass
class Investigation:
    lease_id: str
    period: date
    variance: float
    outcome: str
    sources: List[Source] = field(default_factory=list)
    decision: Optional[Decision] = None
    amendment: Optional[ProposedAmendment] = None
    proposal: Optional[Proposal] = None
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)
    searched: int = 0
    meta: Optional[RunMeta] = None

    @property
    def explains(self) -> bool:
        return self.outcome == SETTLED

    @property
    def needs_human(self) -> bool:
        return True  # nothing posts without sign-off, settled or not

    @property
    def route(self) -> str:
        """Who the item goes to. A landlord fact is the regional manager's;
        an accounting judgement is the controller's."""
        if self.outcome == SETTLED:
            return "controller"
        return "regional_manager"

    def describe(self) -> str:
        if self.outcome == SETTLED:
            return "Explained by %s. %s" % (
                self.decision.trusted.source_id, self.decision.reason)
        if self.outcome == CONFLICTED:
            return self.decision.reason
        return "Nothing in %d documents explains the variance." % self.searched


def investigate(
    llm: LLM,
    lease_id: str,
    period: date,
    variance_text: str,
    documents: Sequence[Tuple[str, str]],
    senders: Dict[str, dict],
    lease_payload: dict,
    books_closed_through: date,
    variance: float = 0.0,
) -> Investigation:
    """Search the corpus, rank what comes back, and propose or escalate.

    `senders` carries the facts the ranking needs per source id: `sender`,
    `has_attachment`, `authorized_rep_email`, `landlord_domain`, `sent`.
    """
    found, meta = llm.structured(
        PROMPT_ID, AmendmentSearch,
        variables={"variance": variance_text},
        documents=list(documents),
    )

    result = Investigation(
        lease_id=lease_id, period=period, variance=variance,
        outcome=UNEXPLAINED, searched=len(documents), meta=meta,
    )

    explaining = [c for c in found.candidates if c.explains_variance]
    if found.none_explain or not explaining:
        result.reasons.append(
            found.note or "No document in the corpus accounts for the variance.")
        result.confidence = 0.0
        return result

    # The model nominated; now rank by authority, which it does not get a say in.
    for candidate in explaining:
        facts = senders.get(candidate.source_id)
        if facts is None:
            # A source id the corpus does not contain is not evidence.
            result.reasons.append(
                "Ignored %r: not a document in the corpus." % candidate.source_id)
            continue
        result.sources.append(classify_email(
            source_id=candidate.source_id,
            sender=facts.get("sender", ""),
            body=facts.get("body", ""),
            authorized_rep_email=facts.get("authorized_rep_email", ""),
            landlord_domain=facts.get("landlord_domain", ""),
            has_attachment=facts.get("has_attachment", False),
            sent=facts.get("sent"),
            claim=candidate.claim,
            quote=candidate.quote,
        ))

    if not result.sources:
        result.reasons.append("No nominated document survived verification.")
        return result

    result.decision = decide(result.sources)
    result.confidence, reasons = confidence(result.sources, result.decision)
    result.reasons.extend(reasons)

    if not result.decision.settled:
        result.outcome = CONFLICTED
        return result

    winner = next(c for c in explaining if c.source_id == result.decision.trusted.source_id)
    if winner.effective is None:
        result.outcome = CONFLICTED
        result.reasons.append(
            "The trusted source does not state when the change takes effect.")
        return result

    result.outcome = SETTLED
    result.amendment = ProposedAmendment(
        effective=date.fromisoformat(winner.effective),
        new_base_rent=winner.new_monthly_rent,
        new_expiration=(date.fromisoformat(winner.new_expiration)
                        if winner.new_expiration else None),
        escalation_kind="fixed_percent",
        escalation_amount=winner.new_escalation_pct or 0.0,
        summary=winner.claim,
    )
    result.proposal = propose(lease_payload, result.amendment, books_closed_through)
    return result


def confidence(sources: Sequence[Source], decision: Decision) -> Tuple[float, List[str]]:
    """How much the evidence supports acting, and why.

    Four factors, each stated rather than tuned, because a controller who
    cannot see why a number is 0.94 has no reason to trust it:

      - the authority of the source relied on,
      - how far it outranks the next source that disagrees,
      - whether anything of equal authority contradicts it,
      - whether any candidate failed verification.
    """
    reasons: List[str] = []
    if not decision.settled or decision.trusted is None:
        if decision.conflicting:
            reasons.append("Sources disagree, so no amount is proposed.")
        return 0.0, reasons

    trusted = decision.trusted
    score = RANK_WEIGHT.get(trusted.rank, 0.3)
    reasons.append("Relied on %s (rank %d)." % (trusted.rank_name, trusted.rank))

    contradicting = [s for s in decision.conflicting if s.claim != trusted.claim]
    if contradicting:
        gap = min(s.rank for s in contradicting) - trusted.rank
        if gap >= 2:
            score = min(1.0, score + 0.05)
            reasons.append(
                "Outranks the contradicting source by %d levels." % gap)
        else:
            score -= 0.15
            reasons.append(
                "A source only %d level below contradicts it." % gap)

    suspect = [s for s in sources if s.is_suspect]
    if suspect:
        score -= 0.05
        reasons.append(
            "%d nominated document(s) failed sender verification and were set aside."
            % len(suspect))

    return round(max(0.0, min(1.0, score)), 2), reasons
