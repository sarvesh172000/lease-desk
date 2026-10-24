"""POST (or GET) /api/items/{id}/why: "why is this item where it is?"

    POST /api/items/42/why   {"question": "why was this held?"}   (body optional)
    GET  /api/items/42/why?question=...

    -> {"answer": "two or three sentences", "rows": [...], "tools_used": [...],
        "path": "template" | "llm:<model_ref>", "item_id": 42, "notes": [...]}

Any signed-in person may ask (401 otherwise), the auditor included, about any
item they could read: the same scope as GET /api/items/{id}, and an item
outside it is a 404. The agent (work/why.py) runs on a `lease_reader`
connection in a READ ONLY transaction, so it cannot write even by mistake.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..auth.deps import SessionActor, current_actor
from ..db.engine import engine
from ..work.why import WhyError, read_only, why
from .items import in_scope

router = APIRouter(prefix="/api", tags=["why"], dependencies=[Depends(current_actor)])


def get_reader_engine() -> Engine:
    """The auditor's role, read-only on everything. Tests override this."""
    return engine("lease_reader")


class WhyRequest(BaseModel):
    question: Optional[str] = Field(None, max_length=1000)


class WhyResponse(BaseModel):
    answer: str
    rows: List[Dict[str, Any]]
    tools_used: List[str]
    path: str
    item_id: int
    notes: List[str] = []


ItemId = PathParam(..., ge=1, le=2 ** 62)


def _answer(item_id: int, question: Optional[str], actor: SessionActor, eng: Engine) -> WhyResponse:
    with read_only(eng) as conn:
        row = conn.execute(text("SELECT id, entity_id, region_id FROM work_item WHERE id = :id"),
                           {"id": item_id}).mappings().first()
        if row is None or not in_scope(actor, row):
            raise HTTPException(404, "no work item %s" % item_id)
        try:
            result = why(conn, item_id, question)
        except WhyError as exc:
            raise HTTPException(404, str(exc)) from None
    return WhyResponse(**result.as_dict())


@router.post("/items/{item_id}/why", response_model=WhyResponse)
def ask_why(item_id: int = ItemId, body: Optional[WhyRequest] = Body(None),
            actor: SessionActor = Depends(current_actor),
            eng: Engine = Depends(get_reader_engine)) -> WhyResponse:
    return _answer(item_id, body.question if body else None, actor, eng)


@router.get("/items/{item_id}/why", response_model=WhyResponse)
def get_why(item_id: int = ItemId, question: Optional[str] = Query(None, max_length=1000),
            actor: SessionActor = Depends(current_actor),
            eng: Engine = Depends(get_reader_engine)) -> WhyResponse:
    return _answer(item_id, question, actor, eng)
