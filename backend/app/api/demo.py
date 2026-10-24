"""The demo's routes: the controller's reset button and the month's run summary.

    POST /api/demo/reset                                   controller only, demo mode only
    GET  /api/summary/month?period=2026-01&entity=ENT-CA   the stepper's run summary
    GET  /api/summary/month/items?period=2026-01&entity=ENT-CA&metric=held
                                                           the rows behind one number

POST /api/demo/reset
--------------------
!!! IT REPLACES THE AUDIT STREAM. DEMO DATABASE, DEMO MODE ONLY. !!!
It restores the demo snapshot over the database this API serves
(app/demo/reset.py): every table, audit_event included, goes back to the
snapshot, so every event since then (approvals, denials, judge-provided
studio input) is gone. Nowhere else may audit_event lose a row. This is
acceptable only because it is the demo database and LEASEDESK_DEMO_MODE=1;
with demo mode off the route does not exist (404, like the other demo
routes). A signed-in person who is not a controller gets 403, and the refusal
is appended to the audit stream (allowed = false, action `demo_reset`) and
committed before the 403 is sent. A controller's reset is itself recorded,
as the first event after the restored history, so the timeline shows who
reset the demo and when.

    200 {"status": "reset", "database": ..., "seconds": 0.61, "within_budget": true,
         "verified": true, "chain_ok": true, "counts_match": true, "head_match": true,
         "judge_provided_cleared": 0, "snapshot": {"created_at", "git_sha", "chain_head", ...},
         "event_seq": 40}
    409 no usable snapshot (missing or stale: run `make demo-snapshot`), or a reset is running
    503 pg_restore is not installed where the API runs, or the restore failed and rolled back
"""

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.engine import Engine

from ..auth.deps import SessionActor, auth_settings, current_actor
from ..demo import reset as demo_reset
from ..demo import summary as month
from ..demo.snapshot import SnapshotError, Target, snapshot_path
from ..settings import Settings
from ..work.events import append_event
from .deps import get_engine, get_gateway_engine

router = APIRouter(prefix="/api", tags=["demo"])

CONTROLLER = "controller"
_RESET_LOCK = threading.Lock()


def demo_snapshot() -> Path:
    """The snapshot the button restores; overridden in tests."""
    return snapshot_path()


def _demo_only(settings: Settings = Depends(auth_settings)) -> Settings:
    if not settings.demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return settings


def _target(eng: Engine, settings: Settings) -> Target:
    """The database this API serves, reached as its owner."""
    url = eng.url
    return Target(url.host or settings.db_host, url.port or settings.db_port,
                  url.database or settings.db_name, settings.db_owner, settings.db_owner_password)


@router.post("/demo/reset")
def reset_demo(settings: Settings = Depends(_demo_only),
               actor: SessionActor = Depends(current_actor),
               eng: Engine = Depends(get_engine),
               gateway_engine: Engine = Depends(get_gateway_engine),
               dump: Path = Depends(demo_snapshot)) -> Dict[str, Any]:
    """Restore the demo snapshot. DEMO DATABASE ONLY: replaces audit_event."""
    t = _target(eng, settings)
    if actor.role != CONTROLLER:
        reason = "only a controller may reset the demo; %s is %s" % (actor.id, actor.role)
        with eng.begin() as conn:
            append_event(conn, actor_id=actor.id, action="demo_reset", subject_type="demo",
                         subject_id=t.database, allowed=False, reason=reason)
        raise HTTPException(status.HTTP_403_FORBIDDEN, reason)

    if not _RESET_LOCK.acquire(blocking=False):
        raise HTTPException(status.HTTP_409_CONFLICT, "a demo reset is already running")
    try:
        # Our own pooled connections hold no locks, but drop them so nothing
        # pooled from before the restore is reused after it.
        eng.dispose()
        gateway_engine.dispose()
        try:
            result = demo_reset.reset_database(t, dump, demo_mode=settings.demo_mode)
        except SnapshotError as exc:
            message = str(exc)
            if message.startswith("no pg_restore"):
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, message) from None
            raise HTTPException(status.HTTP_409_CONFLICT, message) from None
        except demo_reset.ResetFailed as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
        finally:
            eng.dispose()
            gateway_engine.dispose()
    finally:
        _RESET_LOCK.release()

    body = result.as_dict()
    with eng.begin() as conn:
        event = append_event(
            conn, actor_id=actor.id, action="demo_reset", subject_type="demo", subject_id=t.database,
            reason="demo reset to the snapshot of %s" % result.snapshot["created_at"],
            evidence={"seconds": body["seconds"], "verified": result.ok,
                      "judge_provided_cleared": result.judge_provided_cleared,
                      "snapshot_git_sha": result.snapshot["git_sha"],
                      "restored_chain_head": result.snapshot["chain_head"]})
    return dict(body, status="reset", event_seq=event.seq)


# ------------------------------------------------------------ run summary

def _period(raw: str):
    try:
        return month.parse_month(raw)
    except month.BadPeriod as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/summary/month", dependencies=[Depends(current_actor)])
def summary_month(period: str = Query(..., description="YYYY-MM"),
                  entity: Optional[str] = Query(None, max_length=200,
                                                description="entity id; blank for every entity"),
                  eng: Engine = Depends(get_engine)) -> Dict[str, Any]:
    with eng.connect() as conn:
        try:
            return month.month_summary(conn, _period(period), entity or None)
        except month.UnknownEntity as exc:
            raise HTTPException(404, str(exc)) from None


@router.get("/summary/month/items", dependencies=[Depends(current_actor)])
def summary_month_items(period: str = Query(..., description="YYYY-MM"),
                        metric: str = Query(..., description=", ".join(month.METRICS)),
                        entity: Optional[str] = Query(None, max_length=200),
                        eng: Engine = Depends(get_engine)) -> List[Dict[str, Any]]:
    if metric not in month.METRICS:
        raise HTTPException(422, "metric must be one of %s" % ", ".join(month.METRICS))
    with eng.connect() as conn:
        return month.month_items(conn, _period(period), entity or None, metric)
