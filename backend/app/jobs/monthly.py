"""The monthly run: one entity, one period, three jobs in order.

    python -m app.jobs.monthly --period 2026-01 [--entity ENT-CA]
    make run-month M=2026-01        # the above, then the worker with --once

`run_month()` enqueues ingest -> abstraction -> checking, each depending on
the one before, each under the idempotency key
`run_month:<entity>:<YYYY-MM>:<step>`. Running a month twice therefore finds
all three keys taken and enqueues nothing; the checking job that already ran
is `done` and never runs again. `record_findings()` is idempotent on its own
too (a charge that already has a CHARGE_CHECK item is skipped), so even a
checking job retried after a crash adds no second item.

Only confirmed leases are checked (PHASE_1.md group 9). The checker's rules
come from the *confirmed* lease_version 1 terms (`lease_versions.confirmed_rules`),
never from the generator. A charge whose lease has no confirmed version is
not checked at all: no item is proposed against unconfirmed terms. It waits,
and the checking job's result says so (`waiting`, `waiting_leases` with the
reason per lease, and `confirmed`, the set of confirmed version ids it ran
with). Once a regional manager confirms more leases, the next `run_month`
sees that the month's last checking job left charges waiting under a
different confirmed set and enqueues one more checking job, keyed
`run_month:<entity>:<YYYY-MM>:checking@<confirmed set>`. Same set, same key:
running the month again with nothing newly confirmed enqueues nothing.

Two id systems meet here. The checker names a charge the way the generator
does, `<invoice>-L<n>`; the database names it `md5(source | source_id)` of the
raw AP row. The bridge is the raw row: `landlord_charge.raw_ref -> raw_row.id`,
and `raw_row.source_id` is `<invoice>-L<n>`. Charges are loaded with that
source id as their `charge_id`, and findings are mapped back through it.

Policies (work/policies.py): an approved policy that covers a finding decides
it, and its `policy:<id>@v<version>` goes on the propose event's policy_ref.
When any policy is approved, `run_month` also enqueues one `policies` job per
distinct approved set (`run_month:<entity>:<YYYY-MM>:policies@<set>`), which
re-decides the month's open items under it. With none approved, neither
happens and a month runs exactly as it did before policies existed.

Work items are written through the work layer (`app.work.transitions`), never
by hand, so every item starts with a hash-chained event: `create_item` then
`transition(..., 'propose')`, as `agent:checker`, on the worker's
`lease_agent` connection.
"""

import argparse
import re
import sys
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..work.policies import PolicyBook
from ..work.roles import load_actor
from ..work.transitions import create_item, transition
from .queue import enqueue

STEPS = ("ingest", "abstraction", "checking")
CHECKER = "agent:checker"
ITEM_KIND = "CHARGE_CHECK"
SUBJECT = "landlord_charge"
AP_SOURCE = "ap_export"

_PERIOD = re.compile(r"^(\d{4})-(\d{2})(?:-01)?$")


class MonthlyRunError(ValueError):
    """A bad period or entity, or charges the database cannot account for."""


# ---------------------------------------------------------------- periods

def parse_period(value: Any) -> date:
    """`2026-01`, `2026-01-01` or a date on the 1st -> the first of the month."""
    if isinstance(value, date):
        if value.day != 1 or isinstance(value, datetime):
            raise MonthlyRunError("a period is the first of a month, got %r" % (value,))
        return value
    match = _PERIOD.match(str(value).strip()) if isinstance(value, str) else None
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise MonthlyRunError("period must look like YYYY-MM, got %r" % (value,))
    return date(int(match.group(1)), int(match.group(2)), 1)


def job_key(entity_id: str, period: date, step: str) -> str:
    return "run_month:%s:%s:%s" % (entity_id, period.strftime("%Y-%m"), step)


# --------------------------------------------------------------- enqueue

def run_month(conn: Connection, entity_id: str, period: Any) -> Dict[str, int]:
    """Enqueue the month's three jobs (or find them) and return their ids by step."""
    month = parse_period(period)
    if not conn.execute(text("SELECT 1 FROM entity WHERE id = :e"), {"e": entity_id}).first():
        raise MonthlyRunError("unknown entity %r; run `make seed` first" % (entity_id,))
    payload = {"entity_id": entity_id, "period": month.isoformat()}
    ids: Dict[str, int] = {}
    previous: Tuple[int, ...] = ()
    for step in STEPS:
        ids[step] = enqueue(conn, step, payload, idempotency_key=job_key(entity_id, month, step),
                            depends_on=previous)
        previous = (ids[step],)
    recheck = _recheck_key(conn, entity_id, month)
    if recheck is not None:
        ids["recheck"] = enqueue(conn, "checking", payload, idempotency_key=recheck,
                                 depends_on=(ids["abstraction"],))
    policies = _policies_key(conn, entity_id, month)
    if policies is not None:
        ids["policies"] = enqueue(conn, "policies", payload, idempotency_key=policies,
                                  depends_on=tuple(ids[s] for s in ("checking", "recheck")
                                                   if s in ids))
    return ids


def _policies_key(conn: Connection, entity_id: str, month: date) -> Optional[str]:
    """The key of a `policies` job (work/policies.apply_policies), when any
    policy is approved: the month's open charge checks are re-decided under
    the approved set, once per distinct set. With none approved there is no
    such job, and the month runs exactly as before policies existed."""
    from ..work.policies import approved_fingerprint

    now = approved_fingerprint(conn)
    if now == "none":
        return None
    return "%s@%s" % (job_key(entity_id, month, "policies"), now)


def _recheck_key(conn: Connection, entity_id: str, month: date) -> Optional[str]:
    """The key of one more checking job, when the month's latest checking job
    finished with charges waiting on leases and the set of confirmed versions
    has changed since. None otherwise (including while a check is pending)."""
    from .lease_versions import confirmed_rules

    last = conn.execute(text("""
        SELECT status, payload->'result' AS result FROM job
         WHERE kind = 'checking' AND payload->>'entity_id' = :e AND payload->>'period' = :p
         ORDER BY id DESC LIMIT 1
    """), {"e": entity_id, "p": month.isoformat()}).first()
    if last is None or last.status != "done" or not last.result:
        return None
    if not last.result.get("waiting"):
        return None
    now = confirmed_rules(conn, entity_id).fingerprint
    if now == last.result.get("confirmed"):
        return None
    return "%s@%s" % (job_key(entity_id, month, "checking"), now)


# ------------------------------------------------------- loading charges

def load_charges(conn: Connection, entity_id: str, period: date) -> List:
    """The period's billed lines for one entity, as checker `Charge`s whose
    `charge_id` is the generator's `<invoice>-L<n>` (the raw row's source id)."""
    from ..agents.checker import Charge

    rows = conn.execute(text("""
        SELECT r.source_id, c.invoice_id, c.lease_id, c.clinic_id, c.period,
               c.charge_type, c.suite, c.amount, c.description
          FROM landlord_charge c
          JOIN raw_row r ON r.id = c.raw_ref
          JOIN clinic k ON k.id = c.clinic_id
         WHERE c.period = :p AND k.entity_id = :e
         ORDER BY r.source_id
    """), {"p": period, "e": entity_id}).all()
    return [Charge(charge_id=r.source_id, invoice_id=r.invoice_id, lease_id=r.lease_id,
                   clinic_id=r.clinic_id, period=r.period, charge_type=r.charge_type,
                   suite=r.suite or "", amount=float(r.amount),
                   description=r.description or "")
            for r in rows]


def charge_ids_by_source_id(conn: Connection, source_ids: Iterable[str]) -> Dict[str, str]:
    """`<invoice>-L<n>` -> landlord_charge.id, through raw_row."""
    wanted = sorted(set(source_ids))
    if not wanted:
        return {}
    rows = conn.execute(text("""
        SELECT r.source_id, c.id FROM landlord_charge c JOIN raw_row r ON r.id = c.raw_ref
         WHERE r.source = :src AND r.source_id = ANY (CAST(:ids AS text[]))
    """), {"src": AP_SOURCE, "ids": wanted}).all()
    return {r.source_id: r.id for r in rows}


def check_period(conn: Connection, entity_id: str, period: Any) -> Dict[str, Any]:
    """Load the period's charges, check those on a confirmed lease, and
    record every finding. Charges on unconfirmed leases are counted as
    waiting and left alone."""
    from ..agents.checker import check_month
    from .lease_versions import confirmed_rules

    month = parse_period(period)
    charges = load_charges(conn, entity_id, month)
    confirmed = confirmed_rules(conn, entity_id)
    ready = [c for c in charges if c.lease_id in confirmed.rules]
    waiting = [c for c in charges if c.lease_id not in confirmed.rules]
    findings = check_month(ready, confirmed.rules, month)
    counts: Dict[str, Any] = record_findings(conn, findings, month, versions=confirmed.versions)
    waiting_leases = sorted({c.lease_id for c in waiting})
    counts.update(charges=len(charges), checked=len(ready), findings=len(findings),
                  holds=sum(1 for f in findings if f.is_hold), waiting=len(waiting),
                  waiting_leases={lid: confirmed.waiting.get(lid, "no confirmed lease_version")
                                  for lid in waiting_leases},
                  confirmed=confirmed.fingerprint)
    return counts


# ------------------------------------------------------ findings -> work

def record_findings(conn: Connection, findings: Iterable, period: Any,
                    versions: Optional[Mapping[str, int]] = None) -> Dict[str, int]:
    """Turn each checker finding into a proposed CHARGE_CHECK work item.

    One item per finding, about the landlord charge it judged
    (`subject_type = 'landlord_charge'`, `subject_id` = the database id):
    `create_item` then `transition(..., 'propose')` with the checker's
    proposal (`approve` or `hold`), reason and evidence, as `agent:checker`.
    A charge that already has an item is skipped, so this is safe to repeat
    (create_item is idempotent on its own as well). Returns created/skipped
    counts. `versions` (lease_id -> confirmed lease_version id) is cited in
    each item's evidence as `lease_version_id`.
    """
    findings = list(findings)
    month = parse_period(period)
    if not findings:
        return {"created": 0, "skipped": 0}

    actor = load_actor(conn, CHECKER)
    ids = charge_ids_by_source_id(conn, [f.charge.charge_id for f in findings]
                                  + [r for f in findings for r in f.related])
    unknown = sorted({f.charge.charge_id for f in findings} - set(ids))
    if unknown:
        raise MonthlyRunError("findings name charges with no landlord_charge row: %s"
                              % ", ".join(unknown))
    existing = _existing_items(conn, [ids[f.charge.charge_id] for f in findings])
    scope = _clinic_scope(conn, {f.charge.clinic_id for f in findings})
    book = PolicyBook(conn)     # approved policies; none approved changes nothing

    created = skipped = cited = 0
    for f in findings:
        charge_id = ids[f.charge.charge_id]
        if charge_id in existing:
            skipped += 1
            continue
        clinic = scope.get(f.charge.clinic_id, {})
        item = create_item(
            conn, actor, kind=ITEM_KIND, subject_type=SUBJECT, subject_id=charge_id,
            entity_id=clinic.get("entity_id"), region_id=clinic.get("region_id"),
            clinic_id=f.charge.clinic_id, period=month, title=_title(f),
            amount=round(f.billed, 2))
        proposal, reason, ev, ref = book.decide(
            charge_id=charge_id, period=month, charge_type=f.charge.charge_type,
            amount=round(f.billed, 2), lease_id=f.charge.lease_id, clinic_id=f.charge.clinic_id,
            description=f.charge.description, supported=round(f.supported, 2),
            checker_rule=f.rule, proposal=f.proposal, reason=f.reason,
            evidence=evidence(f, ids, (versions or {}).get(f.charge.lease_id)))
        transition(conn, actor, item["id"], "propose", reason=reason, policy_ref=ref,
                   patch={"proposal": proposal, "reason": reason, "evidence": ev})
        existing.add(charge_id)
        created += 1
        cited += ref is not None
    return {"created": created, "skipped": skipped, "cited": cited}


def evidence(finding, ids: Mapping[str, str],
             lease_version_id: Optional[int] = None) -> Dict[str, Any]:
    """What a person needs to judge the proposal, as plain JSON, in the shape
    the read API documents (api/exceptions.py): lease_id, charge_id (the
    landlord_charge id), charge_ids, charge_type, billed, supported, then the
    rule and the lease clause that decided it. The checker is deterministic
    and states no confidence, so none is invented here."""
    proof = finding.proof
    charge = finding.charge
    charge_id = ids[charge.charge_id]
    related = [ids.get(r, r) for r in finding.related]
    return {
        "lease_id": charge.lease_id,
        "charge_id": charge_id,
        "charge_ids": [charge_id] + related,
        "charge_type": charge.charge_type,
        "billed": round(finding.billed, 2),
        "supported": round(finding.supported, 2),
        "variance": finding.variance,
        "rule": finding.rule,
        "proof": None if proof is None else {
            "section": proof.section, "quote": proof.quote, "page": proof.page,
            "box": list(proof.box) if proof.box else None},
        "charge_ref": charge.charge_id,
        "invoice_id": charge.invoice_id,
        "related": related,
        "lease_version_id": lease_version_id,
    }


def _title(finding) -> str:
    if finding.is_hold:
        return finding.describe()
    c = finding.charge
    return "%s %s %s: $%s matches the lease" % (
        c.clinic_id, c.period.strftime("%b %Y"), c.charge_type, "{:,.2f}".format(finding.billed))


def _existing_items(conn: Connection, charge_ids: List[str]) -> set:
    return set(conn.execute(text("""
        SELECT subject_id FROM work_item
         WHERE kind = :k AND subject_type = :t AND subject_id = ANY (CAST(:ids AS text[]))
    """), {"k": ITEM_KIND, "t": SUBJECT, "ids": charge_ids}).scalars())


def _clinic_scope(conn: Connection, clinic_ids) -> Dict[str, Dict[str, Optional[str]]]:
    rows = conn.execute(text("""
        SELECT id, entity_id, region_id FROM clinic WHERE id = ANY (CAST(:ids AS text[]))
    """), {"ids": sorted(clinic_ids)}).all()
    return {r.id: {"entity_id": r.entity_id, "region_id": r.region_id} for r in rows}


# -------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    from ..db.engine import engine

    parser = argparse.ArgumentParser(description="Enqueue one month's run")
    parser.add_argument("--period", required=True, help="YYYY-MM")
    parser.add_argument("--entity", action="append",
                        help="entity id (repeatable); default: every entity")
    args = parser.parse_args(argv)
    try:
        month = parse_period(args.period)
    except MonthlyRunError as exc:
        print("run-month: %s" % exc, file=sys.stderr)
        return 2

    with engine("lease_agent").begin() as conn:
        entities = args.entity or list(conn.execute(
            text("SELECT id FROM entity ORDER BY id")).scalars())
        if not entities:
            print("run-month: no entities; run `make seed` first", file=sys.stderr)
            return 2
        before = conn.execute(text("SELECT count(*) FROM job")).scalar_one()
        try:
            for entity_id in entities:
                ids = run_month(conn, entity_id, month)
                print("  %s %s  %s" % (entity_id, month.strftime("%Y-%m"),
                                       "  ".join("%s=#%d" % kv for kv in ids.items())))
        except MonthlyRunError as exc:
            print("run-month: %s" % exc, file=sys.stderr)
            return 2
        added = conn.execute(text("SELECT count(*) FROM job")).scalar_one() - before
    print("  %d new job(s)" % added)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
