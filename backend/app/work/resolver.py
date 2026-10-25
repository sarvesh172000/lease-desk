"""The resolver: which source to believe, how sure we are, and who has to say.

Every work item the checker opens carries, in its evidence:

    sources             each source: its trust rank, the value it claims, its citation
    decision            proceed, hold or ask, with the human-readable explanation
    confidence          one number between 0 and 1 ...
    confidence_reasons  ... and the sentences that produced it
    route, asked_to     who acts next, and why
    payment_due         the invoice's due date, for the busy-approver rules

Nothing here calls a model. The ranking is the lease's own (who may change it
is a fact in its notices clause), so it is code, tested, and shown to a
person verbatim.

Source trust ranking (docs/phases/PHASE_2.md, agents/trust.py)
---------------------------------------------------------------
  1  executed amendment or side letter signed by both parties
  2  the original executed lease
  3  written confirmation from the landlord's authorized representative
  4  email from property management without stated authority
  5  landlord invoice or statement
  6  payment history, the previous accountant's tracker

Decision rule (`decide`)
------------------------
Suspect sources (a forged sender) are set aside first. Then, in order:

  * an approved policy covers the case       -> PROCEED, citing the policy
  * no usable source                         -> ASK
  * two sources of the top rank disagree     -> ASK   (same-rank conflict)
  * everything agrees                        -> PROCEED, unless the best source is
                                                below rank 3 (nothing with authority
                                                to set the amount): ASK
  * a lower rank contradicts the trusted one -> the item is HELD and a person asked:
      - the contradicting source is a person claiming a change (rank 3 or 4: the
        authorized representative's letter, a property manager's email): ASK, a
        question goes out because only someone who knows the landlord can say
        whether that agreement exists
      - the contradicting source only reports (rank 5 or 6: an invoice, payment
        history): HOLD, the trusted amount is held for review and the reviewer's
        sign-off is the answer; there is no fact a person has to supply
An executed amendment (rank 1) supersedes the original lease (rank 2) by
definition, so the lease disagreeing with it is "superseded", not a conflict.

Confidence (`confidence`)
-------------------------
    e  extraction confidence of the trusted source: lease_term.confidence for the
       fields the decision rests on (the citation score), 1.0 when the value is the
       lease form's own clause or a structured export
    q  read quality of the trusted source's page: 1.0 for a born-digital text layer,
       lower for a scan as the reader scored it
    A  source agreement: the trust weight of the sources that agree with the trusted
       value over the trust weight of every usable source, with weights
       w = {1: 1.0, 2: 0.9, 3: 0.7, 4: 0.5, 5: 0.3, 6: 0.2}
    G  trust gap: 1.0 when nothing contradicts, else min(1, 0.5 + 0.125 * gap) where
       gap = rank of the highest contradicting source - rank of the trusted one
       (gap 0, a same-rank conflict, gives 0.5; gap 4 or more gives 1.0)
    P  policy coverage: 0.6 when an approved policy covers the case, else 0

    raw        = e * q * A * G
    confidence = 1 - (1 - raw) * (1 - P), rounded half-up to 2 places

The demo beat: the lease's CAM cap (rank 2, e = 0.95) against a March email from
an unauthorized property manager (rank 4) and the invoice that billed what the
email says (rank 5): A = 0.9 / (0.9 + 0.5 + 0.3) = 0.529, G = 0.75 (gap 2), so
0.95 * 1.0 * 0.529 * 0.75 = 0.377 -> 0.38.

Routing (`choose_route`)
------------------------
  landlord facts (HOLD, ASK)                 -> the clinic's regional manager
  accounting judgements, policies, a lease
  changed by an executed amendment           -> the controller
  payment release (PROCEED)                  -> the AP clerk
  anything at stake >= the materiality threshold (LEASEDESK_MATERIALITY,
  default $10,000)                            -> also the controller

Busy approvers: a question is due QUESTION_DUE_BUSINESS_DAYS business days
after it is asked, on the business clock (jobs/clock.py). jobs/reminders.py
sends the reminders, escalates after the SLA, and releases the undisputed part
when the payment due date comes first.

Policies (B6) plug in without this module importing them: register a function
with `register_policy_hook(fn)`; it is called with (conn, context) and returns a
`PolicyMatch` or None.
"""

import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..agents.trust import (
    AUTHORIZED_REP,
    EXECUTED_AMENDMENT,
    LANDLORD_INVOICE,
    ORIGINAL_LEASE,
    PAYMENT_HISTORY,
    PROPERTY_MANAGER,
    RANK_NAMES,
)
from ..engine.charges import within_tolerance

PROCEED = "proceed"
HOLD = "hold"
ASK = "ask"

RANK_WEIGHT = {1: 1.0, 2: 0.9, 3: 0.7, 4: 0.5, 5: 0.3, 6: 0.2}
POLICY_LIFT = 0.6
DEFAULT_MATERIALITY = Decimal("10000.00")

QUESTION_DUE_BUSINESS_DAYS = 3
REMIND_EVERY_BUSINESS_DAYS = 2
ESCALATE_AFTER_BUSINESS_DAYS = 5
DUE_HOUR_UTC = 17

RESOLVER_ACTOR = "agent:resolver"

REGIONAL_MANAGER = "regional_manager"
CONTROLLER = "controller"
AP_CLERK = "ap_clerk"

LANDLORD_FACT = "landlord_fact"
ACCOUNTING = "accounting_judgement"
PAYMENT_RELEASE = "payment_release"

# Item kinds whose question is an accounting judgement whatever the sources say.
ACCOUNTING_KINDS = frozenset({"POLICY", "POLICY_PROPOSAL", "REMEASUREMENT",
                              "LEASE_MODIFICATION", "ACCRUAL", "CLOSE"})

# Why a source of this rank cannot, on its own, change what a higher one says.
WHY_LOWER = {
    ORIGINAL_LEASE: "an amendment signed by both parties supersedes the original lease",
    AUTHORIZED_REP: "a letter from the representative is not an amendment signed by both "
                    "parties",
    PROPERTY_MANAGER: "property management has no stated authority to change the lease, and "
                      "its notices clause makes such correspondence informational only",
    LANDLORD_INVOICE: "an invoice reports what the landlord billed; it cannot change what the "
                      "lease says",
    PAYMENT_HISTORY: "payment history shows what was paid, not what is owed",
}

# Which lease terms a checker rule rests on, for the extraction confidence.
RULE_TERMS = {
    "amount": ("base_rent_monthly", "escalation_amount", "escalation_kind", "commencement"),
    "operating_expense": ("cam_estimate_psf_annual", "rentable_sf"),
}


# ------------------------------------------------------------------ shapes

@dataclass(frozen=True)
class Source:
    """One thing that claims a value for the item, and how far to trust it."""
    source_id: str
    kind: str                      # amendment, lease, authorized_rep, property_manager, ...
    rank: int
    label: str
    value: Any                     # dollars (a number) or a text claim
    claim: str
    citation: Mapping[str, Any] = field(default_factory=dict)
    extraction_confidence: Optional[float] = None
    read_quality: Optional[float] = None
    suspect: bool = False
    note: str = ""

    @property
    def rank_name(self) -> str:
        return RANK_NAMES.get(self.rank, "unranked source")

    def to_dict(self) -> Dict[str, Any]:
        return {"source_id": self.source_id, "kind": self.kind, "rank": self.rank,
                "rank_name": self.rank_name, "label": self.label, "value": _jsonable(self.value),
                "claim": self.claim, "citation": dict(self.citation),
                "extraction_confidence": self.extraction_confidence,
                "read_quality": self.read_quality, "suspect": self.suspect, "note": self.note}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Source":
        return cls(source_id=str(d.get("source_id")), kind=str(d.get("kind") or ""),
                   rank=int(d.get("rank") or PAYMENT_HISTORY), label=str(d.get("label") or ""),
                   value=d.get("value"), claim=str(d.get("claim") or ""),
                   citation=dict(d.get("citation") or {}),
                   extraction_confidence=_opt_float(d.get("extraction_confidence")),
                   read_quality=_opt_float(d.get("read_quality")),
                   suspect=bool(d.get("suspect")), note=str(d.get("note") or ""))


@dataclass(frozen=True)
class PolicyMatch:
    """An approved policy that covers the case (B6 builds these)."""
    policy_id: str
    version: int
    then: str                      # what the policy says to do: approve, hold, ...
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {"policy_id": self.policy_id, "version": self.version, "then": self.then,
                "reason": self.reason}


@dataclass
class Decision:
    action: str                                  # proceed, hold, ask
    trusted: Optional[Source]
    explanation: str
    agreeing: List[Source] = field(default_factory=list)
    contradicting: List[Source] = field(default_factory=list)
    superseded: List[Source] = field(default_factory=list)
    set_aside: List[Source] = field(default_factory=list)
    trust_gap: Optional[int] = None
    policy: Optional[PolicyMatch] = None
    reference: Optional[Source] = None           # the source confidence is measured from

    @property
    def needs_answer(self) -> bool:
        return self.action == ASK

    @property
    def lease_changed(self) -> bool:
        return self.trusted is not None and self.trusted.rank == EXECUTED_AMENDMENT \
            and bool(self.superseded)

    def to_dict(self) -> Dict[str, Any]:
        ids = lambda xs: [s.source_id for s in xs]  # noqa: E731
        return {"action": self.action, "explanation": self.explanation,
                "trusted": self.trusted.source_id if self.trusted else None,
                "agreeing": ids(self.agreeing), "contradicting": ids(self.contradicting),
                "superseded": ids(self.superseded), "set_aside": ids(self.set_aside),
                "trust_gap": self.trust_gap,
                "policy": self.policy.to_dict() if self.policy else None}


@dataclass
class Route:
    role: str
    nature: str
    asked_to: Optional[str]
    also_to: List[str]
    amount_at_stake: Decimal
    material: bool
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "nature": self.nature, "asked_to": self.asked_to,
                "also_to": list(self.also_to), "amount_at_stake": float(self.amount_at_stake),
                "material": self.material, "reasons": list(self.reasons)}


# ---------------------------------------------------------- the decision

def agrees(a: Any, b: Any) -> bool:
    """Two claimed values agree: dollars within the checker's own tolerance,
    text when it says the same thing."""
    x, y = _number(a), _number(b)
    if x is not None and y is not None:
        return within_tolerance(x, y)
    if x is not None or y is not None:
        return False
    return " ".join(str(a).lower().split()) == " ".join(str(b).lower().split())


def decide(sources: Sequence[Source], policy: Optional[PolicyMatch] = None) -> Decision:
    """The trust ranking as code. See the module docstring for the table."""
    set_aside = [s for s in sources if s.suspect]
    usable = [s for s in sources if not s.suspect and s.value is not None]
    aside_note = ("" if not set_aside else " Set aside %s: %s." % (
        _plural(len(set_aside), "source"), "; ".join(
            "%s (%s)" % (s.label, s.note or "failed sender verification") for s in set_aside)))

    if not usable:
        return Decision(ASK, None, "No usable source states a value, so there is nothing to "
                        "decide from; asking." + aside_note, set_aside=set_aside)

    best = min(s.rank for s in usable)
    top = [s for s in usable if s.rank == best]
    trusted = top[0]
    agreeing = [s for s in usable if agrees(s.value, trusted.value)]
    others = [s for s in usable if not agrees(s.value, trusted.value)]
    superseded = [s for s in others if trusted.rank == EXECUTED_AMENDMENT
                  and s.rank == ORIGINAL_LEASE]
    contradicting = [s for s in others if s not in superseded]

    if policy is not None:
        return Decision(
            PROCEED, trusted, "Proceeded under approved policy %s v%d (%s): %s%s.%s" % (
                policy.policy_id, policy.version, policy.then, policy.reason.rstrip("."),
                "" if not contradicting else "; it covers the disagreement between %s and %s"
                % (trusted.label, contradicting[0].label), aside_note),
            agreeing, contradicting, superseded, set_aside,
            trust_gap=_gap(trusted, contradicting), policy=policy, reference=trusted)

    same_rank = [s for s in top if not agrees(s.value, trusted.value)]
    if same_rank:
        other = same_rank[0]
        return Decision(
            ASK, None, "Did not pick a side: two sources of equal authority (%s, rank %d) "
            "disagree. %s says %s; %s says %s. Neither governs, so a person is asked.%s" % (
                trusted.rank_name, best, trusted.label, _show(trusted.value), other.label,
                _show(other.value), aside_note),
            agreeing, contradicting, superseded, set_aside, trust_gap=0, reference=trusted)

    if not contradicting:
        if trusted.rank > AUTHORIZED_REP:
            return Decision(
                ASK, trusted, "The best source is %s (rank %d), which cannot set the amount on "
                "its own, and nothing with authority confirms %s; asking.%s" % (
                    trusted.rank_name, trusted.rank, _show(trusted.value), aside_note),
                agreeing, [], superseded, set_aside, reference=trusted)
        why = ("All %s agree on %s: %s." % (_plural(len(agreeing), "source"),
                                           _show(trusted.value),
                                           ", ".join(s.label for s in agreeing))
               if len(agreeing) > 1 else "Relied on %s, uncontradicted." % trusted.label)
        if superseded:
            why = "Trusted %s over %s because %s. %s" % (
                trusted.label, superseded[0].label, WHY_LOWER[ORIGINAL_LEASE], why)
        return Decision(PROCEED, trusted, why + " Proceeding." + aside_note, agreeing, [],
                        superseded, set_aside, reference=trusted)

    gap = _gap(trusted, contradicting)
    claimants = [s for s in contradicting if s.rank <= PROPERTY_MANAGER]
    if claimants:
        c = claimants[0]
        return Decision(
            ASK, trusted, "Did not pick a side: %s (%s, rank %d) says %s, against %s (%s, "
            "rank %d), which says %s. A lower-ranked source cannot override a higher one on "
            "its own (%s), but it may reflect an agreement we have not seen, so the item is "
            "held and a person who knows the landlord is asked.%s" % (
                c.label, c.rank_name, c.rank, _show(c.value), trusted.label, trusted.rank_name,
                trusted.rank, _show(trusted.value), WHY_LOWER.get(c.rank, "it ranks lower"),
                aside_note),
            agreeing, contradicting, superseded, set_aside, trust_gap=gap, reference=trusted)

    c = min(contradicting, key=lambda s: s.rank)
    diff = _difference(c.value, trusted.value)
    return Decision(
        HOLD, trusted, "Trusted %s over %s because %s. %s says %s; %s says %s.%s Held for "
        "review.%s" % (
            trusted.label, c.label, WHY_LOWER.get(c.rank, "it ranks lower"), _cap(trusted.label),
            _show(trusted.value), c.label, _show(c.value),
            " The %s difference is held." % _money(diff) if diff is not None else "",
            aside_note),
        agreeing, contradicting, superseded, set_aside, trust_gap=gap, reference=trusted)


def _gap(trusted: Source, contradicting: Sequence[Source]) -> Optional[int]:
    if not contradicting:
        return None
    return min(s.rank for s in contradicting) - trusted.rank


# -------------------------------------------------------------- confidence

def confidence(decision: Decision) -> Tuple[float, List[str]]:
    """The documented formula (module docstring): (score, reasons)."""
    ref = decision.reference
    if ref is None:
        return 0.0, ["No usable source, so confidence is 0."]
    reasons: List[str] = []

    e = ref.extraction_confidence
    if e is None:
        e = 1.0
        reasons.append("Extraction 1.00: %s is stated by the lease form or a structured "
                       "export, not read by a model." % ref.label)
    else:
        e = _unit(e)
        reasons.append("Extraction %.2f: the citation score of %s." % (e, ref.label))

    q = ref.read_quality
    if q is None:
        q = 1.0
        reasons.append("Read quality 1.00: born-digital text, no OCR.")
    else:
        q = _unit(q)
        reasons.append("Read quality %.2f: the page as the reader scored it." % q)

    usable = decision.agreeing + decision.contradicting
    total = sum(RANK_WEIGHT.get(s.rank, 0.2) for s in usable)
    agree_w = sum(RANK_WEIGHT.get(s.rank, 0.2) for s in decision.agreeing)
    a = agree_w / total if total else 0.0
    reasons.append("Agreement %.2f: %d of %d sources (trust weight %.1f of %.1f) agree with %s."
                   % (a, len(decision.agreeing), len(usable), agree_w, total, ref.label))
    if decision.superseded:
        reasons.append("%s superseded by %s, not counted as a conflict." % (
            ", ".join(s.label for s in decision.superseded), ref.label))
    if decision.set_aside:
        reasons.append("%s set aside after sender verification, not counted."
                       % _plural(len(decision.set_aside), "source"))

    gap = decision.trust_gap
    if gap is None:
        g = 1.0
        reasons.append("Trust gap: nothing contradicts it (factor 1.00).")
    else:
        g = min(1.0, 0.5 + 0.125 * max(gap, 0))
        reasons.append("Trust gap %d: the closest contradicting source is %d rank(s) below "
                       "(factor %.2f)." % (gap, gap, g) if gap else
                       "Trust gap 0: a source of equal rank contradicts it (factor 0.50).")

    p = POLICY_LIFT if decision.policy is not None else 0.0
    reasons.append("Policy: %s." % (
        "approved policy %s v%d covers it (lift %.1f)" % (
            decision.policy.policy_id, decision.policy.version, p)
        if decision.policy else "no approved policy covers it"))

    raw = e * q * a * g
    score = 1 - (1 - raw) * (1 - p)
    score = float(Decimal(repr(score)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    reasons.append("Confidence %.2f = 1 - (1 - %.2f x %.2f x %.2f x %.2f) x (1 - %.1f)."
                   % (score, e, q, a, g, p))
    return score, reasons


# ----------------------------------------------------------------- routing

def materiality() -> Decimal:
    raw = os.environ.get("LEASEDESK_MATERIALITY")
    try:
        return Decimal(raw) if raw else DEFAULT_MATERIALITY
    except InvalidOperation:
        return DEFAULT_MATERIALITY


def choose_route(decision: Decision, *, kind: str, amount_at_stake: Any,
                 threshold: Optional[Decimal] = None) -> Tuple[str, str, bool, List[str]]:
    """(role, nature, material, reasons): who acts next, from what is being
    decided. Pure; `route()` resolves the role to a person."""
    threshold = materiality() if threshold is None else Decimal(str(threshold))
    stake = abs(_decimal(amount_at_stake))
    reasons: List[str] = []
    if kind in ACCOUNTING_KINDS:
        role, nature = CONTROLLER, ACCOUNTING
        reasons.append("A %s item is an accounting judgement: the controller's." % kind)
    elif decision.lease_changed:
        role, nature = CONTROLLER, ACCOUNTING
        reasons.append("An executed amendment changed the lease; remeasuring it is an "
                       "accounting judgement: the controller's.")
    elif decision.action == ASK:
        role, nature = REGIONAL_MANAGER, LANDLORD_FACT
        reasons.append("What the landlord agreed to is a landlord fact: the store's "
                       "regional manager knows it.")
    elif decision.action == HOLD:
        role, nature = REGIONAL_MANAGER, LANDLORD_FACT
        reasons.append("Whether the landlord's bill stands is a landlord fact: the clinic's "
                       "regional manager signs off the hold.")
    else:
        role, nature = AP_CLERK, PAYMENT_RELEASE
        reasons.append("Nothing is in dispute%s; what is left is releasing payment: the AP "
                       "clerk's." % (" (policy %s)" % decision.policy.policy_id
                                     if decision.policy else ""))
    material = stake >= threshold
    if material and role != CONTROLLER:
        reasons.append("%s at stake is at or over the %s materiality threshold, so the "
                       "controller sees it too." % (_money(stake), _money(threshold)))
    return role, nature, material, reasons


def actor_for(conn: Connection, role: str, *, region_id: Optional[str] = None,
              entity_id: Optional[str] = None) -> Optional[str]:
    """The active person who holds `role` for this region and entity."""
    if role == REGIONAL_MANAGER:
        manager = conn.execute(text("""
            SELECT a.id FROM region r JOIN actor a ON a.id = r.manager_id
             WHERE r.id = :r AND a.active AND a.role = 'regional_manager'
        """), {"r": region_id}).scalar()
        if manager:
            return manager
        return conn.execute(text("""
            SELECT id FROM actor WHERE role = 'regional_manager' AND active AND region_id = :r
             ORDER BY id LIMIT 1
        """), {"r": region_id}).scalar()
    return conn.execute(text("""
        SELECT id FROM actor WHERE role = :role AND active
           AND (entity_id IS NULL OR entity_id = :e)
         ORDER BY (entity_id IS NULL), id LIMIT 1
    """), {"role": role, "e": entity_id}).scalar()


def route(conn: Connection, decision: Decision, *, kind: str, amount_at_stake: Any,
          region_id: Optional[str], entity_id: Optional[str],
          threshold: Optional[Decimal] = None) -> Route:
    role, nature, material, reasons = choose_route(decision, kind=kind,
                                                   amount_at_stake=amount_at_stake,
                                                   threshold=threshold)
    asked_to = actor_for(conn, role, region_id=region_id, entity_id=entity_id)
    if asked_to is None:
        reasons.append("No active %s for this %s; nobody is named." % (
            role.replace("_", " "), "region" if role == REGIONAL_MANAGER else "entity"))
    also: List[str] = []
    if material and role != CONTROLLER:
        controller = actor_for(conn, CONTROLLER, entity_id=entity_id)
        if controller and controller != asked_to:
            also.append(controller)
    return Route(role, nature, asked_to, also, abs(_decimal(amount_at_stake)), material, reasons)


# ----------------------------------------------------------- business days

def add_business_days(start: date, days: int) -> date:
    """`days` weekdays after `start` (Saturday and Sunday are not business days)."""
    d = start
    left = days
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


def business_days_between(start: date, end: date) -> int:
    """Weekdays in (start, end]; 0 when end is not after start."""
    if end <= start:
        return 0
    count = 0
    d = start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return count


def due_at(due_on: date) -> datetime:
    return datetime.combine(due_on, time(DUE_HOUR_UTC), tzinfo=timezone.utc)


# --------------------------------------------------- sources of a charge

def charge_sources(conn: Connection, evidence: Mapping[str, Any]) -> List[Source]:
    """The lease clause (rank 2), the invoice (rank 5) and the payment history
    (rank 6) for one CHARGE_CHECK item, from the checker's evidence and the
    rows it names. Missing rows are simply missing sources, never invented."""
    out: List[Source] = []
    charge = _charge_row(conn, evidence.get("charge_id"))
    lease_id = evidence.get("lease_id") or (charge or {}).get("lease_id")
    charge_type = evidence.get("charge_type") or (charge or {}).get("charge_type") or "charge"
    period = (charge or {}).get("period")
    label_period = period.strftime("%B %Y") if isinstance(period, date) else "the period"
    supported = _number(evidence.get("supported"))
    billed = _number(evidence.get("billed"))
    if billed is None and charge is not None:
        billed = float(charge["amount"])

    if supported is not None:
        proof = evidence.get("proof") if isinstance(evidence.get("proof"), Mapping) else {}
        version_id = evidence.get("lease_version_id")
        section = proof.get("section")
        out.append(Source(
            source_id="lease:%s%s" % (lease_id, ":v%s" % _version_number(conn, version_id)
                                      if version_id else ""),
            kind="lease", rank=ORIGINAL_LEASE,
            label="the lease %s%s" % (lease_id or "", " §%s" % section if section else ""),
            value=round(supported, 2),
            claim=_lease_claim(evidence, supported, label_period, charge_type),
            citation={"lease_id": lease_id, "lease_version_id": version_id, "section": section,
                      "quote": proof.get("quote"), "page": proof.get("page"),
                      "box": proof.get("box")},
            extraction_confidence=_term_confidence(conn, version_id, evidence.get("rule")),
            read_quality=_opt_float(evidence.get("read_quality"))))

    if billed is not None:
        invoice_id = evidence.get("invoice_id") or (charge or {}).get("invoice_id")
        out.append(Source(
            source_id="invoice:%s" % (evidence.get("charge_ref") or invoice_id),
            kind="invoice", rank=LANDLORD_INVOICE,
            label="invoice %s" % (invoice_id or "from the landlord"), value=round(billed, 2),
            claim="the landlord billed %s" % _money(billed),
            citation={"invoice_id": invoice_id, "charge_id": evidence.get("charge_id"),
                      "document_id": (charge or {}).get("document_id"),
                      "page": (charge or {}).get("page"),
                      "line": evidence.get("charge_ref"),
                      "due_date": (charge or {}).get("due_date")}))

    for p in _payments(conn, charge):
        out.append(Source(
            source_id="payment:%s" % p["id"], kind="payment_history", rank=PAYMENT_HISTORY,
            label="payment %s" % (p["reference"] or p["id"]), value=float(p["amount"]),
            claim="AP paid %s on %s" % (_money(p["amount"]), p["paid_on"].isoformat()),
            citation={"payment_id": p["id"], "reference": p["reference"],
                      "paid_on": p["paid_on"].isoformat(), "invoice_id": p["invoice_id"]}))
    return out


def _lease_claim(evidence: Mapping[str, Any], supported: float, period: str,
                 charge_type: str) -> str:
    rule = evidence.get("rule")
    if rule == "duplicate":
        return ("the lease provides one monthly installment for %s %s, already billed on "
                "another invoice; this second bill is supported at %s" % (
                    period, _charge_label(charge_type), _money(supported)))
    if rule == "premises":
        return ("the lease does not demise the suite billed, so it supports %s of this charge"
                % _money(supported))
    return "the lease supports %s for %s %s" % (_money(supported), period,
                                                _charge_label(charge_type))


def _charge_row(conn: Connection, charge_id: Any) -> Optional[Dict[str, Any]]:
    if not charge_id:
        return None
    row = conn.execute(text("""
        SELECT c.id, c.lease_id, c.clinic_id, c.invoice_id, c.period, c.charge_type, c.amount,
               c.document_id, c.page, r.payload->>'due_date' AS due_date
          FROM landlord_charge c LEFT JOIN raw_row r ON r.id = c.raw_ref
         WHERE c.id = :id
    """), {"id": str(charge_id)}).mappings().first()
    return dict(row) if row else None


def _payments(conn: Connection, charge: Optional[Mapping]) -> List[Mapping]:
    if charge is None:
        return []
    return list(conn.execute(text("""
        SELECT id, amount, paid_on, reference, invoice_id FROM payment
         WHERE lease_id = :l AND period = :p AND charge_type = :t AND invoice_id = :i
         ORDER BY paid_on, id LIMIT 1
    """), {"l": charge["lease_id"], "p": charge["period"], "t": charge["charge_type"],
           "i": charge["invoice_id"]}).mappings())


def _version_number(conn: Connection, version_id: Any) -> Any:
    """A lease version's number (v1, v2, ...), not its row id: row ids depend on
    what earlier, rolled-back runs consumed, and source ids must not."""
    number = conn.execute(text("SELECT version FROM lease_version WHERE id = :v"),
                          {"v": int(version_id)}).scalar()
    return version_id if number is None else number


def _term_confidence(conn: Connection, version_id: Any, rule: Any) -> Optional[float]:
    fields = RULE_TERMS.get(rule)
    if not version_id or not fields:
        return None
    value = conn.execute(text("""
        SELECT min(confidence) FROM lease_term
         WHERE lease_version_id = :v AND field = ANY (CAST(:f AS text[]))
    """), {"v": int(version_id), "f": list(fields)}).scalar()
    return None if value is None else float(value)


# --------------------------------------------------------- putting it on items

PolicyHook = Callable[[Connection, Mapping[str, Any]], Optional[PolicyMatch]]
_POLICY_HOOKS: List[PolicyHook] = []


def register_policy_hook(hook: PolicyHook) -> None:
    """B6: call `hook(conn, context)` for every decision; the first PolicyMatch wins."""
    if hook not in _POLICY_HOOKS:
        _POLICY_HOOKS.append(hook)


def unregister_policy_hook(hook: PolicyHook) -> None:
    if hook in _POLICY_HOOKS:
        _POLICY_HOOKS.remove(hook)


def policy_for(conn: Connection, context: Mapping[str, Any]) -> Optional[PolicyMatch]:
    for hook in list(_POLICY_HOOKS):
        match = hook(conn, context)
        if match is not None:
            return match
    return None


def resolve(conn: Connection, evidence: Mapping[str, Any], *, kind: str = "CHARGE_CHECK",
            region_id: Optional[str] = None, entity_id: Optional[str] = None,
            extra_sources: Iterable[Source] = (), policy: Optional[PolicyMatch] = None,
            today: Optional[date] = None, threshold: Optional[Decimal] = None) -> Dict[str, Any]:
    """Everything the resolver adds to an item's evidence, as plain JSON:
    sources, decision, confidence, confidence_reasons, route, asked_to,
    payment_due, and for an ASK the question to put (body, asked_on, due_on).
    Reads only; writing is the caller's transition."""
    sources = charge_sources(conn, evidence) + list(extra_sources)
    context = dict(evidence, kind=kind, region_id=region_id, entity_id=entity_id,
                   sources=[s.to_dict() for s in sources])
    if policy is None:
        policy = policy_for(conn, context)
    decision = decide(sources, policy)
    score, reasons = confidence(decision)
    stake = _stake(decision, evidence)
    r = route(conn, decision, kind=kind, amount_at_stake=stake, region_id=region_id,
              entity_id=entity_id, threshold=threshold)
    due = (_charge_row(conn, evidence.get("charge_id")) or {}).get("due_date")
    out: Dict[str, Any] = {
        "sources": [s.to_dict() for s in sources],
        "decision": decision.to_dict(),
        "confidence": score,
        "confidence_reasons": reasons,
        "route": r.to_dict(),
        "asked_to": r.asked_to,
        "payment_due": due,
    }
    if decision.needs_answer and r.asked_to:
        from ..jobs.clock import today as business_today

        asked_on = today or business_today(conn)
        due_on = add_business_days(asked_on, QUESTION_DUE_BUSINESS_DAYS)
        out["question"] = {"body": _question_body(decision, r), "asked_to": r.asked_to,
                           "asked_on": asked_on.isoformat(), "due_on": due_on.isoformat()}
    return out


def ask_if_needed(conn: Connection, actor, item_id: int,
                  evidence: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """When the resolver decided ASK and found someone to ask, put the
    question through the existing `ask` transition, due on the business
    clock. Returns the item row, or None when nothing was asked."""
    from .transitions import transition

    question = evidence.get("question")
    if not isinstance(question, Mapping) or not question.get("asked_to"):
        return None
    due_on = date.fromisoformat(question["due_on"])
    return transition(conn, actor, item_id, "ask", reason=question["body"], patch={
        "asked_to": question["asked_to"], "body": question["body"], "due_at": due_at(due_on),
    }, evidence={"asked_on": question["asked_on"], "due_on": question["due_on"],
                 "route": evidence.get("route"), "confidence": evidence.get("confidence")})


def resolve_item(conn: Connection, actor, item_id: int, *,
                 extra_sources: Iterable[Source] = (), policy: Optional[PolicyMatch] = None,
                 today: Optional[date] = None,
                 threshold: Optional[Decimal] = None) -> Dict[str, Any]:
    """Re-resolve a PROPOSED item with more sources (an email, an amendment
    found by the modification agent): the new evidence goes on the item by
    the `ask` transition when a person must answer, else by re-proposing."""
    from .transitions import load_item, transition

    item = load_item(conn, item_id)
    evidence = dict(item.get("evidence") or {})
    added = resolve(conn, evidence, kind=item["kind"], region_id=item.get("region_id"),
                    entity_id=item.get("entity_id"), extra_sources=extra_sources,
                    policy=policy, today=today, threshold=threshold)
    evidence.update(added)
    if "question" not in added:
        evidence.pop("question", None)
    if added["decision"]["action"] == ASK and "question" in added:
        q = added["question"]
        return transition(conn, actor, item["id"], "ask", reason=q["body"], patch={
            "asked_to": q["asked_to"], "body": q["body"],
            "due_at": due_at(date.fromisoformat(q["due_on"])), "evidence": evidence,
        }, evidence={"asked_on": q["asked_on"], "due_on": q["due_on"],
                     "route": added["route"], "confidence": added["confidence"]})
    proposal = item.get("proposal")
    if added["decision"]["action"] == HOLD:
        proposal = "hold"
    elif added["decision"]["action"] == PROCEED and added["decision"].get("policy"):
        proposal = added["decision"]["policy"]["then"] or proposal
    return transition(conn, actor, item["id"], "propose",
                      reason=added["decision"]["explanation"],
                      patch={"proposal": proposal, "evidence": evidence})


def from_trust(source, *, value: Any, kind: Optional[str] = None,
               citation: Optional[Mapping[str, Any]] = None) -> Source:
    """A Source from agents/trust.py's ranking of an email or amendment, with
    the dollar value it claims for this item."""
    kinds = {EXECUTED_AMENDMENT: "amendment", AUTHORIZED_REP: "authorized_rep",
             PROPERTY_MANAGER: "property_manager"}
    sent = getattr(source, "sent", None)
    return Source(
        source_id=source.source_id, kind=kind or kinds.get(source.rank, "email"),
        rank=source.rank,
        label="%s from %s%s" % ("the amendment" if source.rank == EXECUTED_AMENDMENT
                                else "the email", source.sender or "an unknown sender",
                                " (%s)" % sent.strftime("%b %d, %Y") if sent else ""),
        value=value, claim=source.claim or source.quote,
        citation=dict(citation or {}, quote=source.quote, sender=source.sender,
                      sent=sent.isoformat() if sent else None),
        suspect=source.is_suspect, note=source.reason)


# ----------------------------------------------------------------- helpers

def _stake(decision: Decision, evidence: Mapping[str, Any]) -> Decimal:
    billed = _decimal(evidence.get("billed"))
    if decision.action == PROCEED:
        return billed
    ref = decision.reference
    trusted = _number(ref.value) if ref is not None else None
    if trusted is None:
        trusted = _number(evidence.get("supported"))
    return abs(billed - _decimal(trusted)) if trusted is not None else billed


def _question_body(decision: Decision, r: Route) -> str:
    stake = " %s is at stake." % _money(r.amount_at_stake) if r.amount_at_stake else ""
    if decision.contradicting and decision.trusted is not None:
        c = min(decision.contradicting, key=lambda s: s.rank)
        return ("%s says %s, but %s says %s. Is there an agreement with the landlord that "
                "changes this? Reply with what was agreed, or that nothing was.%s" % (
                    _cap(c.label), _show(c.value), decision.trusted.label,
                    _show(decision.trusted.value), stake))
    return decision.explanation + stake


def _difference(a: Any, b: Any) -> Optional[float]:
    x, y = _number(a), _number(b)
    return None if x is None or y is None else round(abs(x - y), 2)


def _show(value: Any) -> str:
    n = _number(value)
    return _money(n) if n is not None else '"%s"' % value


def _money(value: Any) -> str:
    return "${:,.2f}".format(float(value))


def _cap(label: str) -> str:
    return label[:1].upper() + label[1:]


def _plural(n: int, word: str) -> str:
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _charge_label(charge_type: str) -> str:
    return {"base_rent": "base rent", "cam_estimate": "operating expense estimate"}.get(
        charge_type, str(charge_type).replace("_", " "))


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        n = float(value)
        return n if n == n and n not in (float("inf"), float("-inf")) else None
    return None


def _decimal(value: Any) -> Decimal:
    n = _number(value)
    if n is None:
        try:
            return Decimal(str(value)).quantize(Decimal("0.01")) if value is not None \
                else Decimal("0.00")
        except InvalidOperation:
            return Decimal("0.00")
    return Decimal(repr(n)).quantize(Decimal("0.01"))


def _opt_float(value: Any) -> Optional[float]:
    try:
        return None if value is None or isinstance(value, bool) else float(value)
    except (TypeError, ValueError):
        return None


def _unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
