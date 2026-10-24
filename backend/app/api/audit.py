"""GET /api/audit: the timeline for a lease or any one subject, with the
"chain verified" badge from `verify_chain()` (PHASE_1.md group 11).

    /api/audit?lease_id=LEASE-01
    /api/audit?subject_type=work_item&subject_id=42

`lease_id` gathers every event about the lease: the lease itself, its
versions, its landlord charges, the work items about those charges, and any
event whose evidence or diff names the lease. The chain is verified over the
whole stream, not just the rows returned, because a filtered view of a broken
chain is still a broken chain.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..auth.deps import current_actor
from ..work.events import verify_chain
from .deps import get_engine
from .schemas import AuditEvent, AuditTrail

router = APIRouter(prefix="/api", tags=["audit"], dependencies=[Depends(current_actor)])

_COLUMNS = "seq, at, actor_id, action, subject_type, subject_id, allowed, reason"

_FOR_LEASE = """
    (e.subject_type = 'lease' AND e.subject_id = :lease_id)
    OR e.evidence ->> 'lease_id' = :lease_id
    OR e.diff ->> 'lease_id' = :lease_id
    OR (e.subject_type = 'lease_version' AND e.subject_id IN (
            SELECT id::text FROM lease_version WHERE lease_id = :lease_id))
    OR (e.subject_type = 'landlord_charge' AND e.subject_id IN (
            SELECT id FROM landlord_charge WHERE lease_id = :lease_id))
    OR (e.subject_type = 'work_item' AND e.subject_id IN (
            SELECT w.id::text FROM work_item w
             WHERE w.evidence ->> 'lease_id' = :lease_id
                OR (w.subject_type = 'lease' AND w.subject_id = :lease_id)
                OR (w.subject_type = 'landlord_charge' AND w.subject_id IN (
                        SELECT id FROM landlord_charge WHERE lease_id = :lease_id))))
"""


@router.get("/audit", response_model=AuditTrail)
def audit_trail(
    lease_id: Optional[str] = Query(None, min_length=1, max_length=200),
    subject_type: Optional[str] = Query(None, min_length=1, max_length=100),
    subject_id: Optional[str] = Query(None, min_length=1, max_length=200),
    limit: int = Query(500, ge=1, le=5000, description="Newest events win when there are more"),
    eng: Engine = Depends(get_engine),
) -> AuditTrail:
    if subject_id is not None and subject_type is None:
        raise HTTPException(422, "subject_id needs subject_type: ids are only unique per type")

    where, params = ["TRUE"], {"limit": limit}
    if lease_id is not None:
        where.append("(%s)" % _FOR_LEASE)
        params["lease_id"] = lease_id
    if subject_type is not None:
        where.append("e.subject_type = :subject_type")
        params["subject_type"] = subject_type
    if subject_id is not None:
        where.append("e.subject_id = :subject_id")
        params["subject_id"] = subject_id

    with eng.connect() as conn:
        if lease_id is not None and conn.execute(
                text("SELECT 1 FROM lease WHERE id = :id"), {"id": lease_id}).first() is None:
            raise HTTPException(404, "no lease %r" % lease_id)
        broken = verify_chain(conn)
        rows = conn.execute(text("""
            SELECT * FROM (
                SELECT %s FROM audit_event e WHERE %s ORDER BY seq DESC LIMIT :limit
            ) newest ORDER BY seq
        """ % (_COLUMNS, " AND ".join(where))), params).mappings().all()

    return AuditTrail(
        chain_verified=broken is None,
        broken_seq=broken.seq if broken else None,
        events=[AuditEvent(**r) for r in rows],
    )
