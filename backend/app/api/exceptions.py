"""GET /api/exceptions and GET /api/exceptions/{id}.

An exception is a CHARGE_CHECK work item whose proposal is `hold`: the checker
compared a landlord charge with what the lease supports and they disagreed.
Its numbers come from `work_item.evidence`, which the checker writes:

    {"lease_id": "LEASE-01", "charge_id": "<landlord_charge.id>",
     "charge_ids": [...], "charge_type": "cam_estimate",
     "billed": 6458.33, "supported": 5941.67, "confidence": 0.94,
     "investigation": {"root_cause": ..., "confidence": ..., "evidence": [...],
                       "liability_before": ..., "entries": [...], ...}}

Anything evidence does not carry falls back to the landlord charge the item is
about (`subject_type = 'landlord_charge'`, or `evidence.charge_id`), and
otherwise is null. Nothing is computed here that the checker or the engine did
not already decide; `delta` is billed minus supported, as in the fixture.

Work state -> the four statuses the UI knows (DESIGN.md §16):

    NEW         exception        variance found, nobody has proposed anything yet
    PROPOSED    pending_review   the agent proposed the hold; a person signs off
    NEEDS_INFO  escalated        a question is out to a person
    HELD        escalated        parked on someone outside the system
    APPROVED    balanced         a person signed off; only posting is left
    POSTED, CLOSED, REJECTED     balanced, and no longer listed as open
"""

import math
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ..auth.deps import SessionActor, current_actor
from .deps import get_engine, get_gateway_engine
from .items import perform
from .schemas import ApproveResult, Entry, Evidence, ExceptionDetail, ExceptionSummary, Investigation

router = APIRouter(prefix="/api", tags=["exceptions"], dependencies=[Depends(current_actor)])

STATUS_BY_STATE = {
    "NEW": "exception",
    "PROPOSED": "pending_review",
    "NEEDS_INFO": "escalated",
    "HELD": "escalated",
    "APPROVED": "balanced",
    "POSTED": "balanced",
    "CLOSED": "balanced",
    "REJECTED": "balanced",
}
CLOSED_STATES = ("POSTED", "CLOSED", "REJECTED")

_ID = re.compile(r"^exc_([1-9][0-9]{0,17})$")

_SELECT = """
    SELECT w.id, w.state, w.clinic_id, w.period, w.amount, w.evidence,
           c.lease_id    AS charge_lease_id,
           c.clinic_id   AS charge_clinic_id,
           c.charge_type AS charge_type,
           c.amount      AS charge_amount,
           c.period      AS charge_period
      FROM work_item w
      LEFT JOIN landlord_charge c
        ON c.id = COALESCE(CASE WHEN w.subject_type = 'landlord_charge' THEN w.subject_id END,
                           w.evidence ->> 'charge_id')
     WHERE w.kind = 'CHARGE_CHECK' AND w.proposal = 'hold'
"""


def exception_id(work_item_id: int) -> str:
    return "exc_%d" % work_item_id


def open_exceptions(conn: Connection) -> List[Dict[str, Any]]:
    """Every open exception, flattened to what the list and the portfolio need."""
    rows = conn.execute(text(_SELECT + """
           AND w.state <> ALL(:closed)
         ORDER BY w.period NULLS LAST, w.id
    """), {"closed": list(CLOSED_STATES)}).mappings().all()
    return [_flatten(r) for r in rows]


@router.get("/exceptions", response_model=List[ExceptionSummary])
def list_exceptions(eng: Engine = Depends(get_engine)) -> List[ExceptionSummary]:
    with eng.connect() as conn:
        return [ExceptionSummary(**{k: e[k] for k in ExceptionSummary.model_fields})
                for e in open_exceptions(conn)]


@router.get("/exceptions/{exc_id}", response_model=ExceptionDetail)
def get_exception(exc_id: str, eng: Engine = Depends(get_engine)) -> ExceptionDetail:
    match = _ID.match(exc_id)
    if match is None:
        raise HTTPException(404, "no exception %r" % exc_id)
    with eng.connect() as conn:
        row = conn.execute(text(_SELECT + " AND w.id = :id"),
                           {"id": int(match.group(1))}).mappings().first()
    if row is None:
        raise HTTPException(404, "no exception %r" % exc_id)
    flat = _flatten(row)
    return ExceptionDetail(
        **{k: flat[k] for k in ("exception_id", "lease_id", "period", "expected",
                                "actual", "delta", "status")},
        investigation=_investigation(flat["evidence"].get("investigation")),
    )


class ApproveBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=4000)


@router.post("/exceptions/{exc_id}/approve", response_model=ApproveResult)
def approve_exception(exc_id: str, body: Optional[ApproveBody] = None,
                      actor: SessionActor = Depends(current_actor),
                      eng: Engine = Depends(get_engine),
                      gateway_engine: Engine = Depends(get_gateway_engine)) -> ApproveResult:
    """§16 #4, sign-off: the same approve as POST /api/items/{id}/actions/approve
    (transition() as the session actor, then the gateway post), answered in
    the four statuses the exception screen knows. 403 refused (and on record),
    409 not awaiting review, 404 not an exception."""
    match = _ID.match(exc_id)
    if match is None:
        raise HTTPException(404, "no exception %r" % exc_id)
    item_id = int(match.group(1))
    with eng.connect() as conn:
        if conn.execute(text(_SELECT + " AND w.id = :id"), {"id": item_id}).first() is None:
            raise HTTPException(404, "no exception %r" % exc_id)
    result = perform(eng, gateway_engine, actor, item_id, "approve",
                     reason=(body or ApproveBody()).reason)
    return ApproveResult(status=STATUS_BY_STATE[result.state])


# --- shaping ---------------------------------------------------------------------

def _flatten(row) -> Dict[str, Any]:
    ev = row["evidence"] if isinstance(row["evidence"], dict) else {}
    actual = _money(ev.get("billed"))
    if actual is None:
        actual = _money(row["charge_amount"]) if row["charge_amount"] is not None \
            else _money(row["amount"])
    expected = _money(ev.get("supported"))
    inv = ev.get("investigation") if isinstance(ev.get("investigation"), dict) else {}
    confidence = _number(ev.get("confidence"))
    if confidence is None:
        confidence = _number(inv.get("confidence"))
    return {
        "exception_id": exception_id(row["id"]),
        "lease_id": _str(ev.get("lease_id")) or row["charge_lease_id"],
        "clinic_id": row["clinic_id"] or row["charge_clinic_id"],
        "period": row["period"] or row["charge_period"],
        "charge_type": _str(ev.get("charge_type")) or row["charge_type"],
        "expected": expected,
        "actual": actual,
        "delta": round(actual - expected, 2) if actual is not None and expected is not None else None,
        "status": STATUS_BY_STATE[row["state"]],
        "confidence": confidence,
        "evidence": ev,
    }


def _investigation(raw: Optional[dict]) -> Investigation:
    """The investigation exactly as recorded, nulls where nothing was."""
    if not isinstance(raw, dict):
        return Investigation()
    evidence = [_lenient(Evidence, e) for e in _list(raw.get("evidence")) if isinstance(e, dict)]
    entries = [Entry(account=str(e.get("account") or ""), debit=_money(e.get("debit")) or 0.0,
                     credit=_money(e.get("credit")) or 0.0)
               for e in _list(raw.get("entries")) if isinstance(e, dict)]
    balanced = _bool(raw.get("balanced"))
    if balanced is None and entries:
        # Not a new number: the same debits-equal-credits test the engine asserts.
        balanced = abs(sum(e.debit for e in entries) - sum(e.credit for e in entries)) < 0.005
    return Investigation(
        root_cause=_str(raw.get("root_cause")),
        confidence=_number(raw.get("confidence")),
        explains_variance=_bool(raw.get("explains_variance")),
        evidence=evidence,
        liability_before=_money(raw.get("liability_before")),
        liability_after=_money(raw.get("liability_after")),
        rou_before=_money(raw.get("rou_before")),
        rou_after=_money(raw.get("rou_after")),
        entries=entries,
        balanced=balanced,
    )


def _number(value) -> Optional[float]:
    """A finite float from whatever evidence holds, else None. Evidence is
    written by agents, so a string or a NaN there must not become a 500."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _money(value) -> Optional[float]:
    number = _number(value)
    return None if number is None else round(number, 2)


def _str(value) -> Optional[str]:
    return value if isinstance(value, str) else None


def _bool(value) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _lenient(model, data: dict):
    """Build `model` from agent-written JSON, nulling any field that does not
    fit rather than failing the whole screen over one bad value."""
    values = {k: data.get(k) for k in model.model_fields}
    try:
        return model(**values)
    except ValidationError as exc:
        for error in exc.errors():
            values[error["loc"][0]] = None
        return model(**values)
