"""GET /api/leases/{lease_id}/versions: what each version of a lease says, and
who confirmed it.

    [{"lease_id", "version", "lease_version_id", "effective_from",
      "confirmed": bool, "confirmed_by", "confirmed_at",
      "work_item": {"id", "state", "proposal", "allowed_actions"} | null,
      "terms": [{"field", "value", "page", "bbox", "quote", "confidence",
                 "document_id", "extracted_by": {"run_id", "agent", "prompt_id",
                                                 "prompt_version", "model"}}]}]

Oldest version first. `bbox` is in PDF points, origin top-left (the box the
document viewer draws over `/api/documents/{document_id}/pages/{page}.png`);
a term whose quote could not be located has null `page`, `bbox` and
`document_id` and confidence 0, never a guessed box. `extracted_by.agent` is
`abstraction:llm` or `abstraction:generator`: which path read the term.

Confirming is not a route of its own: a version is confirmed by approving its
LEASE_ABSTRACTION work item (`POST /api/items/{work_item.id}/actions/approve`).
`work_item.allowed_actions` is can()'s answer for the session actor, so the
lease page draws Confirm exactly when that press would be allowed.

`confirmed` is what the checker goes by: confirmed_by is set *and* the item
was not pulled back after approval (an approved item may be held; the
version then waits until it is approved again, and `confirmed_by` stays as
the record of the earlier confirmation).
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..auth.deps import SessionActor, current_actor
from ..jobs.lease_versions import is_confirmed
from ..work.roles import Actor
from ..work.transitions import allowed_actions, load_item
from .deps import get_engine

router = APIRouter(prefix="/api", tags=["leases"])

ITEM_KIND = "LEASE_ABSTRACTION"


class ExtractedBy(BaseModel):
    run_id: Optional[int]
    agent: Optional[str]
    prompt_id: Optional[str]
    prompt_version: Optional[str]
    model: Optional[str]


class Term(BaseModel):
    field: str
    value: Any
    page: Optional[int]
    bbox: Optional[List[float]]
    quote: Optional[str]
    confidence: Optional[float]
    document_id: Optional[str]
    extracted_by: Optional[ExtractedBy]


class VersionItem(BaseModel):
    id: int
    state: str
    proposal: Optional[str]
    allowed_actions: List[str]


class LeaseVersion(BaseModel):
    lease_id: str
    version: int
    lease_version_id: int
    effective_from: date
    confirmed: bool
    confirmed_by: Optional[str]
    confirmed_at: Optional[datetime]
    work_item: Optional[VersionItem]
    terms: List[Term]


@router.get("/leases/{lease_id}/versions", response_model=List[LeaseVersion])
def lease_versions(lease_id: str, actor: SessionActor = Depends(current_actor),
                   eng: Engine = Depends(get_engine)) -> List[LeaseVersion]:
    who = Actor(id=actor.id, role=actor.role, region_id=actor.region_id,
                entity_id=actor.entity_id)
    with eng.connect() as conn:
        if conn.execute(text("SELECT 1 FROM lease WHERE id = :id"), {"id": lease_id}).first() is None:
            raise HTTPException(404, "no lease %r" % lease_id)
        versions = conn.execute(text("""
            SELECT v.id, v.lease_id, v.version, v.effective_from, v.confirmed_by, v.confirmed_at,
                   w.id AS item_id, w.state AS item_state
              FROM lease_version v
              LEFT JOIN work_item w ON w.kind = :kind AND w.subject_type = 'lease_version'
                                   AND w.subject_id = v.id::text
             WHERE v.lease_id = :id ORDER BY v.version
        """), {"id": lease_id, "kind": ITEM_KIND}).mappings().all()
        terms: Dict[int, List[Term]] = {}
        if versions:
            for t in conn.execute(text("""
                SELECT t.lease_version_id, t.field, t.value, t.page, t.bbox, t.quote,
                       t.confidence, t.document_id, r.id AS run_id, r.agent, r.prompt_id,
                       r.prompt_version, r.model
                  FROM lease_term t LEFT JOIN agent_run r ON r.id = t.extracted_by_run
                 WHERE t.lease_version_id = ANY (CAST(:ids AS bigint[]))
                 ORDER BY t.lease_version_id, t.id
            """), {"ids": [v["id"] for v in versions]}).mappings():
                terms.setdefault(t["lease_version_id"], []).append(Term(
                    field=t["field"], value=t["value"], page=t["page"],
                    bbox=list(t["bbox"]) if t["bbox"] is not None else None, quote=t["quote"],
                    confidence=float(t["confidence"]) if t["confidence"] is not None else None,
                    document_id=t["document_id"],
                    extracted_by=None if t["run_id"] is None else ExtractedBy(
                        run_id=t["run_id"], agent=t["agent"], prompt_id=t["prompt_id"],
                        prompt_version=t["prompt_version"], model=t["model"])))
        items: Dict[int, VersionItem] = {}
        for v in versions:
            if v["item_id"] is None:
                continue
            item = load_item(conn, v["item_id"])
            items[v["id"]] = VersionItem(id=item["id"], state=item["state"],
                                         proposal=item["proposal"],
                                         allowed_actions=allowed_actions(who, item))
    return [LeaseVersion(
        lease_id=v["lease_id"], version=v["version"], lease_version_id=v["id"],
        effective_from=v["effective_from"],
        confirmed=is_confirmed(v["confirmed_by"], v["item_state"]),
        confirmed_by=v["confirmed_by"], confirmed_at=v["confirmed_at"],
        work_item=items.get(v["id"]), terms=terms.get(v["id"], []))
        for v in versions]
