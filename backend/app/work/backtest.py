"""Backtest a policy before anyone approves it (PHASE_2.md group 10).

`backtest(conn, rule)` runs the rule over every landlord charge on record in
its scope, every period, 2025's history and the months the system has run,
and reports:

  * which decisions would change: the charge, what was decided then, what the
    policy would decide, and the dollars that moves;
  * how many dollars in all, split into released (a hold the policy would
    pay) and withheld (a payment the policy would hold);
  * conflicts with approved policies: another policy covering the same
    charges with a different `then`, and which of the two would win.

"What was decided then" is, per charge:

  * the CHARGE_CHECK work item's proposal when the system checked it
    (`approve`, `hold`, or `dispute` for a hold whose evidence says so), and
    `approve` once a controller paid it as billed;
  * otherwise what the bank export shows: paid in full is `approve`, paid in
    part is `hold`, not paid is no decision yet (counted, never a change).

The facts a rule needs (what the lease supports, which checker rule applies)
come from the checker itself: a checked charge's item evidence, or, for
months the system never checked, the checker run over that month against the
confirmed lease terms. A charge on a lease nobody has confirmed has no such
facts; a rule that needs them reports it as `unknown`, never as a match.

Effective dates are ignored here on purpose, for the rule and for the
approved policies it is compared with: the question is how the rule would
have treated history, including the months before it would start, and
which cases two rules both claim.
"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .policies import (
    CENT,
    ChargeFacts,
    PolicyRule,
    StoredPolicy,
    _money,
    conditions_hold,
    evaluate,
    load_policies,
    rank,
    validate_rule,
)

ZERO = Decimal("0.00")
MAX_ROWS = 200        # change rows kept in the result; the totals cover all of them
CANDIDATE_ID = 2**62  # stands in for an unsaved rule's id when ranking


@dataclass
class PastCharge:
    facts: ChargeFacts
    source_id: str
    invoice_id: str
    paid: Decimal = ZERO
    payment_ids: List[str] = field(default_factory=list)
    item_id: Optional[int] = None
    decision: Optional[str] = None       # approve / hold / dispute / None
    decided_by: Optional[str] = None     # work_item:<id> or payment:<id>,...


# ---------------------------------------------------------------- history

def charge_history(conn: Connection, *, lease_ids: Optional[List[str]] = None,
                   entity_id: Optional[str] = None,
                   until: Optional[date] = None) -> List[PastCharge]:
    """Every landlord charge on record (optionally for some leases, one
    entity, or periods up to `until`), with the facts a rule reads and the
    decision that was made on it."""
    where, params = ["TRUE"], {}
    if lease_ids is not None:
        where.append("c.lease_id = ANY (CAST(:leases AS text[]))")
        params["leases"] = list(lease_ids)
    if entity_id is not None:
        where.append("k.entity_id = :entity")
        params["entity"] = entity_id
    if until is not None:
        where.append("c.period <= :until")
        params["until"] = until
    rows = conn.execute(text("""
        SELECT c.id, r.source_id, c.lease_id, c.clinic_id, l.landlord_id, k.entity_id,
               c.period, c.charge_type, c.amount, c.description, c.invoice_id, c.suite
          FROM landlord_charge c
          JOIN raw_row r ON r.id = c.raw_ref
          JOIN lease l ON l.id = c.lease_id
          JOIN clinic k ON k.id = c.clinic_id
         WHERE %s
         ORDER BY c.period, r.source_id
    """ % " AND ".join(where)), params).mappings().all()
    if not rows:
        return []
    leases = sorted({r["lease_id"] for r in rows})

    items = {r.subject_id: r for r in conn.execute(text("""
        SELECT id, subject_id, state, proposal, evidence FROM work_item
         WHERE kind = 'CHARGE_CHECK' AND subject_type = 'landlord_charge'
           AND subject_id = ANY (CAST(:ids AS text[]))
    """), {"ids": [r["id"] for r in rows]}).all()}

    payments = conn.execute(text("""
        SELECT id, lease_id, invoice_id, period, charge_type, amount FROM payment
         WHERE lease_id = ANY (CAST(:leases AS text[])) ORDER BY id
    """), {"leases": leases}).all()
    paid_for: Dict[Tuple, Decimal] = defaultdict(lambda: ZERO)
    for p in payments:
        paid_for[(p.lease_id, p.charge_type, p.period)] += p.amount

    checker = _checker_facts(conn, rows, items)

    past: List[PastCharge] = []
    for r in rows:
        item = items.get(r["id"])
        ev = dict(item.evidence or {}) if item is not None else {}
        if item is not None:
            supported = _money(ev.get("supported"))
            rule = ev.get("rule")
            checker_proposal = ev.get("checker_proposal", item.proposal)
        else:
            rule, supported, checker_proposal = checker.get(r["source_id"], (None, None, None))
        period = r["period"]
        prev = date(period.year - (period.month == 1), (period.month - 2) % 12 + 1, 1)
        prior = paid_for.get((r["lease_id"], r["charge_type"], prev))
        facts = ChargeFacts(
            charge_id=r["id"], period=period, charge_type=r["charge_type"],
            amount=_money(r["amount"]) or ZERO, lease_id=r["lease_id"],
            clinic_id=r["clinic_id"], landlord_id=r["landlord_id"], entity_id=r["entity_id"],
            description=r["description"] or "", prior_paid=_money(prior),
            supported=supported, checker_rule=rule, checker_proposal=checker_proposal)
        past.append(PastCharge(facts=facts, source_id=r["source_id"],
                               invoice_id=r["invoice_id"],
                               item_id=item.id if item is not None else None))

    _allocate_payments(past, payments)
    for pc in past:
        item = items.get(pc.facts.charge_id)
        if item is not None:
            pc.decision, pc.decided_by = _item_decision(item), "work_item:%d" % item.id
        elif pc.payment_ids:
            full = pc.paid >= pc.facts.amount - CENT / 2
            pc.decision = "approve" if full else "hold"
            pc.decided_by = ",".join("payment:%s" % i for i in pc.payment_ids)
    return past


def _item_decision(item) -> Optional[str]:
    ev = item.evidence or {}
    if ev.get("resolution") == "pay_as_billed":
        return "approve"
    if item.proposal == "hold":
        return "dispute" if ev.get("dispute") else "hold"
    return item.proposal


def _allocate_payments(past: List[PastCharge], payments) -> None:
    """Payments name an invoice and a charge type, not a line. When one
    invoice has two lines of a type, a payment of exactly one line's amount
    goes to that line; whatever is left goes to the first line in order."""
    lines: Dict[Tuple, List[PastCharge]] = defaultdict(list)
    for pc in past:
        lines[(pc.invoice_id, pc.facts.charge_type, pc.facts.lease_id)].append(pc)
    for p in payments:
        group = lines.get((p.invoice_id, p.charge_type, p.lease_id))
        if not group:
            continue
        exact = [pc for pc in group if not pc.payment_ids and abs(pc.facts.amount - p.amount) < CENT]
        target = exact[0] if exact else group[0]
        target.paid += p.amount
        target.payment_ids.append(str(p.id))


def _checker_facts(conn: Connection, rows, items) -> Dict[str, Tuple]:
    """source_id -> (rule, supported, proposal) from the checker run over
    each month the system never checked, against confirmed lease terms."""
    from ..agents.checker import Charge, check_month
    from ..jobs.lease_versions import confirmed_rules

    todo: Dict[Tuple[str, date], List] = defaultdict(list)
    for r in rows:
        if r["id"] not in items:
            todo[(r["entity_id"], r["period"])].append(r)
    out: Dict[str, Tuple] = {}
    rules_by_entity: Dict[str, Any] = {}
    for (entity, period), month in sorted(todo.items()):
        if entity not in rules_by_entity:
            rules_by_entity[entity] = confirmed_rules(conn, entity).rules
        rules = rules_by_entity[entity]
        charges = [Charge(charge_id=r["source_id"], invoice_id=r["invoice_id"],
                          lease_id=r["lease_id"], clinic_id=r["clinic_id"], period=period,
                          charge_type=r["charge_type"], suite=r["suite"] or "",
                          amount=float(r["amount"]), description=r["description"] or "")
                   for r in month if r["lease_id"] in rules]
        for f in check_month(charges, rules, period):
            out[f.charge.charge_id] = (f.rule, _money(round(f.supported, 2)), f.proposal)
    return out


# --------------------------------------------------------------- backtest

def _dollars(pc: PastCharge, current: str, proposed: str) -> Tuple[Decimal, str]:
    """(amount, direction) a change of decision moves. A hold withholds only
    what the lease does not support (work/charges.payable pays the supported
    part of an upheld hold), so holding a charge that matched the lease
    changes the decision and moves no dollar."""
    amount = pc.facts.amount
    withholds = {"hold", "dispute"}
    if current == "approve" and proposed in withholds:
        supported = pc.facts.supported
        kept = min(supported, amount) if supported is not None else ZERO
        return max(amount - max(kept, ZERO), ZERO), "withheld"
    if current in withholds and proposed == "approve":
        if pc.item_id is not None:
            supported = pc.facts.supported if pc.facts.supported is not None else ZERO
            return max(amount - min(supported, amount), ZERO), "released"
        return max(amount - pc.paid, ZERO), "released"
    return ZERO, "none"


def backtest(conn: Connection, rule: Any, *, policy_id: Optional[int] = None,
             history: Optional[List[PastCharge]] = None) -> Dict[str, Any]:
    """Run one rule over all past charges in its scope. Read-only."""
    rule: PolicyRule = validate_rule(rule)
    if history is None:
        history = charge_history(conn, lease_ids=_leases_in_scope(conn, rule))
    action = rule.then.action
    candidate = StoredPolicy(id=policy_id or CANDIDATE_ID, name=rule.name,
                             version=rule.version, status="proposed", rule=rule)
    existing = [p for p in load_policies(conn)
                if p.name != rule.name and p.id != policy_id]

    matched = unknown = unchanged = new = 0
    released = withheld = ZERO
    changes: List[Dict[str, Any]] = []
    changed = 0
    conflicts: Dict[int, Dict[str, Any]] = {}
    periods = sorted({pc.facts.period for pc in history})
    for pc in history:
        verdict = conditions_hold(rule, pc.facts, ignore_dates=True)
        if verdict is None:
            unknown += 1
            continue
        if not verdict:
            continue
        matched += 1
        # Conflicts are about what the rules cover, so dates are ignored on
        # both sides: an approved rule from 2026 still collides on 2025's cases.
        other = evaluate(existing, pc.facts, ignore_dates=True)
        if other is not None and other.policy.rule.then != rule.then:
            c = conflicts.setdefault(other.policy.id, {
                "policy_id": other.policy.id, "version": other.policy.version,
                "name": other.policy.name, "action": other.policy.rule.then.action,
                "charges": 0, "examples": [],
                "winner": "this" if rank(candidate) < rank(other.policy) else "existing"})
            c["charges"] += 1
            if len(c["examples"]) < 5:
                c["examples"].append(pc.facts.charge_id)
        current = pc.decision
        if action is None or current is None:
            if current is None and action is not None:
                new += 1
            else:
                unchanged += 1
            continue
        if current == action:
            unchanged += 1
            continue
        dollars, direction = _dollars(pc, current, action)
        changed += 1
        if direction == "released":
            released += dollars
        elif direction == "withheld":
            withheld += dollars
        if len(changes) < MAX_ROWS:
            changes.append({
                "charge_id": pc.facts.charge_id, "charge_ref": pc.source_id,
                "period": pc.facts.period.isoformat(), "lease_id": pc.facts.lease_id,
                "clinic_id": pc.facts.clinic_id, "charge_type": pc.facts.charge_type,
                "amount": float(pc.facts.amount), "current": current,
                "decided_by": pc.decided_by, "policy": action,
                "dollars": float(dollars), "direction": direction})

    result = {
        "policy": {"id": policy_id, "name": rule.name, "version": rule.version,
                   "fingerprint": rule.fingerprint},
        "periods": {"first": periods[0].isoformat() if periods else None,
                    "last": periods[-1].isoformat() if periods else None,
                    "count": len(periods)},
        "charges_scanned": len(history),
        "matched": matched,
        "unknown": unknown,
        "unchanged": unchanged,
        "new_decisions": new,
        "changed": changed,
        "dollars": float(released + withheld),
        "released": float(released),
        "withheld": float(withheld),
        "changes": changes,
        "conflicts": sorted(conflicts.values(), key=lambda c: c["policy_id"]),
        "effective_dates_ignored": True,
    }
    result["digest"] = hashlib.sha256(json.dumps(
        {k: v for k, v in result.items()}, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return result


def _leases_in_scope(conn: Connection, rule: PolicyRule) -> List[str]:
    s = rule.scope
    where, params = [], {}
    for key, column in (("entity_id", "k.entity_id"), ("landlord_id", "l.landlord_id"),
                        ("lease_id", "l.id"), ("clinic_id", "l.clinic_id")):
        value = getattr(s, key)
        if value is not None:
            where.append("%s = :%s" % (column, key))
            params[key] = value
    return list(conn.execute(text("""
        SELECT l.id FROM lease l JOIN clinic k ON k.id = l.clinic_id WHERE %s ORDER BY l.id
    """ % (" AND ".join(where) or "TRUE")), params).scalars())


def summary(result: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The few numbers a list shows."""
    if not result:
        return None
    return {k: result.get(k) for k in ("matched", "changed", "dollars", "released", "withheld",
                                       "unknown", "digest")} | {
        "conflicts": len(result.get("conflicts") or ())}
