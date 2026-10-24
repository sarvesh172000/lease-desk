"""What kind of document is this?

Everything downstream branches on the answer. A lease goes to abstraction, an
invoice to the parser, an amendment to the modification agent, a credit memo to
the dispute register. Getting it wrong does not produce a wrong number — it
produces no number, because the document goes to a reader that cannot make
sense of it.

Rules first, model second. Most documents announce themselves: a statement says
INVOICE at the top, a lease says OFFICE LEASE AGREEMENT, a portal export has
`ChargeCode` in its header. Those are decided here for nothing, in a
millisecond, with the phrase that decided it. The model is asked only when the
rules are genuinely unsure — which is the case worth spending a call on, and
the case where a human may need to look anyway.

A page with no text layer is a scan. It is not classified from text at all; it
is routed to vision, and saying so is more useful than guessing.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

LEASE = "lease"
AMENDMENT = "amendment"
SIDE_LETTER = "side_letter"
RENT_INVOICE = "rent_invoice"
CAM_ESTIMATE = "cam_estimate"
CAM_RECONCILIATION = "cam_reconciliation"
TAX_OR_INSURANCE = "tax_or_insurance_bill"
CREDIT_MEMO = "credit_memo"
LATE_NOTICE = "late_notice"
CORRESPONDENCE = "correspondence"
SCANNED = "scanned_no_text"
OTHER = "other"

# Phrases that settle it, strongest first. The phrase is reported, so a
# classification can be checked rather than taken on trust.
RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (AMENDMENT, ("second amendment", "first amendment", "third amendment",
                 "amendment to lease", "lease amendment", "countersigned amendment")),
    (SIDE_LETTER, ("side letter", "letter agreement")),
    (LEASE, ("office lease agreement", "basic lease information",
             "this lease is entered into", "base rent schedule")),
    (CAM_RECONCILIATION, ("operating expense reconciliation", "annual reconciliation",
                          "true-up", "true up", "reconciliation statement")),
    (CREDIT_MEMO, ("credit memo", "credit memorandum", "we will credit",
                   "a credit of")),
    (LATE_NOTICE, ("late charge", "notice of late payment", "past due",
                   "payment is overdue")),
    (TAX_OR_INSURANCE, ("real property tax pass-through", "tax pass-through",
                        "insurance pass-through", "certificate of insurance")),
    # A statement outranks its own line items. An invoice that happens to
    # carry an operating expense line is still an invoice, and routing it to
    # the CAM reader produces no number at all rather than a wrong one.
    (RENT_INVOICE, ("invoice", "statement total", "total due", "base rent for",
                    "remit payment")),
    # Reached only by a standalone estimate notice, which is rare: most
    # operating expense estimates arrive as a line on a statement.
    (CAM_ESTIMATE, ("operating expense estimate", "estimated operating expenses",
                    "estimated share of operating expenses")),
)

# A portal export is identified by its columns, not by prose.
PORTAL_HEADERS = ("chargecode", "chargeamt", "tenantref")

CERTAIN = 0.90
UNSURE = 0.60


@dataclass
class Classification:
    kind: str
    confidence: float
    decided_by: str              # "rules" | "model" | "no_text"
    evidence: Optional[str] = None
    alternatives: List[str] = field(default_factory=list)

    @property
    def needs_model(self) -> bool:
        return self.decided_by == "rules" and self.confidence < UNSURE

    @property
    def needs_vision(self) -> bool:
        return self.kind == SCANNED


def classify(text: str, has_text_layer: bool = True) -> Classification:
    """Classify from text. Cheap, deterministic, and explains itself."""
    if not has_text_layer or not (text or "").strip():
        return Classification(
            SCANNED, 1.0, "no_text",
            "no text layer; the document is an image and goes to vision")

    lowered = " ".join(text.lower().split())

    if any(header in lowered.replace(" ", "") for header in PORTAL_HEADERS):
        return Classification(RENT_INVOICE, 0.95, "rules",
                              "portal export columns (ChargeCode, ChargeAmt)")

    hits: Dict[str, List[str]] = {}
    for kind, phrases in RULES:
        found = [p for p in phrases if p in lowered]
        if found:
            hits.setdefault(kind, []).extend(found)

    if not hits:
        return Classification(OTHER, 0.3, "rules", None,
                              alternatives=[CORRESPONDENCE, OTHER])

    # RULES is ordered by authority: an amendment that also says "invoice"
    # is still an amendment.
    ranked = sorted(hits, key=lambda k: _rule_rank(k))
    best = ranked[0]
    phrase = hits[best][0]

    # A single weak phrase among several candidates is not a decision.
    confidence = 0.95 if len(hits[best]) > 1 else 0.82
    if len(ranked) > 2:
        confidence -= 0.25

    return Classification(
        best, round(confidence, 2), "rules",
        "matched %r" % phrase,
        alternatives=[k for k in ranked[1:3]],
    )


def classify_document(document, llm=None) -> Classification:
    """Classify a parsed `Document`, falling back to the model when unsure."""
    text = "\n".join(p.text for p in document.pages[:2])
    has_text = any(p.has_text_layer for p in document.pages)
    result = classify(text, has_text)

    if result.needs_model and llm is not None:
        return _ask_model(text, llm, result)
    return result


def _ask_model(text: str, llm, fallback: Classification) -> Classification:
    """Only reached when the rules could not decide."""
    from pydantic import BaseModel, Field

    class Guess(BaseModel):
        kind: str = Field(description="One of: %s" % ", ".join(KINDS))
        confidence: float = Field(ge=0.0, le=1.0)
        evidence: str = Field(description="The phrase that decided it, quoted")

    try:
        guess, _ = llm.structured(
            "classify_document", Guess,
            variables={"kinds": ", ".join(KINDS)},
            documents=[("document", text[:6000])],
        )
    except Exception:
        return fallback

    kind = guess.kind if guess.kind in KINDS else OTHER
    return Classification(kind, round(guess.confidence, 2), "model", guess.evidence)


KINDS = (LEASE, AMENDMENT, SIDE_LETTER, RENT_INVOICE, CAM_ESTIMATE,
         CAM_RECONCILIATION, TAX_OR_INSURANCE, CREDIT_MEMO, LATE_NOTICE,
         CORRESPONDENCE, OTHER)

_RANK = {kind: index for index, (kind, _) in enumerate(RULES)}


def _rule_rank(kind: str) -> int:
    return _RANK.get(kind, len(RULES))
