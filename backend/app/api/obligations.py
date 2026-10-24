"""Lease obligations and critical dates over HTTP (PHASE_2.md group 12).

    GET /api/obligations?within_days=&lease_id=&kind=

Obligations due from the business date (jobs/clock.today) through
`within_days` calendar days later (default 365), soonest first, each with
its citation, its 90/60/30-business-day alert dates and the OBLIGATION work
items already opened for it. Scoped like the queue: a regional manager sees
their region's leases, an actor with an entity sees that entity's.

Response:

    {"today": "2026-10-24", "within_days": 365, "total": 3,
     "obligations": [{id, lease_id, clinic_id, region_id, entity_id, kind, key,
                      due_date, days_left, action, citation, source,
                      lease_version_id, details, alert_dates: {"90": date, ...},
                      alerts: [{id, state, title, proposal, reason, updated_at}]}]}
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from ..auth.deps import SessionActor, current_actor
from ..jobs import clock
from ..work import obligations as work
from .deps import get_engine
from .items import scope_sql

router = APIRouter(prefix="/api", tags=["obligations"])


class Alert(BaseModel):
    id: int
    state: str
    title: str
    proposal: Optional[str]
    reason: Optional[str]
    updated_at: datetime


class ObligationOut(BaseModel):
    id: int
    lease_id: str
    clinic_id: str
    region_id: Optional[str]
    entity_id: str
    kind: str
    key: str
    due_date: date
    days_left: int
    action: str
    citation: Dict[str, Any]
    source: str
    lease_version_id: Optional[int]
    details: Dict[str, Any]
    alert_dates: Dict[str, date]
    alerts: List[Alert]


class Obligations(BaseModel):
    today: date
    within_days: int
    total: int
    obligations: List[ObligationOut]


@router.get("/obligations", response_model=Obligations)
def list_obligations(
    within_days: int = Query(365, ge=0, le=3660),
    lease_id: Optional[str] = Query(None, min_length=1, max_length=200),
    kind: Optional[str] = Query(None),
    actor: SessionActor = Depends(current_actor),
    eng: Engine = Depends(get_engine),
) -> Obligations:
    if kind is not None and kind not in work.KINDS:
        raise HTTPException(422, "kind must be one of %s" % ", ".join(work.KINDS))
    where, params = scope_sql(actor, "o")
    if lease_id is not None:
        where.append("o.lease_id = :lease_id")
        params["lease_id"] = lease_id
    if kind is not None:
        where.append("o.kind = :kind")
        params["kind"] = kind
    with eng.connect() as conn:
        today = clock.today(conn)
        rows = work.due_within(conn, today, within_days, where, params)
    out = [ObligationOut(**{k: r[k] for k in ObligationOut.model_fields
                            if k not in ("days_left", "alerts", "alert_dates")},
                         days_left=(r["due_date"] - today).days, alert_dates=r["alert_dates"],
                         alerts=[Alert(**a) for a in r["alerts"]]) for r in rows]
    return Obligations(today=today, within_days=within_days, total=len(out), obligations=out)
