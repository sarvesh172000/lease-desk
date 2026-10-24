"""GET /api/leases and GET /api/leases/{id}/schedule.

Every number here comes from the ASC 842 engine in `leasedesk/` (via the
amendment path in `engine/remeasurement.py` for later versions). This module
only decides which terms to hand it and which row to read back.

Where the terms come from
-------------------------
Version 1 is the lease as signed: the engine input `datagen.build` writes to
`<data_dir>/leases/<lease_id>.json`, the same register `make seed` loads the
lease table from. (Confirmed abstractions replace this once the abstraction
agent writes `lease_term` rows; `engine/from_datagen.py` documents the same
shim.) Location and lessor come from the golden tables.

Version N > 1 is a `lease_version` row: an amendment effective from
`effective_from`, its revised terms in `lease_term` under the abstraction's
field names — `base_rent_monthly`, `expiration`, `escalation_kind`,
`escalation_amount`, and optionally `discount_rate`. A term's `value` may be
the bare JSON value or `{"value": ...}`. The engine remeasures at the
effective date, so a later version's rows start there.

As of when
----------
The portfolio is read as of the business date (`deps.get_business_date`,
2026-01-01 until the job clock exists), or `?as_of=YYYY-MM-DD`. `monthly_rent`
is the payment due that month; `liability` is the closing liability for that
month, which is how DESIGN.md §6 states the carried balance. The terms used
are the latest *confirmed* version in effect on that date.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ..auth.deps import current_actor
from .deps import get_business_date, get_data_dir, get_engine
from .exceptions import open_exceptions
from .schemas import LeaseSummary, Schedule, ScheduleRow

router = APIRouter(prefix="/api", tags=["leases"], dependencies=[Depends(current_actor)])

AMENDMENT_FIELDS = ("base_rent_monthly", "expiration", "escalation_kind",
                    "escalation_amount", "discount_rate")


class TermsError(ValueError):
    """The stored terms cannot be turned into a schedule."""


@dataclass(frozen=True)
class Version:
    number: int
    effective_from: Optional[date]    # None for v1: commencement, from the terms
    confirmed: bool
    terms: Dict[str, object]


# --- routes ------------------------------------------------------------------------

@router.get("/leases", response_model=List[LeaseSummary])
def list_leases(
    as_of: Optional[date] = Query(None, description="Read the portfolio as of this date"),
    eng: Engine = Depends(get_engine),
    data_dir: Path = Depends(get_data_dir),
    business_date: date = Depends(get_business_date),
) -> List[LeaseSummary]:
    return portfolio(eng, data_dir, as_of or business_date)


def portfolio(eng: Engine, data_dir: Path, when: date) -> List[LeaseSummary]:
    """Every lease as of `when`, its numbers from the engine. Shared with
    GET /api/summary, so the dashboard's liability is this list's sum."""
    with eng.connect() as conn:
        leases = conn.execute(text(_LEASES)).mappings().all()
        held = {e["lease_id"] for e in open_exceptions(conn) if e["status"] != "balanced"}
        versions = _versions_by_lease(conn)

    out = []
    for row in leases:
        rent = liability = end = None
        payload = register_terms(data_dir, row["id"])
        if payload is not None:
            later = versions.get(row["id"], [])
            try:
                schedule, lease = build_schedule(payload, later, active_version(later, when))
            except TermsError:
                schedule = None     # the schedule endpoint says why; here, nulls
            if schedule is not None:
                due = schedule.period_for(when)
                rent = due.payment if due is not None else 0.0
                liability = round(schedule.balances_at(when)["liability"], 2)
                end = lease.end
        out.append(LeaseSummary(
            lease_id=row["id"], clinic_id=row["clinic_id"],
            location="%s — %s" % (row["clinic_name"], row["suite"]),
            lessor=row["lessor"],
            status="exception" if row["id"] in held else "balanced",
            monthly_rent=rent, liability=liability, end=end,
        ))
    return out


@router.get("/leases/{lease_id}/schedule", response_model=Schedule)
def lease_schedule(
    lease_id: str,
    version: Optional[int] = Query(None, ge=1, le=10_000,
                                   description="1 is the lease as signed; omit for the active one"),
    eng: Engine = Depends(get_engine),
    data_dir: Path = Depends(get_data_dir),
    business_date: date = Depends(get_business_date),
) -> Schedule:
    with eng.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM lease WHERE id = :id"), {"id": lease_id}).first()
        if exists is None:
            raise HTTPException(404, "no lease %r" % lease_id)
        later = _versions_by_lease(conn, lease_id).get(lease_id, [])

    payload = register_terms(data_dir, lease_id)
    if payload is None:
        raise HTTPException(404, "no terms on file for %s" % lease_id)

    numbers = [1] + [v.number for v in later]
    active = active_version(later, business_date)
    if version is None:
        version = active
    elif version not in numbers:
        raise HTTPException(404, "%s has no version %d (it has %s)"
                            % (lease_id, version, ", ".join(map(str, numbers))))
    try:
        schedule, lease = build_schedule(payload, later, version)
    except TermsError as exc:
        raise HTTPException(422, str(exc)) from None

    chosen = next((v for v in later if v.number == version), None)
    return Schedule(
        lease_id=lease_id, version=version, versions=numbers,
        effective_from=chosen.effective_from if chosen else lease.commencement,
        confirmed=chosen.confirmed if chosen else True,
        active=version == active,
        discount_rate=lease.discount_rate,
        opening_liability=schedule.opening_liability,
        opening_rou=schedule.opening_rou,
        rows=[ScheduleRow(**vars(p)) for p in schedule.periods],
    )


# --- terms -> engine --------------------------------------------------------------

_LEASES = """
    SELECT l.id, l.clinic_id, c.name AS clinic_name, c.suite, ll.name AS lessor
      FROM lease l
      JOIN clinic c ON c.id = l.clinic_id
      JOIN landlord ll ON ll.id = l.landlord_id
     ORDER BY l.id
"""


def register_terms(data_dir: Path, lease_id: str) -> Optional[dict]:
    """The signed terms in the engine's input shape, or None if not on file.
    `lease_id` always comes from the lease table, never straight from a URL."""
    path = data_dir / "leases" / ("%s.json" % lease_id.lower())
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _versions_by_lease(conn: Connection, lease_id: Optional[str] = None) -> Dict[str, List[Version]]:
    """Versions after the first, with their terms, oldest first."""
    rows = conn.execute(text("""
        SELECT v.lease_id, v.version, v.effective_from, v.confirmed_by IS NOT NULL AS confirmed,
               t.field, t.value
          FROM lease_version v
          LEFT JOIN lease_term t ON t.lease_version_id = v.id
         WHERE v.version > 1 AND (CAST(:lease AS text) IS NULL OR v.lease_id = :lease)
         ORDER BY v.lease_id, v.version
    """), {"lease": lease_id}).mappings().all()
    grouped: Dict[str, Dict[int, Version]] = {}
    for r in rows:
        versions = grouped.setdefault(r["lease_id"], {})
        v = versions.get(r["version"]) or Version(r["version"], r["effective_from"], r["confirmed"], {})
        if r["field"] is not None:
            value = r["value"]
            v.terms[r["field"]] = value["value"] if isinstance(value, dict) and "value" in value else value
        versions[r["version"]] = v
    return {lid: sorted(vs.values(), key=lambda v: v.number) for lid, vs in grouped.items()}


def active_version(later: List[Version], when: date) -> int:
    """The latest confirmed version already in effect on `when`."""
    live = [v.number for v in later if v.confirmed and v.effective_from <= when]
    return max(live, default=1)


def build_schedule(payload: dict, later: List[Version], version: int):
    """The engine's schedule for one version, and the engine's lease for it."""
    from leasedesk.models import from_dict
    from leasedesk.remeasure import remeasure
    from leasedesk.schedule import build

    try:
        base = from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise TermsError("the lease register entry is malformed: %s" % exc) from None
    if version == 1:
        return build(base), base

    current = dict(payload, amendments=[])
    for v in later:
        if v.number > version:
            break
        current = _amend(current, v)
    lease = from_dict(current)
    effective = max(a.effective for a in lease.amendments)
    return remeasure(lease, effective=effective, through=effective).new, lease.as_of(effective)


def _amend(payload: dict, v: Version) -> dict:
    """Add version `v` to the payload as an engine amendment. The revised rent
    steps come from the same step builder `engine/remeasurement.propose` uses,
    so escalation is computed exactly as the investigation path computes it.
    (Not `propose()` itself: it leaves a temp file behind per call, which a
    read endpoint cannot afford.)"""
    from leasedesk.models import from_dict

    from ..engine.remeasurement import ProposedAmendment
    from ..engine.remeasurement import _steps as revised_steps

    t = v.terms
    try:
        amendment = ProposedAmendment(
            effective=v.effective_from,
            new_base_rent=float(t["base_rent_monthly"]) if t.get("base_rent_monthly") is not None else None,
            new_expiration=date.fromisoformat(t["expiration"]) if t.get("expiration") else None,
            escalation_kind=str(t.get("escalation_kind") or "fixed_percent"),
            escalation_amount=float(t.get("escalation_amount") or 0.0),
        )
        discount = float(t["discount_rate"]) if t.get("discount_rate") is not None else None
    except (TypeError, ValueError) as exc:
        raise TermsError("version %d has a term the engine cannot read: %s" % (v.number, exc)) from None
    if amendment.escalation_kind not in ("fixed_percent", "fixed_step"):
        raise TermsError("version %d: escalation_kind %r is neither fixed_percent nor fixed_step"
                         % (v.number, amendment.escalation_kind))

    # Flatten what came before so this amendment builds on the terms as they
    # stood the day before it takes effect.
    standing = from_dict(payload).as_of(date.max)
    if amendment.effective <= standing.commencement or amendment.effective > standing.end:
        raise TermsError("version %d takes effect %s, outside the lease term %s to %s"
                         % (v.number, amendment.effective, standing.commencement, standing.end))
    end = amendment.new_expiration or standing.end
    if end < amendment.effective:
        raise TermsError("version %d expires %s, before it takes effect %s"
                         % (v.number, end, amendment.effective))
    rent = amendment.new_base_rent
    if rent is None:
        rent = standing.rent_for(amendment.effective)
    steps = revised_steps(amendment.effective, end, rent,
                          amendment.escalation_kind, amendment.escalation_amount)
    entry = {
        "amendment_id": "%s-v%d" % (payload["lease_id"], v.number),
        "effective": amendment.effective.isoformat(),
        "source": "lease_version",
        "summary": "",
        "new_end": end.isoformat(),
        "new_steps": steps,
    }
    if discount is not None:
        entry["new_discount_rate"] = discount
    return dict(payload, amendments=list(payload.get("amendments", [])) + [entry])
