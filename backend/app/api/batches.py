"""POST /api/batches/{period}/release: the AP clerk releases a payment batch.

    POST /api/batches/2026-01/release        {"entity_id": "ENT-CA"}   (body optional)

It calls `gateway.release_batch()` on a `lease_gateway` connection, the only
role that may write the outbox. The gateway decides who may release (an
active AP clerk, for their own entity) and records a refusal on its own
transaction, so a 403 here always has an allowed = false `release_batch`
event on `ap_batch` behind it. Deliberately no `require_role` in front: a
refusal before the gateway would leave no trace.

Releasing a period twice returns the batch already released (`created`
false), never a second one.
"""

import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from ..auth.deps import SessionActor, current_actor
from ..work import gateway
from .deps import get_gateway_engine

router = APIRouter(prefix="/api", tags=["batches"])

_PERIOD = re.compile(r"^(\d{4})-(\d{2})(?:-01)?$")


class ReleaseBody(BaseModel):
    entity_id: Optional[str] = Field(None, min_length=1, max_length=200)


class BatchOut(BaseModel):
    outbox_id: int
    idempotency_key: str
    created: bool             # false when this period's batch was already released
    period: date
    item_count: int
    total: float


def parse_period(raw: str) -> date:
    match = _PERIOD.match(raw)
    try:
        if match is None:
            raise ValueError
        return date(int(match.group(1)), int(match.group(2)), 1)
    except ValueError:
        raise HTTPException(422, "period must be YYYY-MM or YYYY-MM-01, got %r" % raw) from None


@router.post("/batches/{period}/release", response_model=BatchOut)
def release(period: str, body: Optional[ReleaseBody] = None,
            actor: SessionActor = Depends(current_actor),
            gateway_engine: Engine = Depends(get_gateway_engine)) -> BatchOut:
    month = parse_period(period)
    entity_id = (body or ReleaseBody()).entity_id
    try:
        with gateway_engine.begin() as conn:
            batch = gateway.release_batch(conn, month, actor.id, entity_id=entity_id)
    except gateway.NotAllowed as exc:
        raise HTTPException(403, str(exc)) from None
    except gateway.GatewayError as exc:      # nothing approved to release
        raise HTTPException(409, str(exc)) from None
    return BatchOut(outbox_id=batch.outbox_id, idempotency_key=batch.idempotency_key,
                    created=batch.created, period=month, item_count=batch.item_count,
                    total=float(batch.total))
