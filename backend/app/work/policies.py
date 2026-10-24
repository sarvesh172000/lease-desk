"""Policies: the rule format, and deterministic evaluation (PHASE_2.md group 10).

PHASE_2 names this module `engine/policies.py`. `engine/` is Person A's
folder (the lease-math engines), and a policy is work: it is proposed by an
agent, approved by a controller through transition(), and cited on the events
it drives. So it lives here, in `work/`, next to the state machine it uses.

The rule format (JSON, stored in `policy.rule`)
-----------------------------------------------

    {
      "name": "answer:LEASE-01:cam_estimate:approve",     stable across versions
      "version": 1,                                        mirrors policy.version
      "description": "Pay the 2026 operating expense estimate ...",
      "origin": "onboarding" | "answer" | "manual",
      "scope": {"entity_id": null, "landlord_id": null,    at least one is set;
                "lease_id": "LEASE-01", "clinic_id": null}, every set key must match
      "when": {
        "charge_types": ["cam_estimate"],                  required, at least one
        "same_as_prior_paid": true | false | null,         billed == paid the month before
        "matches_lease": true | false | null,              within $1.00 of what the lease supports
        "min_amount": "0.00", "max_amount": "6458.33",     billed amount bounds
        "min_variance": null, "max_variance": null,        billed - supported bounds
        "checker_rules": ["amount", "operating_expense"],  which checker findings it may decide
        "description_contains": null                       case-insensitive substring
      },
      "then": {"action": "approve" | "hold" | "dispute" | null,
               "account": "6100" | null,                   treat as account X
               "trust_source": "executed_amendment" | null},  trust source Y
      "effective_from": "2026-01-01", "effective_to": null,
      "evidence_ids": ["question:7", "work_item:12", "landlord_charge:ab12...", ...]
    }

`validate_rule()` parses it with pydantic and refuses anything malformed with
one readable message: unknown keys, an empty scope, no charge type, a `then`
that does nothing, bounds the wrong way round, an end before the start.

`checker_rules` defaults to the two amount rules. A policy never decides a
charge the checker set aside as a duplicate or as billed for premises we do
not lease unless it names that rule explicitly: a habit learned from months
with one charge each says nothing about a second invoice.

Evaluation
----------
`evaluate(policies, facts)` is pure and deterministic. A policy matches a
charge when it is approved (the caller passes approved ones), the charge's
period is inside its effective dates, every scope key it sets equals the
charge's, and every `when` condition holds. A condition that needs a fact we
do not have (no prior payment, no confirmed lease) does not hold: unknown is
never a match.

When several match, the most specific wins:

  1. scope: lease (8) + clinic (4) + landlord (2) + entity (1), summed
  2. then the most `when` conditions set
  3. then the latest effective_from
  4. then the lowest policy id (the policy approved first keeps the case)

Only one version of a name is ever approved at once (approving v2 retires v1,
by trigger), so versions never compete. Matches with a different `then` than
the winner are returned as conflicts, so the caller can show them.

A decision driven by a policy cites it as `policy:<id>@v<version>` in the
event's `policy_ref` column (`transition(..., policy_ref=...)`).
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.engine import Connection

log = logging.getLogger(__name__)

POLICY_KIND = "POLICY"
POLICY_SUBJECT = "policy"
POLICY_AGENT = "agent:policy"
TOLERANCE = Decimal("1.00")          # the checker's: below this a difference is rounding
CENT = Decimal("0.01")

DEFAULT_CHECKER_RULES = ("amount", "operating_expense")
ACTIONS = ("approve", "hold", "dispute")

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.:@/-]{0,199}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,199}$")


class PolicyFormatError(ValueError):
    """A rule that does not parse. The message says what is wrong, field by field."""


# ------------------------------------------------------------------ format

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_id(value: Optional[str], what: str) -> Optional[str]:
    if value is not None and not _ID.match(value):
        raise ValueError("%s %r is not an id" % (what, value))
    return value


class Scope(_Strict):
    entity_id: Optional[str] = None
    landlord_id: Optional[str] = None
    lease_id: Optional[str] = None
    clinic_id: Optional[str] = None

    @field_validator("entity_id", "landlord_id", "lease_id", "clinic_id")
    @classmethod
    def _ids(cls, value, info):
        return _check_id(value, info.field_name)

    @model_validator(mode="after")
    def _not_empty(self):
        if not any((self.entity_id, self.landlord_id, self.lease_id, self.clinic_id)):
            raise ValueError("scope must name at least one of entity_id, landlord_id, "
                             "lease_id, clinic_id: a policy for everything is not a policy")
        return self

    @property
    def specificity(self) -> int:
        return ((8 if self.lease_id else 0) + (4 if self.clinic_id else 0)
                + (2 if self.landlord_id else 0) + (1 if self.entity_id else 0))


Money = Optional[Decimal]


class When(_Strict):
    charge_types: List[str] = Field(..., min_length=1, max_length=20)
    same_as_prior_paid: Optional[bool] = None
    matches_lease: Optional[bool] = None
    min_amount: Money = None
    max_amount: Money = None
    min_variance: Money = None
    max_variance: Money = None
    checker_rules: List[str] = Field(default_factory=lambda: list(DEFAULT_CHECKER_RULES),
                                     min_length=1, max_length=10)
    description_contains: Optional[str] = Field(None, min_length=1, max_length=200)

    @field_validator("charge_types", "checker_rules")
    @classmethod
    def _names(cls, values, info):
        for v in values:
            _check_id(v, info.field_name)
        if len(set(values)) != len(values):
            raise ValueError("%s has duplicates" % info.field_name)
        return values

    @field_validator("min_amount", "max_amount", "min_variance", "max_variance")
    @classmethod
    def _money(cls, value):
        if value is not None:
            if not value.is_finite():
                raise ValueError("must be a finite amount")
            value = value.quantize(CENT)
        return value

    @model_validator(mode="after")
    def _bounds(self):
        for lo, hi in (("min_amount", "max_amount"), ("min_variance", "max_variance")):
            a, b = getattr(self, lo), getattr(self, hi)
            if a is not None and b is not None and a > b:
                raise ValueError("%s %s is above %s %s" % (lo, a, hi, b))
        for name in ("min_amount", "max_amount"):
            v = getattr(self, name)
            if v is not None and v < 0:
                raise ValueError("%s must not be negative" % name)
        return self

    @property
    def conditions(self) -> int:
        """How many conditions narrow it, beyond the charge type."""
        return sum(1 for v in (self.same_as_prior_paid, self.matches_lease, self.min_amount,
                               self.max_amount, self.min_variance, self.max_variance,
                               self.description_contains) if v is not None)


class Then(_Strict):
    action: Optional[Literal["approve", "hold", "dispute"]] = None
    account: Optional[str] = Field(None, min_length=1, max_length=40)
    trust_source: Optional[str] = Field(None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def _does_something(self):
        if self.action is None and self.account is None and self.trust_source is None:
            raise ValueError("then must set an action (approve, hold, dispute), an account "
                             "or a trust_source")
        return self


class PolicyRule(_Strict):
    name: str
    version: int = Field(1, ge=1, le=100000)
    description: str = Field(..., min_length=1, max_length=2000)
    origin: Literal["onboarding", "answer", "manual"] = "manual"
    scope: Scope
    when: When
    then: Then
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    evidence_ids: List[str] = Field(default_factory=list, max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, value):
        if not _NAME.match(value):
            raise ValueError("name must be 1-200 letters, digits, spaces or _.:@/- "
                             "and start with a letter or digit")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def _evidence(cls, values):
        for v in values:
            if not isinstance(v, str) or ":" not in v or len(v) > 300:
                raise ValueError("evidence ids look like '<kind>:<id>', got %r" % (v,))
        return sorted(set(values))

    @model_validator(mode="after")
    def _dates(self):
        if (self.effective_from and self.effective_to
                and self.effective_to < self.effective_from):
            raise ValueError("effective_to %s is before effective_from %s"
                             % (self.effective_to, self.effective_from))
        return self

    def to_json(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    @property
    def fingerprint(self) -> str:
        """What the rule does, without its name, version, words or evidence:
        two rules with the same fingerprint decide every charge the same way."""
        body = self.model_dump(mode="json", include={"scope", "when", "then",
                                                     "effective_from", "effective_to"})
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def validate_rule(data: Any) -> PolicyRule:
    """Parse a rule or raise PolicyFormatError naming every problem."""
    if isinstance(data, PolicyRule):
        return data
    if isinstance(data, (str, bytes)):
        try:
            data = json.loads(data)
        except ValueError as exc:
            raise PolicyFormatError("policy rule is not JSON: %s" % exc) from None
    if not isinstance(data, Mapping):
        raise PolicyFormatError("policy rule must be a JSON object, got %s" % type(data).__name__)
    try:
        return PolicyRule.model_validate(dict(data))
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            where = ".".join(str(p) for p in err["loc"]) or "rule"
            problems.append("%s: %s" % (where, err["msg"]))
        raise PolicyFormatError("malformed policy rule: " + "; ".join(problems)) from None


# ------------------------------------------------------------------- facts

@dataclass(frozen=True)
class ChargeFacts:
    """What evaluation may look at about one landlord charge."""
    charge_id: str                     # landlord_charge.id
    period: date
    charge_type: str
    amount: Decimal
    lease_id: Optional[str] = None
    clinic_id: Optional[str] = None
    landlord_id: Optional[str] = None
    entity_id: Optional[str] = None
    description: str = ""
    prior_paid: Optional[Decimal] = None    # paid for this lease and type the month before
    supported: Optional[Decimal] = None     # what the confirmed lease supports
    checker_rule: Optional[str] = None      # the checker finding's rule
    checker_proposal: Optional[str] = None  # approve / hold, before any policy


@dataclass(frozen=True)
class StoredPolicy:
    id: int
    name: str
    version: int
    status: str
    rule: PolicyRule

    @property
    def ref(self) -> str:
        return policy_ref(self.id, self.version)


def policy_ref(policy_id: int, version: int) -> str:
    return "policy:%d@v%d" % (policy_id, version)


@dataclass
class Match:
    policy: StoredPolicy
    conflicts: List[StoredPolicy] = field(default_factory=list)
    others: List[StoredPolicy] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return self.policy.ref


def _money(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
    return out.quantize(CENT) if out.is_finite() else None


def conditions_hold(rule: PolicyRule, facts: ChargeFacts, *,
                    ignore_dates: bool = False) -> Optional[bool]:
    """True when the rule covers the charge, False when it does not, None when
    the scope and everything known fit but a condition needs a missing fact.
    Callers that decide treat None as no."""
    if not ignore_dates:
        if rule.effective_from and facts.period < rule.effective_from:
            return False
        if rule.effective_to and facts.period > rule.effective_to:
            return False
    s = rule.scope
    for key in ("entity_id", "landlord_id", "lease_id", "clinic_id"):
        want = getattr(s, key)
        if want is not None and getattr(facts, key) != want:
            return False
    w = rule.when
    if facts.charge_type not in w.charge_types:
        return False
    amount = facts.amount
    if w.min_amount is not None and amount < w.min_amount:
        return False
    if w.max_amount is not None and amount > w.max_amount:
        return False
    if w.description_contains is not None and \
            w.description_contains.lower() not in (facts.description or "").lower():
        return False

    unknown = False
    if facts.checker_rule is None:
        unknown = True
    elif facts.checker_rule not in w.checker_rules:
        return False
    if w.same_as_prior_paid is not None:
        if facts.prior_paid is None:      # nothing on record for the month before
            unknown = True
        elif (abs(amount - facts.prior_paid) < CENT) != w.same_as_prior_paid:
            return False
    needs_supported = (w.matches_lease is not None or w.min_variance is not None
                       or w.max_variance is not None)
    if needs_supported:
        if facts.supported is None:
            unknown = True
        else:
            variance = amount - facts.supported
            if w.matches_lease is not None and (abs(variance) <= TOLERANCE) != w.matches_lease:
                return False
            if w.min_variance is not None and variance < w.min_variance:
                return False
            if w.max_variance is not None and variance > w.max_variance:
                return False
    return None if unknown else True


def rank(policy: StoredPolicy) -> Tuple:
    """Sort key, best first (see the module docstring)."""
    r = policy.rule
    return (-r.scope.specificity, -r.when.conditions,
            -(r.effective_from or date.min).toordinal(), policy.id)


def evaluate(policies: Iterable[StoredPolicy], facts: ChargeFacts, *,
             ignore_dates: bool = False) -> Optional[Match]:
    """The policy that decides this charge, or None. Pure and deterministic.
    ignore_dates is for backtests: what a rule covers, whenever it starts."""
    matching = sorted((p for p in policies
                       if conditions_hold(p.rule, facts, ignore_dates=ignore_dates) is True),
                      key=rank)
    if not matching:
        return None
    best = matching[0]
    return Match(policy=best, others=matching[1:],
                 conflicts=[p for p in matching[1:] if p.rule.then != best.rule.then])


# ----------------------------------------------------------- the database

def load_policies(conn: Connection, statuses: Iterable[str] = ("approved",)) -> List[StoredPolicy]:
    rows = conn.execute(text("""
        SELECT id, name, version, status, rule FROM policy
         WHERE status = ANY (CAST(:s AS text[])) ORDER BY id
    """), {"s": list(statuses)}).mappings().all()
    out = []
    for r in rows:
        try:
            rule = validate_rule(r["rule"])
        except PolicyFormatError as exc:    # stored by hand, not by the learner
            log.warning("policy %s v%s ignored: %s", r["id"], r["version"], exc)
            continue
        out.append(StoredPolicy(id=r["id"], name=r["name"], version=r["version"],
                                status=r["status"], rule=rule))
    return out


def load_policy(conn: Connection, policy_id: int) -> Optional[StoredPolicy]:
    r = conn.execute(text("SELECT id, name, version, status, rule FROM policy WHERE id = :i"),
                     {"i": policy_id}).mappings().first()
    if r is None:
        return None
    return StoredPolicy(id=r["id"], name=r["name"], version=r["version"], status=r["status"],
                        rule=validate_rule(r["rule"]))


def approved_fingerprint(conn: Connection) -> str:
    """Names the set of approved policy versions; a re-run is due when it changes."""
    rows = conn.execute(text(
        "SELECT id, version FROM policy WHERE status = 'approved' ORDER BY id")).all()
    return ",".join("%d.%d" % (r.id, r.version) for r in rows) or "none"


class FactLoader:
    """Facts about charges the checker's finding does not carry: the landlord,
    the entity, and what was paid for the same lease and type the month before."""

    def __init__(self, conn: Connection):
        self.conn = conn
        self._lease: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
        self._prior: Dict[Tuple[str, str, date], Optional[Decimal]] = {}

    def lease(self, lease_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """(landlord_id, entity_id) of a lease."""
        if lease_id is None:
            return None, None
        if lease_id not in self._lease:
            row = self.conn.execute(text("""
                SELECT l.landlord_id, k.entity_id FROM lease l JOIN clinic k ON k.id = l.clinic_id
                 WHERE l.id = :l
            """), {"l": lease_id}).first()
            self._lease[lease_id] = (row.landlord_id, row.entity_id) if row else (None, None)
        return self._lease[lease_id]

    def prior_paid(self, lease_id: Optional[str], charge_type: str,
                   period: date) -> Optional[Decimal]:
        if lease_id is None:
            return None
        prev = date(period.year - (period.month == 1), (period.month - 2) % 12 + 1, 1)
        key = (lease_id, charge_type, prev)
        if key not in self._prior:
            total = self.conn.execute(text("""
                SELECT sum(amount) FROM payment
                 WHERE lease_id = :l AND charge_type = :t AND period = :p
            """), {"l": lease_id, "t": charge_type, "p": prev}).scalar()
            self._prior[key] = _money(total)
        return self._prior[key]

    def facts(self, *, charge_id: str, period: date, charge_type: str, amount: Any,
              lease_id: Optional[str], clinic_id: Optional[str], description: str = "",
              supported: Any = None, checker_rule: Optional[str] = None,
              checker_proposal: Optional[str] = None) -> ChargeFacts:
        landlord_id, entity_id = self.lease(lease_id)
        return ChargeFacts(
            charge_id=charge_id, period=period, charge_type=charge_type,
            amount=_money(amount) or Decimal("0.00"), lease_id=lease_id, clinic_id=clinic_id,
            landlord_id=landlord_id, entity_id=entity_id, description=description or "",
            prior_paid=self.prior_paid(lease_id, charge_type, period),
            supported=_money(supported), checker_rule=checker_rule,
            checker_proposal=checker_proposal)


# ------------------------------------------------------- deciding with them

def proposal_for(action: Optional[str], checker_proposal: str) -> str:
    """The work item's proposal under a policy action. A dispute is a hold
    whose evidence says `dispute: true`."""
    if action == "approve":
        return "approve"
    if action in ("hold", "dispute"):
        return "hold"
    return checker_proposal


def apply_match(match: Match, proposal: str, reason: str,
                evidence: Mapping[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
    """The proposal, reason and evidence a decision has once a policy drives
    it. What the checker said is kept beside it."""
    p = match.policy
    then = p.rule.then
    ev = dict(evidence)
    checker_proposal = ev.get("checker_proposal", proposal)
    checker_reason = ev.get("checker_reason", reason)
    for stale in ("dispute", "account", "trusted_source"):
        ev.pop(stale, None)
    ev.update({
        "checker_proposal": checker_proposal,
        "checker_reason": checker_reason,
        "policy": {"id": p.id, "version": p.version, "name": p.name, "ref": p.ref,
                   "action": then.action, "description": p.rule.description,
                   "conflicts": [{"id": c.id, "version": c.version, "name": c.name,
                                  "action": c.rule.then.action} for c in match.conflicts]},
    })
    if then.action == "dispute":
        ev["dispute"] = True
    if then.account:
        ev["account"] = then.account
    if then.trust_source:
        ev["trusted_source"] = then.trust_source
    new_proposal = proposal_for(then.action, checker_proposal)
    new_reason = "Policy %s v%d (%s): %s Checker: %s" % (
        p.name, p.version, p.ref, p.rule.description, checker_reason)
    return new_proposal, new_reason, ev


def unapply(evidence: Mapping[str, Any], proposal: str, reason: str) -> Tuple[str, str, Dict]:
    """Back to what the checker said, when the policy that drove an open item
    is no longer approved."""
    ev = dict(evidence)
    proposal = ev.pop("checker_proposal", proposal)
    reason = ev.pop("checker_reason", reason)
    for stale in ("policy", "dispute", "account", "trusted_source"):
        ev.pop(stale, None)
    return proposal, reason, ev


class PolicyBook:
    """The approved policies, loaded once, for one checking run."""

    def __init__(self, conn: Connection):
        self.policies = load_policies(conn)
        self.loader = FactLoader(conn)

    def __bool__(self) -> bool:
        return bool(self.policies)

    def decide(self, *, charge_id: str, period: date, charge_type: str, amount: Any,
               lease_id: Optional[str], clinic_id: Optional[str], description: str,
               supported: Any, checker_rule: Optional[str], proposal: str, reason: str,
               evidence: Mapping[str, Any]) -> Tuple[str, str, Dict[str, Any], Optional[str]]:
        """(proposal, reason, evidence, policy_ref). Unchanged, with no ref,
        when no approved policy covers the charge."""
        if not self.policies:
            return proposal, reason, dict(evidence), None
        facts = self.loader.facts(
            charge_id=charge_id, period=period, charge_type=charge_type, amount=amount,
            lease_id=lease_id, clinic_id=clinic_id, description=description,
            supported=supported, checker_rule=checker_rule, checker_proposal=proposal)
        match = evaluate(self.policies, facts)
        if match is None:
            return proposal, reason, dict(evidence), None
        new_proposal, new_reason, ev = apply_match(match, proposal, reason, evidence)
        return new_proposal, new_reason, ev, match.ref


# ------------------------------------------ re-deciding open items (re-run)

def apply_policies(conn: Connection, entity_id: str, period: date,
                   actor_id: str = "agent:checker") -> Dict[str, Any]:
    """Re-decide the period's open charge checks under the approved policies.

    A PROPOSED item a policy now covers is proposed again (PROPOSED ->
    propose -> PROPOSED, the machine's "revise the proposal") with the
    policy's decision and `policy_ref` on the event. One already decided
    under the same policy version is left alone, so this is idempotent. One
    whose policy is no longer approved goes back to the checker's proposal.
    Items waiting on a person (NEEDS_INFO, HELD) or already decided are not
    touched; the counts say how many.
    """
    from .roles import load_actor
    from .transitions import transition

    book = PolicyBook(conn)
    actor = load_actor(conn, actor_id)
    rows = conn.execute(text("""
        SELECT w.id, w.state, w.proposal, w.reason, w.evidence, w.clinic_id,
               c.id AS charge_id, c.lease_id, c.charge_type, c.amount, c.period,
               c.description
          FROM work_item w JOIN landlord_charge c ON c.id = w.subject_id
         WHERE w.kind = 'CHARGE_CHECK' AND w.subject_type = 'landlord_charge'
           AND w.entity_id = :e AND w.period = :p
         ORDER BY w.id
    """), {"e": entity_id, "p": period}).mappings().all()
    out = {"cited": 0, "unchanged": 0, "reverted": 0, "waiting": 0, "decided": 0, "refs": []}
    for r in rows:
        if r["state"] in ("NEEDS_INFO", "HELD"):
            out["waiting"] += 1
            continue
        if r["state"] != "PROPOSED":
            out["decided"] += 1
            continue
        ev = dict(r["evidence"] or {})
        checker_proposal = ev.get("checker_proposal", r["proposal"])
        checker_reason = ev.get("checker_reason", r["reason"])
        current = (ev.get("policy") or {}).get("ref")
        proposal, reason, new_ev, ref = book.decide(
            charge_id=r["charge_id"], period=r["period"], charge_type=r["charge_type"],
            amount=r["amount"], lease_id=r["lease_id"], clinic_id=r["clinic_id"],
            description=r["description"] or "", supported=ev.get("supported"),
            checker_rule=ev.get("rule"), proposal=checker_proposal, reason=checker_reason,
            evidence=ev)
        if ref is None and current is None:
            out["unchanged"] += 1
            continue
        if ref == current:
            out["unchanged"] += 1
            continue
        if ref is None:
            proposal, reason, new_ev = unapply(ev, r["proposal"], r["reason"])
            out["reverted"] += 1
        else:
            out["cited"] += 1
            out["refs"].append(ref)
        transition(conn, actor, r["id"], "propose", reason=reason, policy_ref=ref,
                   patch={"proposal": proposal, "reason": reason, "evidence": new_ev})
    out["refs"] = sorted(set(out["refs"]))
    return out
