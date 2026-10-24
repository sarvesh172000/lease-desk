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

Two id systems meet here. The checker names a charge the way the generator
does, `<invoice>-L<n>`; the database names it `md5(source | source_id)` of the
raw AP row. The bridge is the raw row: `landlord_charge.raw_ref -> raw_row.id`,
and `raw_row.source_id` is `<invoice>-L<n>`. Charges are loaded with that
source id as their `charge_id`, and findings are mapped back through it.

Work items are written through the work layer (`app.work.transitions`), never
by hand, so every item starts with a hash-chained event. Until that module
exists, `record_findings()` refuses loudly rather than inventing a second
way to create work.
"""

import argparse
import importlib
import re
import sys
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

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
    return ids


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


def lease_rules():
    """Confirmed lease rules. Until abstraction (A3) is wired into the run,
    they are built from the generator's terms, as the eval does."""
    from datagen.company import build_company
    from datagen.leases import build_leases

    from ..engine.from_datagen import rules_from_terms

    company = build_company()
    return rules_from_terms(build_leases(company), company)


def check_period(conn: Connection, entity_id: str, period: Any) -> Dict[str, int]:
    """Load the period's charges, run the checker, and record every finding."""
    from ..agents.checker import check_month

    month = parse_period(period)
    charges = load_charges(conn, entity_id, month)
    findings = check_month(charges, lease_rules(), month)
    counts = record_findings(conn, findings, month)
    counts.update(charges=len(charges), findings=len(findings),
                  holds=sum(1 for f in findings if f.is_hold))
    return counts


# ------------------------------------------------------ findings -> work

def record_findings(conn: Connection, findings: Iterable, period: Any) -> Dict[str, int]:
    """Turn each checker finding into a proposed CHARGE_CHECK work item.

    Goes through `app.work.transitions`: `create_item` then `transition(...,
    'propose', patch=...)`, as `agent:checker`. A charge that already has an
    item is skipped, so this is safe to repeat. Returns created/skipped counts.
    """
    findings = list(findings)
    month = parse_period(period)
    transitions = _transitions()
    if not findings:
        return {"created": 0, "skipped": 0}

    actor = _load_actor(conn, transitions, CHECKER)
    ids = charge_ids_by_source_id(conn, [f.charge.charge_id for f in findings]
                                  + [r for f in findings for r in f.related])
    unknown = sorted({f.charge.charge_id for f in findings} - set(ids))
    if unknown:
        raise MonthlyRunError("findings name charges with no landlord_charge row: %s"
                              % ", ".join(unknown))
    existing = _existing_items(conn, [ids[f.charge.charge_id] for f in findings])
    scope = _clinic_scope(conn, {f.charge.clinic_id for f in findings})

    created = skipped = 0
    for f in findings:
        charge_id = ids[f.charge.charge_id]
        if charge_id in existing:
            skipped += 1
            continue
        clinic = scope.get(f.charge.clinic_id, {})
        item = transitions.create_item(
            conn, actor, kind=ITEM_KIND, subject_type=SUBJECT, subject_id=charge_id,
            entity_id=clinic.get("entity_id"), region_id=clinic.get("region_id"),
            clinic_id=f.charge.clinic_id, period=month, title=_title(f),
            amount=round(f.billed, 2))
        item_id = getattr(item, "id", item)
        transitions.transition(conn, actor, item_id, "propose", patch={
            "proposal": f.proposal, "reason": f.reason, "evidence": evidence(f, ids)})
        existing.add(charge_id)
        created += 1
    return {"created": created, "skipped": skipped}


def evidence(finding, ids: Mapping[str, str]) -> Dict[str, Any]:
    """What a person needs to judge the proposal, as plain JSON."""
    proof = finding.proof
    return {
        "rule": finding.rule,
        "charge_ref": finding.charge.charge_id,
        "invoice_id": finding.charge.invoice_id,
        "billed": round(finding.billed, 2),
        "supported": round(finding.supported, 2),
        "variance": finding.variance,
        "proof": None if proof is None else {
            "section": proof.section, "quote": proof.quote, "page": proof.page,
            "box": list(proof.box) if proof.box else None},
        "related": [ids.get(r, r) for r in finding.related],
    }


def _title(finding) -> str:
    if finding.is_hold:
        return finding.describe()
    c = finding.charge
    return "%s %s %s: $%s matches the lease" % (
        c.clinic_id, c.period.strftime("%b %Y"), c.charge_type, "{:,.2f}".format(finding.billed))


def _transitions():
    try:
        return importlib.import_module("app.work.transitions")
    except ImportError as exc:
        if getattr(exc, "name", None) not in ("app.work.transitions", "app.work"):
            raise
        raise NotImplementedError(
            "record_findings needs app.work.transitions (create_item, transition), "
            "which is not in this checkout yet; it lands with the work layer (A6)") from exc


def _load_actor(conn: Connection, transitions, actor_id: str):
    """The work layer's actor for `actor_id`. Looked for on transitions first,
    then on app.work.can, wherever the work layer chose to put `load_actor`."""
    loader = getattr(transitions, "load_actor", None)
    if loader is None:
        try:
            loader = getattr(importlib.import_module("app.work.can"), "load_actor", None)
        except ImportError:
            loader = None
    if loader is None:
        raise NotImplementedError("record_findings needs load_actor(conn, actor_id) in "
                                  "app.work.transitions or app.work.can")
    return loader(conn, actor_id)


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
