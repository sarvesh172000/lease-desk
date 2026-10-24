"""The dispute register over HTTP (PHASE_2.md group 11).

    GET  /api/disputes?status=&clinic_id=          the register, with counts per status
    GET  /api/disputes/{id}                        letter, status history, receivable, items
    POST /api/disputes/{id}/approve                {reason?}  approve the letter; the gateway sends it
    POST /api/disputes/{id}/receivable/approve     {reason?}  controller: recognise the receivable
    POST /api/disputes/{id}/reply                  record the landlord's reply

Reads are scoped like the queue (api/items.py): a regional manager sees their
region's disputes, an actor with an entity sees that entity's; a dispute
outside scope is a 404.

Approving the letter is the DISPUTE work item's ordinary approve
(transition(), so can() scopes it to the clinic's region; the queue's
/api/items/{id}/actions/approve does the same thing). After any write the
gateway runs for that dispute, on its own `lease_gateway` transaction after
the write commits (gateway.sync_disputes): it queues the approved letter as
an email, posts the approved receivable, clears credit memos and settles. If
the gateway fails the write stands and the response carries `gateway_error`;
syncing again is safe, every step is idempotent.

A reply is recorded by an AP clerk (acknowledged, queried, full credit) or a
controller (any outcome, including partial credit and refusal, which reopen
the letter to the regional manager). Anyone else gets 403, and the refusal is
an audit event. A wrong status is 409; a malformed reply 422.

Response shapes (no §16 fixture; documented here):

    DisputeSummary  id, status, landlord_id, landlord_name, lease_id, clinic_id,
                    region_id, entity_id, period, charge_type, invoice_id, billed,
                    supported, amount, credited_amount, open_receivable,
                    work_item_id, work_item_state, sent_at, updated_at
    DisputeDetail   dispute (a summary) + letter, notice_to, facts, credits,
                    refusal_reason, history[], items{letter, receivable},
                    receivable{recognized, cleared, open, entries[]}, outbox[],
                    reply_outcomes (what this actor may record), gateway_error
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ..auth.deps import SessionActor, current_actor
from ..work import disputes, gateway
from ..work.transitions import Denied, IllegalTransition, transition
from .deps import get_engine, get_gateway_engine
from .items import in_scope, scope_sql, work_actor

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["disputes"])

DisputeId = PathParam(..., min_length=1, max_length=64, pattern=r"^DSP-\d+$")

Outcome = Literal["acknowledged", "queried", "full_credit", "partial_credit", "refused"]


# --- models -----------------------------------------------------------------------

class DisputeSummary(BaseModel):
    id: str
    status: str
    landlord_id: str
    landlord_name: str
    lease_id: str
    clinic_id: str
    region_id: Optional[str]
    entity_id: str
    period: date
    charge_type: str
    invoice_id: str
    billed: float
    supported: float
    amount: float
    credited_amount: float
    open_receivable: float
    work_item_id: int
    work_item_state: str
    sent_at: Optional[datetime]
    updated_at: datetime


class DisputeList(BaseModel):
    counts: Dict[str, int]
    total: int
    disputes: List[DisputeSummary]


class HistoryEvent(BaseModel):
    seq: int
    at: datetime
    actor_id: str
    action: str
    allowed: bool
    reason: Optional[str]
    from_status: Optional[str]
    to_status: Optional[str]
    evidence: Optional[Dict[str, Any]]


class ReceivableEntry(BaseModel):
    journal_entry_id: int
    key: str
    date: date
    debit: float
    credit: float


class Receivable(BaseModel):
    recognized: float
    cleared: float
    open: float
    entries: List[ReceivableEntry]


class OutboxMessage(BaseModel):
    id: int
    key: str
    status: str
    round: Optional[int]
    to: Optional[str]
    subject: Optional[str]
    sent_at: Optional[datetime]


class DisputeDetail(BaseModel):
    dispute: DisputeSummary
    letter: str
    notice_to: Dict[str, Any]
    facts: Dict[str, Any]
    credits: List[Dict[str, Any]]
    refusal_reason: Optional[str]
    history: List[HistoryEvent]
    items: Dict[str, Optional[Dict[str, Any]]]
    receivable: Receivable
    outbox: List[OutboxMessage]
    reply_outcomes: List[str]
    gateway_error: Optional[str] = None


class ApproveBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=4000)


class ReplyBody(BaseModel):
    outcome: Outcome
    granted: Optional[Decimal] = Field(None, ge=0, max_digits=14, decimal_places=2)
    credit_memo_ref: Optional[str] = Field(None, max_length=200)
    reason: Optional[str] = Field(None, max_length=8000)
    received_on: Optional[date] = None
    sender: Optional[str] = Field(None, max_length=320)
    message_id: Optional[str] = Field(None, max_length=300)
    body: Optional[str] = Field(None, max_length=20000)


# --- reads ------------------------------------------------------------------------

_SUMMARY_SQL = """
    SELECT d.id, d.status, d.landlord_id, l.name AS landlord_name, d.lease_id, d.clinic_id,
           d.region_id, d.entity_id, d.period, d.charge_type, c.invoice_id, d.billed,
           d.supported, d.amount, d.credited_amount, d.work_item_id, w.state AS work_item_state,
           d.sent_at, d.updated_at
      FROM dispute d
      JOIN landlord l ON l.id = d.landlord_id
      JOIN landlord_charge c ON c.id = d.charge_id
      JOIN work_item w ON w.id = d.work_item_id
"""


@router.get("/disputes", response_model=DisputeList)
def list_disputes(
    status: Optional[str] = Query(None, description="One of the dispute statuses"),
    clinic_id: Optional[str] = Query(None, min_length=1, max_length=200),
    actor: SessionActor = Depends(current_actor),
    eng: Engine = Depends(get_engine),
) -> DisputeList:
    if status is not None and status not in disputes.STATUSES:
        raise HTTPException(422, "status must be one of %s" % ", ".join(disputes.STATUSES))
    where, params = scope_sql(actor, "d")
    if clinic_id is not None:
        where.append("d.clinic_id = :clinic_id")
        params["clinic_id"] = clinic_id
    base = " AND ".join(where) or "TRUE"
    with eng.connect() as conn:
        counts = dict.fromkeys(disputes.STATUSES, 0)
        counts.update(dict(conn.execute(text(
            "SELECT d.status, count(*) FROM dispute d WHERE %s GROUP BY d.status" % base),
            params).all()))
        rows = conn.execute(text(_SUMMARY_SQL + " WHERE %s%s ORDER BY d.updated_at DESC, d.id" % (
            base, " AND d.status = :status" if status else "")),
            dict(params, status=status)).mappings().all()
        out = [_summary(conn, r) for r in rows]
    return DisputeList(counts=counts, total=len(out), disputes=out)


@router.get("/disputes/{dispute_id}", response_model=DisputeDetail)
def dispute_detail(dispute_id: str = DisputeId, actor: SessionActor = Depends(current_actor),
                   eng: Engine = Depends(get_engine)) -> DisputeDetail:
    with eng.connect() as conn:
        return _detail(conn, actor, dispute_id)


# --- writes -----------------------------------------------------------------------

@router.post("/disputes/{dispute_id}/approve", response_model=DisputeDetail)
def approve_letter(dispute_id: str = DisputeId, body: Optional[ApproveBody] = None,
                   actor: SessionActor = Depends(current_actor), eng: Engine = Depends(get_engine),
                   gateway_engine: Engine = Depends(get_gateway_engine)) -> DisputeDetail:
    body = body or ApproveBody()
    with eng.connect() as conn:
        with _errors():
            with conn.begin():
                d = _visible(conn, actor, dispute_id)
                transition(conn, work_actor(actor), d["work_item_id"], "approve",
                           reason=body.reason, evidence={"dispute_id": dispute_id})
    return _after_write(eng, gateway_engine, actor, dispute_id)


@router.post("/disputes/{dispute_id}/receivable/approve", response_model=DisputeDetail)
def approve_receivable(dispute_id: str = DisputeId, body: Optional[ApproveBody] = None,
                       actor: SessionActor = Depends(current_actor),
                       eng: Engine = Depends(get_engine),
                       gateway_engine: Engine = Depends(get_gateway_engine)) -> DisputeDetail:
    body = body or ApproveBody()
    with eng.connect() as conn:
        with _errors():
            with conn.begin():
                _visible(conn, actor, dispute_id)
                disputes.approve_receivable(conn, work_actor(actor), dispute_id, reason=body.reason)
    return _after_write(eng, gateway_engine, actor, dispute_id)


@router.post("/disputes/{dispute_id}/reply", response_model=DisputeDetail)
def record_reply(body: ReplyBody, dispute_id: str = DisputeId,
                 actor: SessionActor = Depends(current_actor), eng: Engine = Depends(get_engine),
                 gateway_engine: Engine = Depends(get_gateway_engine)) -> DisputeDetail:
    with eng.connect() as conn:
        with _errors():
            with conn.begin():
                _visible(conn, actor, dispute_id)
                disputes.record_reply(
                    conn, work_actor(actor), dispute_id, body.outcome, granted=body.granted,
                    credit_memo_ref=body.credit_memo_ref, reason=body.reason,
                    received_on=body.received_on, sender=body.sender,
                    message_id=body.message_id, body=body.body)
    return _after_write(eng, gateway_engine, actor, dispute_id)


class _errors:
    """Map the work layer's refusals to HTTP, the way api/items.py does."""

    def __enter__(self):
        return self

    def __exit__(self, kind, exc, tb):
        if exc is None:
            return False
        if isinstance(exc, Denied):
            raise HTTPException(403, exc.reason) from None
        if isinstance(exc, (IllegalTransition, disputes.DisputeStateError)):
            raise HTTPException(409, str(exc)) from None
        if isinstance(exc, disputes.UnknownDispute):
            raise HTTPException(404, str(exc)) from None
        if isinstance(exc, ValueError):
            raise HTTPException(422, str(exc)) from None
        return False


def _after_write(eng: Engine, gateway_engine: Engine, actor: SessionActor,
                 dispute_id: str) -> DisputeDetail:
    error = None
    try:
        with gateway_engine.begin() as conn:
            gateway.sync_disputes(conn, dispute_id=dispute_id)
    except Exception as exc:  # noqa: BLE001 - the write is committed; never lose it to the gateway
        log.warning("dispute %s not synced by the gateway: %s", dispute_id, exc)
        error = "%s: %s" % (type(exc).__name__, exc)
    with eng.connect() as conn:
        detail = _detail(conn, actor, dispute_id)
    detail.gateway_error = error
    return detail


# --- shaping ----------------------------------------------------------------------

def _visible(conn: Connection, actor: SessionActor, dispute_id: str) -> Dict[str, Any]:
    row = conn.execute(text("SELECT * FROM dispute WHERE id = :id"),
                       {"id": dispute_id}).mappings().first()
    if row is None or not in_scope(actor, row):
        raise HTTPException(404, "no dispute %s" % dispute_id)
    return dict(row)


def _summary(conn: Connection, row) -> DisputeSummary:
    rec = disputes.receivable(conn, row["id"])
    return DisputeSummary(**{k: (float(v) if isinstance(v, Decimal) else v) for k, v in row.items()},
                          open_receivable=float(rec["open"]))


def _detail(conn: Connection, actor: SessionActor, dispute_id: str) -> DisputeDetail:
    d = _visible(conn, actor, dispute_id)
    row = conn.execute(text(_SUMMARY_SQL + " WHERE d.id = :id"), {"id": dispute_id}).mappings().one()
    history = [HistoryEvent(seq=e.seq, at=e.at, actor_id=e.actor_id, action=e.action,
                            allowed=e.allowed, reason=e.reason,
                            from_status=(e.diff or {}).get("from"), to_status=(e.diff or {}).get("to"),
                            evidence=e.evidence if isinstance(e.evidence, dict) else None)
               for e in disputes.history(conn, dispute_id)]
    letter_item = conn.execute(text(
        "SELECT id, state, proposal, reason, updated_at FROM work_item WHERE id = :id"),
        {"id": d["work_item_id"]}).mappings().first()
    rec_item = disputes.receivable_item(conn, dispute_id)
    rec = disputes.receivable(conn, dispute_id)
    outbox = conn.execute(text("""
        SELECT id, idempotency_key AS key, status, sent_at, payload->>'round' AS round,
               payload->>'to' AS "to", payload->>'subject' AS subject
          FROM outbox WHERE kind = 'email' AND idempotency_key LIKE :prefix ORDER BY id
    """), {"prefix": "dispute_letter:%s:%%" % dispute_id}).mappings().all()
    allowed = sorted(disputes.RECORDERS.get(actor.role, ()))
    return DisputeDetail(
        dispute=_summary(conn, row), letter=d["letter"], notice_to=d["notice_to"],
        facts=d["facts"], credits=list(d["credits"] or []), refusal_reason=d["refusal_reason"],
        history=history,
        items={"letter": _plain(letter_item),
               "receivable": _plain({k: rec_item[k] for k in ("id", "state", "proposal", "reason",
                                                              "updated_at")} if rec_item else None)},
        receivable=Receivable(recognized=float(rec["recognized"]), cleared=float(rec["cleared"]),
                              open=float(rec["open"]),
                              entries=[ReceivableEntry(**e) for e in rec["entries"]]),
        outbox=[OutboxMessage(**dict(o, round=int(o["round"]) if o["round"] else None))
                for o in outbox],
        reply_outcomes=[o for o in disputes.OUTCOMES if o in allowed])


def _plain(row) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in dict(row).items()}
