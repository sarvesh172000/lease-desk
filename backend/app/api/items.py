"""The work queue and the actions on it (PHASE_1.md group 11).

    GET  /api/items?state=&clinic_id=&region_id=&period=   the queue, with counts per state
    GET  /api/items/{id}                                   item, evidence, questions, timeline
    GET  /api/items/{id}/allowed-actions                   {"actions": [...]}, from can()
    POST /api/items/{id}/actions/{action}                  {reason?, patch?}

Every route needs a session. Reads are scoped the way can() scopes writes: a
regional manager sees their region, anyone with an entity sees that entity,
and everyone else (controller, AP clerk, auditor without an entity) sees all.
An item outside your scope is a 404 on read, as if it were not there.

Writes are transition() on `lease_api` as the session actor, so the answer the
button got from allowed-actions is the answer the press gets. A refusal is
403 with can()'s reason, and its allowed = false event is already committed
(transition() writes it on its own connection), so it is in the timeline even
though nothing else changed. A move the state machine does not have is 409.

An approved CHARGE_CHECK item on a landlord charge is posted straight away
through the gateway, on a `lease_gateway` connection, in a transaction of its
own *after* the approval commits. If posting fails the approval stands, the
item stays APPROVED, and the response says posting is pending; posting again
later is safe because the gateway is idempotent on the charge's key.
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ..auth.deps import SessionActor, current_actor
from ..work import gateway
from ..work.events import events_for
from ..work.roles import Actor
from ..work.transitions import (
    Denied,
    IllegalTransition,
    UnknownItem,
    allowed_actions,
    load_item,
    transition,
)
from .deps import get_engine, get_gateway_engine

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["items"])

ItemId = PathParam(..., ge=1, le=2**63 - 1)

STATES = ("NEW", "PROPOSED", "NEEDS_INFO", "HELD", "APPROVED", "REJECTED", "POSTED", "CLOSED")

# What a person may press. propose and ask are the agents' moves, post is the
# gateway's; none of them is a button.
HumanAction = Literal["approve", "hold", "resume", "reject", "answer", "close"]

QUEUE_COLUMNS = ("id", "kind", "state", "title", "clinic_id", "region_id", "entity_id",
                 "period", "amount", "proposal", "reason", "updated_at")


# --- models -----------------------------------------------------------------------

class QueueItem(BaseModel):
    id: int
    kind: str
    state: str
    title: str
    clinic_id: Optional[str]
    region_id: Optional[str]
    entity_id: Optional[str]
    period: Optional[date]
    amount: Optional[float]
    proposal: Optional[str]
    reason: Optional[str]
    updated_at: datetime


class Queue(BaseModel):
    counts: Dict[str, int]       # every state, zeros included; the state filter is not applied
    total: int                   # rows in `items`
    items: List[QueueItem]


class Question(BaseModel):
    id: int
    asked_to: str
    asked_by: str
    body: str
    answer: Optional[str]
    answered_by: Optional[str]
    asked_at: datetime
    answered_at: Optional[datetime]
    due_at: Optional[datetime]


class TimelineEvent(BaseModel):
    seq: int
    at: datetime
    actor_id: str
    action: str
    allowed: bool
    reason: Optional[str]
    from_state: Optional[str]
    to_state: Optional[str]
    diff: Optional[Dict[str, Any]]
    evidence: Optional[Dict[str, Any]]


class ItemDetail(BaseModel):
    item: Dict[str, Any]
    evidence: Dict[str, Any]
    questions: List[Question]
    timeline: List[TimelineEvent]
    allowed_actions: List[str]


class AllowedActions(BaseModel):
    actions: List[str]


class ActionBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=4000)
    patch: Optional[Dict[str, Any]] = None


class Posting(BaseModel):
    status: Literal["posted", "pending"]
    journal_entry_id: Optional[int] = None
    error: Optional[str] = None


class ActionResult(BaseModel):
    state: str
    item: Dict[str, Any]
    posting: Optional[Posting] = None   # only after approving a postable charge check


# --- scope ------------------------------------------------------------------------

def work_actor(actor: SessionActor) -> Actor:
    return Actor(id=actor.id, role=actor.role, region_id=actor.region_id,
                 entity_id=actor.entity_id)


def scope_sql(actor: SessionActor, alias: str = "w") -> Tuple[List[str], Dict[str, Any]]:
    """The WHERE clauses that keep a read inside what this actor may see.
    The same two rules can() applies to writes, on the same columns."""
    where, params = [], {}
    if actor.entity_id is not None:
        where.append("%s.entity_id = :scope_entity" % alias)
        params["scope_entity"] = actor.entity_id
    if actor.role == "regional_manager":
        where.append("%s.region_id IS NOT DISTINCT FROM :scope_region" % alias)
        params["scope_region"] = actor.region_id
    return where, params


def in_scope(actor: SessionActor, item: Mapping) -> bool:
    if actor.entity_id is not None and item.get("entity_id") != actor.entity_id:
        return False
    if actor.role == "regional_manager" and item.get("region_id") != actor.region_id:
        return False
    return True


# --- reads ------------------------------------------------------------------------

@router.get("/items", response_model=Queue)
def queue(
    state: Optional[str] = Query(None, description="One of the eight work states"),
    clinic_id: Optional[str] = Query(None, min_length=1, max_length=200),
    region_id: Optional[str] = Query(None, min_length=1, max_length=200),
    period: Optional[date] = Query(None, description="First of the month, YYYY-MM-01"),
    kind: Optional[str] = Query(None, min_length=1, max_length=100),
    limit: int = Query(1000, ge=1, le=5000),
    actor: SessionActor = Depends(current_actor),
    eng: Engine = Depends(get_engine),
) -> Queue:
    if state is not None and state not in STATES:
        raise HTTPException(422, "state must be one of %s" % ", ".join(STATES))
    where, params = scope_sql(actor)
    for column, value in (("clinic_id", clinic_id), ("region_id", region_id),
                          ("period", period), ("kind", kind)):
        if value is not None:
            where.append("w.%s = :%s" % (column, column))
            params[column] = value
    base = " AND ".join(where) or "TRUE"

    with eng.connect() as conn:
        counts = dict.fromkeys(STATES, 0)
        counts.update(dict(conn.execute(text(
            "SELECT w.state, count(*) FROM work_item w WHERE %s GROUP BY w.state" % base),
            params).all()))
        rows_where = base + (" AND w.state = :state" if state is not None else "")
        rows = conn.execute(text("""
            SELECT %s FROM work_item w WHERE %s ORDER BY w.updated_at DESC, w.id DESC LIMIT :limit
        """ % (", ".join("w." + c for c in QUEUE_COLUMNS), rows_where)),
            dict(params, state=state, limit=limit)).mappings().all()
    items = [QueueItem(**r) for r in rows]
    return Queue(counts=counts, total=len(items), items=items)


def _visible_item(conn: Connection, actor: SessionActor, item_id: int) -> Dict[str, Any]:
    try:
        item = load_item(conn, item_id)
    except UnknownItem:
        raise HTTPException(404, "no work item %s" % item_id) from None
    if not in_scope(actor, item):
        raise HTTPException(404, "no work item %s" % item_id)
    return item


@router.get("/items/{item_id}", response_model=ItemDetail)
def item_detail(item_id: int = ItemId, actor: SessionActor = Depends(current_actor),
                eng: Engine = Depends(get_engine)) -> ItemDetail:
    with eng.connect() as conn:
        item = _visible_item(conn, actor, item_id)
        questions = conn.execute(text("""
            SELECT id, asked_to, asked_by, body, answer, answered_by, asked_at, answered_at, due_at
              FROM question WHERE work_item_id = :id ORDER BY id
        """), {"id": item_id}).mappings().all()
        timeline = [_timeline_event(e) for e in events_for(conn, "work_item", item_id)]
    return ItemDetail(item=_public_item(item), evidence=item.get("evidence") or {},
                      questions=[Question(**q) for q in questions], timeline=timeline,
                      allowed_actions=allowed_actions(work_actor(actor), item))


@router.get("/items/{item_id}/allowed-actions", response_model=AllowedActions)
def item_allowed_actions(item_id: int = ItemId, actor: SessionActor = Depends(current_actor),
                         eng: Engine = Depends(get_engine)) -> AllowedActions:
    with eng.connect() as conn:
        item = _visible_item(conn, actor, item_id)
    return AllowedActions(actions=allowed_actions(work_actor(actor), item))


# --- writes -----------------------------------------------------------------------

@router.post("/items/{item_id}/actions/{action}", response_model=ActionResult)
def act(action: HumanAction, item_id: int = ItemId, body: Optional[ActionBody] = None,
        actor: SessionActor = Depends(current_actor), eng: Engine = Depends(get_engine),
        gateway_engine: Engine = Depends(get_gateway_engine)) -> ActionResult:
    body = body or ActionBody()
    return perform(eng, gateway_engine, actor, item_id, action, reason=body.reason,
                   patch=body.patch)


def perform(eng: Engine, gateway_engine: Engine, actor: SessionActor, item_id: int,
            action: str, *, reason: Optional[str] = None,
            patch: Optional[Mapping] = None) -> ActionResult:
    """One action as one person, then the gateway post an approval implies.
    Shared by the queue's action route and §16's exception approve."""
    with eng.connect() as conn:
        try:
            with conn.begin():
                row = transition(conn, work_actor(actor), item_id, action,
                                 reason=reason, patch=patch)
        except Denied as exc:
            raise HTTPException(403, exc.reason) from None
        except UnknownItem:
            raise HTTPException(404, "no work item %s" % item_id) from None
        except IllegalTransition as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:            # a bad patch or a missing answer
            raise HTTPException(422, str(exc)) from None

    posting = None
    if action == "approve" and _postable(row):
        posting = _post(gateway_engine, row["id"])
        if posting.status == "posted":
            with eng.connect() as conn:
                row = dict(conn.execute(text("SELECT * FROM work_item WHERE id = :id"),
                                        {"id": row["id"]}).mappings().one())
    return ActionResult(state=row["state"], item=_public_item(row), posting=posting)


def _postable(row: Mapping) -> bool:
    return (row["state"] == "APPROVED" and row["kind"] == gateway.CHARGE_CHECK
            and row["subject_type"] == "landlord_charge")


def _post(gateway_engine: Engine, item_id: int) -> Posting:
    try:
        with gateway_engine.begin() as conn:
            entry_id = gateway.post_approved_charge(conn, item_id)
    except Exception as exc:  # noqa: BLE001 — the approval is committed; never lose it to a post
        log.warning("approved work item %s not posted: %s", item_id, exc)
        return Posting(status="pending", error="%s: %s" % (type(exc).__name__, exc))
    return Posting(status="posted", journal_entry_id=entry_id)


# --- shaping ----------------------------------------------------------------------

def _public_item(row: Mapping) -> Dict[str, Any]:
    out = {k: v for k, v in row.items() if k not in ("proposers", "answered_by")}
    for k, v in out.items():
        if isinstance(v, Decimal):
            out[k] = float(v)
    return out


def _timeline_event(e) -> TimelineEvent:
    diff = e.diff if isinstance(e.diff, dict) else None
    return TimelineEvent(seq=e.seq, at=e.at, actor_id=e.actor_id, action=e.action,
                         allowed=e.allowed, reason=e.reason,
                         from_state=(diff or {}).get("from"), to_state=(diff or {}).get("to"),
                         diff=diff, evidence=e.evidence if isinstance(e.evidence, dict) else None)
