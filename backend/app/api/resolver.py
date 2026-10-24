"""The resolver's two reads: an item's sources, and the questions waiting on a person.

    GET /api/items/{id}/sources     sources, trust decision, confidence and route
    GET /api/questions?mine=1       open questions, with due dates and dollars at stake

`/sources` reads what work/resolver.py put on the item's evidence when the
checker proposed it. A CHARGE_CHECK item proposed before the resolver existed
is resolved on the fly (read-only, nothing written), so every charge check has
an answer. Scope is the queue's: an item outside yours is a 404.

    {"item_id": 7, "kind": "CHARGE_CHECK", "state": "PROPOSED",
     "sources": [{"source_id", "kind", "rank", "rank_name", "label", "value", "claim",
                  "citation": {...}, "extraction_confidence", "read_quality",
                  "suspect", "note"}, ...],
     "decision": {"action": "hold", "explanation": "Trusted the lease ... over ...",
                  "trusted", "agreeing", "contradicting", "superseded", "set_aside",
                  "trust_gap", "policy"},
     "explanation": "...", "confidence": 0.56, "confidence_reasons": ["...", ...],
     "route": {"role", "nature", "asked_to", "also_to", "amount_at_stake", "material",
               "reasons"},
     "asked_to": "PER-RM-BAY", "payment_due": "2026-01-01",
     "question": null | {"id", "asked_to", "body", "asked_at", "due_at", "reminders",
                         "last_reminded_at", "escalated_to"},
     "computed": false}

`/questions` lists unanswered questions in the actor's scope, oldest due first.
With `mine=1`, only those waiting on the session actor: asked to them,
escalated to them, or material enough that the route copied them
(`why`: asked | escalated | material). `overdue` is against the business
clock (jobs/clock.py), not the wall clock.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ..auth.deps import SessionActor, current_actor
from ..jobs import clock
from ..jobs.reminders import history_of
from ..work import resolver
from .deps import get_engine
from .items import ItemId, _visible_item, scope_sql

router = APIRouter(prefix="/api", tags=["resolver"])


class SourceOut(BaseModel):
    source_id: str
    kind: str
    rank: int
    rank_name: str
    label: str
    value: Any
    claim: str
    citation: Dict[str, Any]
    extraction_confidence: Optional[float] = None
    read_quality: Optional[float] = None
    suspect: bool = False
    note: str = ""


class OpenQuestion(BaseModel):
    id: int
    asked_to: str
    body: str
    asked_at: datetime
    due_at: Optional[datetime]
    reminders: int
    last_reminded_at: Optional[datetime]
    escalated_to: Optional[str]


class ItemSources(BaseModel):
    item_id: int
    kind: str
    state: str
    sources: List[SourceOut]
    decision: Optional[Dict[str, Any]]
    explanation: Optional[str]
    confidence: Optional[float]
    confidence_reasons: List[str]
    route: Optional[Dict[str, Any]]
    asked_to: Optional[str]
    payment_due: Optional[str]
    question: Optional[OpenQuestion]
    computed: bool                  # true: resolved on the fly, not read from evidence


class QuestionItem(BaseModel):
    id: int
    work_item_id: int
    kind: str
    state: str
    title: str
    clinic_id: Optional[str]
    region_id: Optional[str]
    entity_id: Optional[str]
    period: Optional[date]
    asked_to: str
    asked_by: str
    body: str
    asked_at: datetime
    due_at: Optional[datetime]
    due_on: Optional[date]
    overdue: bool
    amount_at_stake: Optional[float]
    confidence: Optional[float]
    reminders: int
    last_reminded_at: Optional[datetime]
    escalated_to: Optional[str]
    why: Optional[Literal["asked", "escalated", "material"]]


class Questions(BaseModel):
    business_date: date
    total: int
    questions: List[QuestionItem]


@router.get("/items/{item_id}/sources", response_model=ItemSources)
def item_sources(item_id: int = ItemId, actor: SessionActor = Depends(current_actor),
                 eng: Engine = Depends(get_engine)) -> ItemSources:
    with eng.connect() as conn:
        item = _visible_item(conn, actor, item_id)
        ev = dict(item.get("evidence") or {})
        computed = False
        if "sources" not in ev and item["kind"] == "CHARGE_CHECK" and "supported" in ev:
            ev.update(resolver.resolve(conn, ev, kind=item["kind"],
                                       region_id=item.get("region_id"),
                                       entity_id=item.get("entity_id")))
            computed = True
        question = _open_question(conn, item_id)
    decision = ev.get("decision") if isinstance(ev.get("decision"), dict) else None
    return ItemSources(
        item_id=item["id"], kind=item["kind"], state=item["state"],
        sources=[SourceOut(**resolver.Source.from_dict(s).to_dict())
                 for s in ev.get("sources") or [] if isinstance(s, dict)],
        decision=decision, explanation=(decision or {}).get("explanation"),
        confidence=_float(ev.get("confidence")),
        confidence_reasons=[str(r) for r in ev.get("confidence_reasons") or []],
        route=ev.get("route") if isinstance(ev.get("route"), dict) else None,
        asked_to=ev.get("asked_to") if isinstance(ev.get("asked_to"), str) else None,
        payment_due=ev.get("payment_due") if isinstance(ev.get("payment_due"), str) else None,
        question=question, computed=computed)


@router.get("/questions", response_model=Questions)
def questions(mine: bool = Query(False, description="only those waiting on me"),
              actor: SessionActor = Depends(current_actor),
              eng: Engine = Depends(get_engine)) -> Questions:
    where, params = scope_sql(actor)
    where.append("q.answered_by IS NULL")
    with eng.connect() as conn:
        today = clock.today(conn)
        rows = conn.execute(text("""
            SELECT q.id, q.work_item_id, q.asked_to, q.asked_by, q.body, q.asked_at, q.due_at,
                   w.kind, w.state, w.title, w.clinic_id, w.region_id, w.entity_id, w.period,
                   w.evidence
              FROM question q JOIN work_item w ON w.id = q.work_item_id
             WHERE %s
             ORDER BY q.due_at NULLS LAST, q.id
        """ % " AND ".join(where)), params).mappings().all()
        out: List[QuestionItem] = []
        for r in rows:
            follow = _follow_up(conn, r["id"])
            ev = r["evidence"] if isinstance(r["evidence"], dict) else {}
            route = ev.get("route") if isinstance(ev.get("route"), dict) else {}
            why = ("asked" if r["asked_to"] == actor.id
                   else "escalated" if follow["escalated_to"] == actor.id
                   else "material" if actor.id in (route.get("also_to") or []) else None)
            if mine and why is None:
                continue
            due_on = r["due_at"].date() if r["due_at"] is not None else None
            out.append(QuestionItem(
                id=r["id"], work_item_id=r["work_item_id"], kind=r["kind"], state=r["state"],
                title=r["title"], clinic_id=r["clinic_id"], region_id=r["region_id"],
                entity_id=r["entity_id"], period=r["period"], asked_to=r["asked_to"],
                asked_by=r["asked_by"], body=r["body"], asked_at=r["asked_at"],
                due_at=r["due_at"], due_on=due_on,
                overdue=due_on is not None and today > due_on,
                amount_at_stake=_float(route.get("amount_at_stake")),
                confidence=_float(ev.get("confidence")), why=why, **follow))
    return Questions(business_date=today, total=len(out), questions=out)


def _open_question(conn: Connection, item_id: int) -> Optional[OpenQuestion]:
    row = conn.execute(text("""
        SELECT id, asked_to, body, asked_at, due_at FROM question
         WHERE work_item_id = :id AND answered_by IS NULL ORDER BY id DESC LIMIT 1
    """), {"id": item_id}).mappings().first()
    if row is None:
        return None
    return OpenQuestion(**row, **_follow_up(conn, row["id"]))


def _follow_up(conn: Connection, question_id: int) -> Dict[str, Any]:
    reminders = [e for e in history_of(conn, question_id) if e["action"] == "remind"]
    escalations = [e for e in history_of(conn, question_id) if e["action"] == "escalate"]
    return {"reminders": len(reminders),
            "last_reminded_at": reminders[-1]["at"] if reminders else None,
            "escalated_to": (escalations[-1]["evidence"] or {}).get("escalated_to")
            if escalations else None}


def _float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
