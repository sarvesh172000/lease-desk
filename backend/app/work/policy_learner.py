"""The policy learner: proposes policies from 2025's history and from people's
answers. Deterministic: no model is called, so the same history and the same
answers always propose the same rules.

    python -m app.work.policy_learner --onboard ENT-CA [--year 2025]
    python -m app.work.policy_learner --answer <question id>

Every proposal is work (PHASE_2.md group 10): a `policy` row, born
'proposed', and a POLICY work item on it (`subject_type 'policy'`) proposed by
`agent:policy` with the rule, its precedents, the decisions it was learned
from and its backtest as evidence. A controller approves or rejects it
through POST /api/items/{id}/actions/{approve|reject}; the item's state sets
the policy's status (sql/006_policies.sql). The agent that proposed it can
never approve it: can() refuses agents `approve`, and separation of duties
refuses whoever proposed.

Onboarding (`onboard`)
----------------------
What the dev company's 2025 history holds (`datagen/history.py`): every
lease's base rent and operating expense estimate, billed monthly and paid in
full, and two charges that were wrong and paid anyway (H1, April 2025 CAM
estimate $225 over the lease; H2, June 2025 rent at July's step). The habit
that history shows is "a recurring charge billed at the amount paid the
month before was paid as billed", and both mistakes happened in months the
amount changed. So for each landlord and charge type the learner counts the
precedents (billed equal to last month's payment, paid in full) and the
counter-examples (billed equal, not paid in full), and proposes

    approve <charge type> from <landlord> when same_as_prior_paid

when there are at least MIN_PRECEDENTS precedents and no counter-example. It
generalises to the landlord only when two or more of its leases agree, and to
one lease otherwise. A precedent that the confirmed lease says was over the
lease narrows the rule to `matches_lease: true`. Months the amount changed
are a second candidate ("approve a changed amount that matches the lease"),
proposed only with as many precedents; the dev history has too few, and the
result says so in `skipped`.

From answers (`learn_from_answer`)
----------------------------------
When a question on a charge check is answered, the answer is read for a
verdict (`verdict()`: pay / dispute, negations first; anything else proposes
nothing). The rule generalises only as far as one answer supports: the same
lease and charge type, the checker rule that raised it, from that period on,
and for `approve` no more than the amount the person saw. It links the
question, the answer, the work item, the charge and its document.

Rejection memory
----------------
A rejected policy keeps its row (status 'rejected') and its reason (the
POLICY item's reason and the reject event's). A candidate with the same name
is not proposed again unless it carries evidence no rejected version had:
`skipped` names the rejection, who made it and why.
"""

import argparse
import re
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .backtest import backtest
from .policies import (
    CENT,
    POLICY_AGENT,
    POLICY_KIND,
    POLICY_SUBJECT,
    TOLERANCE,
    PolicyRule,
    validate_rule,
)

MIN_PRECEDENTS = 6
YEAR = 2025
LABEL = {"base_rent": "base rent", "cam_estimate": "operating expense estimate"}

# Read in this order: a negation or a refusal anywhere means "do not pay".
_NO = re.compile(r"\b(not|never|no|don't|dont|do not|isn't|wasn't|dispute|disputed|refuse|"
                 r"wrong|incorrect|overbill\w*|reject|hold)\b|n't\b", re.I)
_YES = re.compile(r"\b(approve|approved|pay|pay it|correct|agreed|agree|confirmed|confirm|"
                  r"fine|yes|ok|okay|valid|right)\b", re.I)


class LearnerError(ValueError):
    """Nothing to learn from: no such question, or not answered."""


def verdict(answer: Optional[str]) -> Optional[str]:
    """'approve', 'dispute' or None for an answer that says neither."""
    if not answer or not answer.strip():
        return None
    if _NO.search(answer):
        return "dispute"
    if _YES.search(answer):
        return "approve"
    return None


# ------------------------------------------------------------- proposing

def _rejections(conn: Connection, name: str) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute(text("""
        SELECT p.id, p.version, p.rule, w.id AS item_id, w.reason,
               (SELECT e.actor_id FROM audit_event e
                 WHERE e.subject_type = 'work_item' AND e.subject_id = w.id::text
                   AND e.action = 'reject' AND e.allowed ORDER BY e.seq DESC LIMIT 1) AS rejected_by,
               (SELECT e.at FROM audit_event e
                 WHERE e.subject_type = 'work_item' AND e.subject_id = w.id::text
                   AND e.action = 'reject' AND e.allowed ORDER BY e.seq DESC LIMIT 1) AS rejected_at
          FROM policy p
          LEFT JOIN work_item w ON w.kind = :k AND w.subject_type = :st
                               AND w.subject_id = p.id::text
         WHERE p.name = :n AND p.status = 'rejected'
         ORDER BY p.version
    """), {"n": name, "k": POLICY_KIND, "st": POLICY_SUBJECT}).mappings()]


def propose(conn: Connection, rule: Any, *, entity_id: Optional[str] = None,
            clinic_id: Optional[str] = None, evidence: Optional[Mapping[str, Any]] = None
            ) -> Dict[str, Any]:
    """Propose one rule as work, unless rejection memory or an identical
    proposal says not to. Returns {"proposed": {...}} or {"skipped": {...}}."""
    from .roles import load_actor
    from .transitions import create_item, transition

    candidate = validate_rule(rule)
    name = candidate.name
    versions = conn.execute(text("""
        SELECT id, version, status, rule FROM policy WHERE name = :n ORDER BY version
    """), {"n": name}).mappings().all()
    for v in versions:
        if v["status"] in ("proposed", "approved"):
            same = validate_rule(v["rule"]).fingerprint == candidate.fingerprint
            return {"skipped": {"name": name, "policy_id": v["id"], "version": v["version"],
                                "reason": "%s as policy %d v%d%s" % (
                                    "already " + v["status"], v["id"], v["version"],
                                    "" if same else " (a different rule; decide on it first)")}}
    rejected = _rejections(conn, name)
    if rejected:
        seen = set()
        for r in rejected:
            seen.update((r["rule"] or {}).get("evidence_ids") or ())
        fresh = sorted(set(candidate.evidence_ids) - seen)
        if not fresh:
            last = rejected[-1]
            return {"skipped": {
                "name": name, "policy_id": last["id"], "version": last["version"],
                "reason": "rejected as policy %d v%d by %s on %s: %s; no new evidence since" % (
                    last["id"], last["version"], last["rejected_by"] or "?",
                    last["rejected_at"].date().isoformat() if last["rejected_at"] else "?",
                    last["reason"] or "no reason given"),
                "rejected": {"policy_id": last["id"], "reason": last["reason"],
                             "by": last["rejected_by"]}}}
    version = (versions[-1]["version"] + 1) if versions else 1
    candidate = candidate.model_copy(update={"version": version})
    rule_json = candidate.to_json()

    policy_id = conn.execute(text("""
        INSERT INTO policy (name, version, rule, effective_from, effective_to)
        VALUES (:n, :v, CAST(:r AS jsonb), :f, :t) RETURNING id
    """), {"n": name, "v": version, "r": _dumps(rule_json),
           "f": candidate.effective_from, "t": candidate.effective_to}).scalar_one()

    result = backtest(conn, candidate, policy_id=policy_id)
    ev = dict(evidence or {})
    ev.update({"policy_id": policy_id, "version": version, "rule": rule_json,
               "fingerprint": candidate.fingerprint, "backtest": result})
    if rejected:
        ev["after_rejection"] = [{"policy_id": r["id"], "version": r["version"],
                                  "reason": r["reason"], "by": r["rejected_by"]} for r in rejected]
    precedents = (ev.get("precedents") or {}).get("count")
    reason = "%s%s Backtest: %d past charges matched, %d decisions would change ($%s)%s." % (
        candidate.description,
        "" if precedents is None else " %d precedents." % precedents,
        result["matched"], result["changed"], "{:,.2f}".format(result["dollars"]),
        ", %d conflicts" % len(result["conflicts"]) if result["conflicts"] else "")

    actor = load_actor(conn, POLICY_AGENT)
    item = create_item(conn, actor, kind=POLICY_KIND, subject_type=POLICY_SUBJECT,
                       subject_id=policy_id, entity_id=entity_id, clinic_id=clinic_id,
                       title="Policy v%d: %s" % (version, _short(candidate.description)),
                       amount=result["dollars"],
                       period=candidate.effective_from.replace(day=1)
                       if candidate.effective_from else None)
    transition(conn, actor, item["id"], "propose", reason=reason,
               patch={"proposal": "approve", "reason": reason, "evidence": ev})
    return {"proposed": {"name": name, "policy_id": policy_id, "version": version,
                         "item_id": item["id"], "precedents": precedents,
                         "backtest": {k: result[k] for k in ("matched", "changed", "dollars")}}}


def refresh_backtest(conn: Connection, policy_id: int) -> Dict[str, Any]:
    """Re-run a proposed policy's backtest and, if it changed, put the new one
    on its POLICY item (a revised proposal by agent:policy)."""
    from .policies import load_policy
    from .roles import load_actor
    from .transitions import transition

    policy = load_policy(conn, policy_id)
    if policy is None:
        raise LearnerError("no policy %s" % policy_id)
    result = backtest(conn, policy.rule, policy_id=policy.id)
    item = conn.execute(text("""
        SELECT id, state, evidence, reason FROM work_item
         WHERE kind = :k AND subject_type = :st AND subject_id = :sid
    """), {"k": POLICY_KIND, "st": POLICY_SUBJECT, "sid": str(policy_id)}).mappings().first()
    stored = ((item or {}).get("evidence") or {}).get("backtest") or {}
    if item is None or item["state"] != "PROPOSED" or stored.get("digest") == result["digest"]:
        return {"policy_id": policy_id, "stored": False, "backtest": result}
    ev = dict(item["evidence"])
    ev["backtest"] = result
    transition(conn, load_actor(conn, POLICY_AGENT), item["id"], "propose",
               reason="Backtest re-run: %d matched, %d would change ($%s)." % (
                   result["matched"], result["changed"], "{:,.2f}".format(result["dollars"])),
               patch={"evidence": ev, "amount": result["dollars"]})
    return {"policy_id": policy_id, "stored": True, "backtest": result}


# ------------------------------------------------------------- onboarding

def onboard(conn: Connection, entity_id: str, *, year: int = YEAR) -> Dict[str, Any]:
    """Scan one entity's `year` and propose the habits it shows as policies."""
    from ..engine.charges import expected
    from ..jobs.lease_versions import confirmed_rules

    rows = conn.execute(text("""
        SELECT c.id, r.source_id, c.lease_id, c.clinic_id, l.landlord_id, d.name AS landlord,
               c.period, c.charge_type, c.amount, c.invoice_id
          FROM landlord_charge c
          JOIN raw_row r ON r.id = c.raw_ref
          JOIN lease l ON l.id = c.lease_id
          JOIN landlord d ON d.id = l.landlord_id
          JOIN clinic k ON k.id = c.clinic_id
         WHERE k.entity_id = :e AND c.period >= :a AND c.period < :b
         ORDER BY c.period, r.source_id
    """), {"e": entity_id, "a": date(year, 1, 1), "b": date(year + 1, 1, 1)}).mappings().all()
    payments = conn.execute(text("""
        SELECT p.id, p.lease_id, p.invoice_id, p.period, p.charge_type, p.amount
          FROM payment p JOIN clinic k ON k.id = p.clinic_id
         WHERE k.entity_id = :e AND p.period >= :a AND p.period < :b ORDER BY p.id
    """), {"e": entity_id, "a": date(year - 1, 12, 1), "b": date(year + 1, 1, 1)}).all()
    if not rows:
        return {"entity_id": entity_id, "year": year, "scanned": 0, "proposed": [],
                "skipped": [{"name": None, "reason": "no %d charges on record for %s"
                             % (year, entity_id)}], "paid_anyway": []}

    paid_by_line: Dict[Tuple, List] = defaultdict(list)
    paid_by_month: Dict[Tuple, Decimal] = defaultdict(lambda: Decimal("0"))
    for p in payments:
        paid_by_line[(p.invoice_id, p.charge_type, p.lease_id)].append(p)
        paid_by_month[(p.lease_id, p.charge_type, p.period)] += p.amount
    lines: Dict[Tuple, int] = defaultdict(int)
    for r in rows:
        lines[(r["invoice_id"], r["charge_type"], r["lease_id"])] += 1
    rules = confirmed_rules(conn, entity_id).rules

    decisions = []
    for r in rows:
        key = (r["invoice_id"], r["charge_type"], r["lease_id"])
        pays = paid_by_line.get(key, [])
        if lines[key] > 1:          # two lines of one type on one invoice: match by amount
            pays = [p for p in pays if abs(p.amount - r["amount"]) < CENT][:1]
        paid = sum((p.amount for p in pays), Decimal("0"))
        period = r["period"]
        prev = date(period.year - (period.month == 1), (period.month - 2) % 12 + 1, 1)
        prior = paid_by_month.get((r["lease_id"], r["charge_type"], prev))
        rule = rules.get(r["lease_id"])
        supported = None
        if rule is not None:
            supported = Decimal(str(round(expected(rule, period).for_type(r["charge_type"]), 2)))
        decisions.append({
            "charge_id": r["id"], "charge_ref": r["source_id"], "lease_id": r["lease_id"],
            "landlord_id": r["landlord_id"], "landlord": r["landlord"],
            "period": period.isoformat(), "charge_type": r["charge_type"],
            "amount": float(r["amount"]), "paid": float(paid),
            "payment_ids": [str(p.id) for p in pays],
            "paid_in_full": paid >= r["amount"] - CENT / 2,
            "same_as_prior": prior is not None and abs(r["amount"] - prior) < CENT,
            "changed": prior is not None and abs(r["amount"] - prior) >= CENT,
            "supported": None if supported is None else float(supported),
            "over_lease": supported is not None and r["amount"] - supported > TOLERANCE,
        })

    paid_anyway = [_brief(d) for d in decisions if d["paid_in_full"] and d["over_lease"]]
    out: Dict[str, Any] = {"entity_id": entity_id, "year": year, "scanned": len(decisions),
                           "leases_confirmed": sorted(rules), "proposed": [], "skipped": [],
                           "paid_anyway": paid_anyway}
    if not rules:
        out["skipped"].append({"name": None, "reason": (
            "no confirmed leases for %s: mistakes paid anyway cannot be told from habits, and "
            "the changed-amount habit cannot be checked against the lease" % entity_id)})

    groups: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for d in decisions:
        groups[(d["landlord_id"], d["charge_type"])].append(d)
    for (landlord_id, charge_type), group in sorted(groups.items()):
        candidate = _unchanged_candidate(entity_id, landlord_id, charge_type, group, year)
        _offer(conn, out, entity_id, candidate)

    changed: Dict[str, List[Dict]] = defaultdict(list)
    for d in decisions:
        if rules and d["changed"] and d["supported"] is not None and d["paid_in_full"]:
            changed[d["charge_type"]].append(d)
    for charge_type, group in sorted(changed.items()):
        _offer(conn, out, entity_id, _changed_candidate(entity_id, charge_type, group, year))
    return out


def _offer(conn, out, entity_id, candidate) -> None:
    if candidate is None:
        return
    if "skip" in candidate:
        out["skipped"].append(candidate["skip"])
        return
    result = propose(conn, candidate["rule"], entity_id=entity_id, evidence=candidate["evidence"])
    if "proposed" in result:
        out["proposed"].append(result["proposed"])
    else:
        out["skipped"].append(result["skipped"])


def _unchanged_candidate(entity_id: str, landlord_id: str, charge_type: str,
                         group: List[Dict], year: int) -> Optional[Dict]:
    precedents = [d for d in group if d["same_as_prior"] and d["paid_in_full"]]
    counter = [d for d in group if d["same_as_prior"] and not d["paid_in_full"]]
    name = "onboarding:%s:%s:unchanged" % (landlord_id, charge_type)
    if counter:
        return {"skip": {"name": name, "reason": "%d charges billed at last month's amount were "
                         "not paid in full: no consistent habit" % len(counter)}}
    if len(precedents) < MIN_PRECEDENTS:
        return {"skip": {"name": name, "reason": "%d precedents; %d needed"
                         % (len(precedents), MIN_PRECEDENTS)}}
    leases = sorted({d["lease_id"] for d in precedents})
    landlord = group[0]["landlord"]
    covered_mistakes = [d for d in precedents if d["over_lease"]]
    scope = {"landlord_id": landlord_id, "entity_id": entity_id} if len(leases) > 1 \
        else {"lease_id": leases[0]}
    when: Dict[str, Any] = {"charge_types": [charge_type], "same_as_prior_paid": True}
    if covered_mistakes:
        when["matches_lease"] = True
    label = LABEL.get(charge_type, charge_type)
    description = ("Pay %s from %s as billed when it equals what was paid the month before%s "
                   "(%d: %d such charges across %s, all paid in full)." % (
                       label, landlord, " and matches the lease" if covered_mistakes else "",
                       year, len(precedents), ", ".join(leases)))
    rule = {
        "name": name, "description": description, "origin": "onboarding",
        "scope": scope, "when": when, "then": {"action": "approve"},
        "effective_from": date(year + 1, 1, 1).isoformat(),
        "evidence_ids": ["landlord_charge:%s" % d["charge_id"] for d in precedents]
        + ["payment:%s" % p for d in precedents for p in d["payment_ids"]],
    }
    mistakes = [_brief(d) for d in group if d["paid_in_full"] and d["over_lease"]]
    return {"rule": rule, "evidence": {
        "origin": "onboarding", "learned_from": "%d history" % year,
        "precedents": {"count": len(precedents), "leases": leases,
                       "decisions": [_brief(d) for d in precedents]},
        "counter_examples": [],
        "paid_anyway": mistakes,
        "not_covered": ("the %d charges paid over the lease were billed at a changed amount, "
                        "so this rule would not have paid them" % len(mistakes))
        if mistakes and not covered_mistakes else None,
    }}


def _changed_candidate(entity_id: str, charge_type: str, group: List[Dict],
                       year: int) -> Optional[Dict]:
    precedents = [d for d in group if not d["over_lease"]]
    counter = [d for d in group if d["over_lease"]]
    name = "onboarding:%s:%s:changed-matches-lease" % (entity_id, charge_type)
    if len(precedents) < MIN_PRECEDENTS:
        return {"skip": {"name": name, "reason": (
            "%d changed-amount %s charges matched the lease and were paid (%d paid over it); "
            "%d needed" % (len(precedents), LABEL.get(charge_type, charge_type), len(counter),
                           MIN_PRECEDENTS))}}
    rule = {
        "name": name, "origin": "onboarding",
        "description": "Pay a changed %s as billed when it matches the confirmed lease "
                       "(%d: %d precedents)." % (LABEL.get(charge_type, charge_type), year,
                                                 len(precedents)),
        "scope": {"entity_id": entity_id},
        "when": {"charge_types": [charge_type], "same_as_prior_paid": False,
                 "matches_lease": True},
        "then": {"action": "approve"},
        "effective_from": date(year + 1, 1, 1).isoformat(),
        "evidence_ids": ["landlord_charge:%s" % d["charge_id"] for d in precedents],
    }
    return {"rule": rule, "evidence": {
        "origin": "onboarding", "learned_from": "%d history" % year,
        "precedents": {"count": len(precedents), "decisions": [_brief(d) for d in precedents]},
        "counter_examples": [_brief(d) for d in counter]}}


def _brief(d: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: d[k] for k in ("charge_id", "charge_ref", "lease_id", "period", "charge_type",
                              "amount", "paid", "payment_ids", "supported")}


# ---------------------------------------------------------- from answers

def learn_from_answer(conn: Connection, question_id: int) -> Dict[str, Any]:
    """Propose a policy from one answered question on a charge check."""
    q = conn.execute(text("""
        SELECT q.id, q.body, q.answer, q.answered_by, q.answered_at, q.work_item_id,
               w.kind, w.entity_id, w.clinic_id, w.period, w.proposal, w.evidence,
               c.id AS charge_id, c.lease_id, c.charge_type, c.amount, c.document_id
          FROM question q
          JOIN work_item w ON w.id = q.work_item_id
          LEFT JOIN landlord_charge c ON w.subject_type = 'landlord_charge' AND c.id = w.subject_id
         WHERE q.id = :q
    """), {"q": question_id}).mappings().first()
    if q is None:
        raise LearnerError("no question %s" % question_id)
    base = {"question_id": question_id, "work_item_id": q["work_item_id"]}
    if q["answer"] is None:
        return dict(base, skipped="question %s is not answered yet" % question_id)
    if q["kind"] != "CHARGE_CHECK" or q["charge_id"] is None:
        return dict(base, skipped="question %s is on a %s item; only charge checks teach policies"
                    % (question_id, q["kind"]))
    action = verdict(q["answer"])
    if action is None:
        return dict(base, skipped="the answer says neither pay nor dispute; nothing to generalise")

    ev = dict(q["evidence"] or {})
    rule_name = ev.get("rule")
    billed = Decimal(str(q["amount"])).quantize(CENT)
    label = LABEL.get(q["charge_type"], q["charge_type"])
    period: date = q["period"]
    when: Dict[str, Any] = {"charge_types": [q["charge_type"]]}
    if rule_name:
        when["checker_rules"] = [rule_name]
    if action == "approve":
        when["max_amount"] = str(billed)
        description = ("Pay %s's %s as billed up to $%s from %s on: %s answered \"%s\"." % (
            q["lease_id"], label, "{:,.2f}".format(billed), period.strftime("%B %Y"),
            q["answered_by"], _short(q["answer"], 160)))
    else:
        when["min_variance"] = "0.01"
        description = ("Dispute %s's %s whenever it is billed above what the lease supports, "
                       "from %s on: %s answered \"%s\"." % (
                           q["lease_id"], label, period.strftime("%B %Y"), q["answered_by"],
                           _short(q["answer"], 160)))
    evidence_ids = ["question:%d" % q["id"], "work_item:%d" % q["work_item_id"],
                    "landlord_charge:%s" % q["charge_id"]]
    if q["document_id"]:
        evidence_ids.append("document:%s" % q["document_id"])
    if ev.get("lease_version_id"):
        evidence_ids.append("lease_version:%s" % ev["lease_version_id"])
    rule = {
        "name": "answer:%s:%s:%s" % (q["lease_id"], q["charge_type"], action),
        "description": description, "origin": "answer",
        "scope": {"lease_id": q["lease_id"]}, "when": when, "then": {"action": action},
        "effective_from": period.isoformat(), "evidence_ids": evidence_ids,
    }
    result = propose(conn, rule, entity_id=q["entity_id"], clinic_id=q["clinic_id"], evidence={
        "origin": "answer",
        "question": {"id": q["id"], "body": q["body"], "answer": q["answer"],
                     "answered_by": q["answered_by"],
                     "answered_at": q["answered_at"].isoformat() if q["answered_at"] else None},
        "work_item_id": q["work_item_id"], "charge_id": q["charge_id"],
        "document_id": q["document_id"], "lease_version_id": ev.get("lease_version_id"),
        "generalised_to": "lease %s, %s, checker rule %s, from %s%s" % (
            q["lease_id"], label, rule_name or "any amount rule", period.isoformat(),
            ", up to $%s" % billed if action == "approve" else ", billed above the lease"),
        "precedents": {"count": 1, "decisions": [{"work_item_id": q["work_item_id"],
                                                  "charge_id": q["charge_id"],
                                                  "answer": q["answer"]}]},
    })
    return dict(base, verdict=action, **result)


def learn_from_answers(conn: Connection, entity_id: str, period: date) -> List[Dict[str, Any]]:
    """Every answered question on the period's charge checks. Safe to repeat:
    an identical proposal or a rejected one without new evidence is skipped."""
    ids = conn.execute(text("""
        SELECT q.id FROM question q JOIN work_item w ON w.id = q.work_item_id
         WHERE w.kind = 'CHARGE_CHECK' AND w.entity_id = :e AND w.period = :p
           AND q.answer IS NOT NULL ORDER BY q.id
    """), {"e": entity_id, "p": period}).scalars().all()
    return [learn_from_answer(conn, i) for i in ids]


# ------------------------------------------------------------------ util

def _short(s: str, n: int = 90) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _dumps(value: Any) -> str:
    import json
    return json.dumps(value, sort_keys=True, default=str)


def main(argv=None) -> int:
    from ..db.engine import engine

    parser = argparse.ArgumentParser(description="Propose policies (as agent:policy)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--onboard", metavar="ENTITY")
    group.add_argument("--answer", metavar="QUESTION_ID", type=int)
    parser.add_argument("--year", type=int, default=YEAR)
    args = parser.parse_args(argv)
    with engine("lease_agent").begin() as conn:
        if args.onboard:
            out = onboard(conn, args.onboard, year=args.year)
            for p in out["proposed"]:
                print("  proposed policy %(policy_id)d v%(version)d  %(name)s  "
                      "(%(precedents)s precedents, item #%(item_id)d)" % p)
            for s in out["skipped"]:
                print("  skipped %s: %s" % (s.get("name") or "-", s["reason"]))
        else:
            print(learn_from_answer(conn, args.answer))
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["PolicyRule", "learn_from_answer", "learn_from_answers", "onboard", "propose",
           "refresh_backtest", "verdict"]
