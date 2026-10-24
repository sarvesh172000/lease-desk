"""Policies over HTTP (PHASE_2.md group 10).

    GET  /api/policies                    every policy: status, version, precedent count,
                                          its POLICY work item and backtest summary
    GET  /api/policies/{id}               the rule, every version of its name, the
                                          evidence (precedents, linked decisions, question
                                          and answer), the stored backtest, the rejection
                                          if any, and the decisions that cite it
    POST /api/policies/{id}/backtest      run the backtest now and return it; for a policy
                                          still proposed, also queue a job that puts the
                                          fresh result on its work item for the controller
    POST /api/policies/onboard            {entity_id, year?}: controller only; queue the
                                          learner over that year's history

Approving or rejecting a policy is not here: it is the POLICY work item's
approve / reject through POST /api/items/{item_id}/actions/{action}, so can()
and separation of duties decide it like any other work, and the item's state
sets the policy's status (db/sql/006_policies.sql).

Reads run as `lease_api` for any signed-in person. A person with an entity
sees the policies scoped to that entity or to no entity in particular.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ..auth.deps import SessionActor, current_actor
from ..jobs.queue import enqueue
from ..work.backtest import backtest, summary
from ..work.events import append_event
from ..work.policies import POLICY_KIND, POLICY_SUBJECT, PolicyFormatError, policy_ref, validate_rule
from ..work.policy_learner import YEAR
from .deps import get_engine

router = APIRouter(prefix="/api", tags=["policies"])

PolicyId = PathParam(..., ge=1, le=2**63 - 1)


class PolicyRow(BaseModel):
    id: int
    name: str
    version: int
    status: str
    ref: str
    origin: Optional[str]
    description: Optional[str]
    scope: Dict[str, Any]
    action: Optional[str]
    charge_types: List[str]
    effective_from: Optional[date]
    effective_to: Optional[date]
    precedent_count: Optional[int]
    work_item_id: Optional[int]
    work_item_state: Optional[str]
    backtest: Optional[Dict[str, Any]]
    created_at: datetime


class PolicyList(BaseModel):
    counts: Dict[str, int]
    policies: List[PolicyRow]


class PolicyVersion(BaseModel):
    id: int
    version: int
    status: str
    created_at: datetime
    work_item_id: Optional[int]


class Citation(BaseModel):
    seq: int
    at: datetime
    actor_id: str
    action: str
    subject_type: str
    subject_id: str
    reason: Optional[str]


class PolicyDetail(BaseModel):
    policy: PolicyRow
    rule: Dict[str, Any]
    versions: List[PolicyVersion]
    evidence: Dict[str, Any]
    backtest: Optional[Dict[str, Any]]
    rejection: Optional[Dict[str, Any]]
    cited_by: List[Citation]


class BacktestResult(BaseModel):
    policy_id: int
    status: str
    backtest: Dict[str, Any]
    refresh_job_id: Optional[int] = None


class OnboardBody(BaseModel):
    entity_id: str = Field(..., min_length=1, max_length=100)
    year: int = Field(YEAR, ge=2000, le=2100)


class OnboardQueued(BaseModel):
    job_id: int
    entity_id: str
    year: int


_SELECT = """
    SELECT p.id, p.name, p.version, p.status, p.rule, p.effective_from, p.effective_to,
           p.created_at, w.id AS item_id, w.state AS item_state, w.evidence AS item_evidence,
           w.entity_id AS item_entity
      FROM policy p
      LEFT JOIN work_item w ON w.kind = :k AND w.subject_type = :st AND w.subject_id = p.id::text
"""


def _params(**extra) -> Dict[str, Any]:
    return dict(k=POLICY_KIND, st=POLICY_SUBJECT, **extra)


def _visible(actor: SessionActor, row) -> bool:
    if actor.entity_id is None:
        return True
    scope = (row["rule"] or {}).get("scope") or {}
    entity = scope.get("entity_id") or row["item_entity"]
    return entity is None or entity == actor.entity_id


def _row(r) -> PolicyRow:
    rule = r["rule"] or {}
    ev = r["item_evidence"] or {}
    when = rule.get("when") or {}
    return PolicyRow(
        id=r["id"], name=r["name"], version=r["version"], status=r["status"],
        ref=policy_ref(r["id"], r["version"]), origin=rule.get("origin"),
        description=rule.get("description"), scope=rule.get("scope") or {},
        action=(rule.get("then") or {}).get("action"), charge_types=when.get("charge_types") or [],
        effective_from=r["effective_from"], effective_to=r["effective_to"],
        precedent_count=(ev.get("precedents") or {}).get("count"),
        work_item_id=r["item_id"], work_item_state=r["item_state"],
        backtest=summary(ev.get("backtest")), created_at=r["created_at"])


def _load(conn: Connection, actor: SessionActor, policy_id: int):
    r = conn.execute(text(_SELECT + " WHERE p.id = :id"), _params(id=policy_id)).mappings().first()
    if r is None or not _visible(actor, r):
        raise HTTPException(404, "no policy %s" % policy_id)
    return r


@router.get("/policies", response_model=PolicyList)
def list_policies(actor: SessionActor = Depends(current_actor),
                  eng: Engine = Depends(get_engine)) -> PolicyList:
    with eng.connect() as conn:
        rows = conn.execute(text(_SELECT + " ORDER BY p.name, p.version"), _params()).mappings().all()
    rows = [r for r in rows if _visible(actor, r)]
    counts = dict.fromkeys(("proposed", "approved", "rejected", "retired"), 0)
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return PolicyList(counts=counts, policies=[_row(r) for r in rows])


@router.get("/policies/{policy_id}", response_model=PolicyDetail)
def policy_detail(policy_id: int = PolicyId, actor: SessionActor = Depends(current_actor),
                  eng: Engine = Depends(get_engine)) -> PolicyDetail:
    with eng.connect() as conn:
        r = _load(conn, actor, policy_id)
        versions = conn.execute(text(_SELECT + " WHERE p.name = :n ORDER BY p.version"),
                                _params(n=r["name"])).mappings().all()
        rejection = None
        if r["status"] == "rejected" and r["item_id"] is not None:
            e = conn.execute(text("""
                SELECT actor_id, at, reason FROM audit_event
                 WHERE subject_type = 'work_item' AND subject_id = :sid AND action = 'reject'
                   AND allowed ORDER BY seq DESC LIMIT 1
            """), {"sid": str(r["item_id"])}).mappings().first()
            if e is not None:
                rejection = {"by": e["actor_id"], "at": e["at"].isoformat(), "reason": e["reason"]}
        cited = conn.execute(text("""
            SELECT seq, at, actor_id, action, subject_type, subject_id, reason FROM audit_event
             WHERE policy_ref = :ref AND allowed ORDER BY seq
        """), {"ref": policy_ref(r["id"], r["version"])}).mappings().all()
    ev = dict(r["item_evidence"] or {})
    return PolicyDetail(
        policy=_row(r), rule=r["rule"] or {},
        versions=[PolicyVersion(id=v["id"], version=v["version"], status=v["status"],
                                created_at=v["created_at"], work_item_id=v["item_id"])
                  for v in versions],
        evidence={k: v for k, v in ev.items() if k != "backtest"},
        backtest=ev.get("backtest"), rejection=rejection,
        cited_by=[Citation(**c) for c in cited])


READ_ONLY_ROLES = ("auditor",)


def _refuse(eng: Engine, actor: SessionActor, action: str, subject_id: str, why: str) -> None:
    """A refused write is a 403 with one allowed = false event on record."""
    with eng.begin() as conn:
        append_event(conn, actor_id=actor.id, action=action, subject_type=POLICY_SUBJECT,
                     subject_id=subject_id, allowed=False, reason=why)
    raise HTTPException(403, why)


@router.post("/policies/{policy_id}/backtest", response_model=BacktestResult)
def run_backtest(policy_id: int = PolicyId, actor: SessionActor = Depends(current_actor),
                 eng: Engine = Depends(get_engine)) -> BacktestResult:
    if actor.role in READ_ONLY_ROLES:
        # A backtest may queue a refresh job, so it is a write.
        _refuse(eng, actor, "policy_backtest", str(policy_id),
                "role %s may read policies but never run a backtest" % actor.role)
    with eng.connect() as conn:
        with conn.begin():
            r = _load(conn, actor, policy_id)
            try:
                rule = validate_rule(r["rule"])
            except PolicyFormatError as exc:
                raise HTTPException(422, str(exc)) from None
            result = backtest(conn, rule, policy_id=policy_id)
            job_id = None
            stored = (r["item_evidence"] or {}).get("backtest") or {}
            if r["status"] == "proposed" and stored.get("digest") != result["digest"]:
                job_id = enqueue(conn, "policy_backtest", {"policy_id": policy_id},
                                 idempotency_key="policy_backtest:%d:%s" % (
                                     policy_id, result["digest"]))
    return BacktestResult(policy_id=policy_id, status=r["status"], backtest=result,
                          refresh_job_id=job_id)


@router.post("/policies/onboard", response_model=OnboardQueued)
def onboard(body: OnboardBody, actor: SessionActor = Depends(current_actor),
            eng: Engine = Depends(get_engine)) -> OnboardQueued:
    if actor.role != "controller":
        _refuse(eng, actor, "policy_onboard", body.entity_id,
                "only a controller may onboard policies; %s is %s" % (actor.id, actor.role))
    with eng.begin() as conn:
        if conn.execute(text("SELECT 1 FROM entity WHERE id = :e"),
                        {"e": body.entity_id}).first() is None:
            raise HTTPException(404, "no entity %s" % body.entity_id)
        # Once per state of the policy table: after a rejection the learner may
        # run again (and rejection memory decides what it may propose).
        state = conn.execute(text("""
            SELECT md5(coalesce(string_agg(id || '.' || status, ',' ORDER BY id), ''))
              FROM policy""")).scalar_one()
        job_id = enqueue(conn, "policy_onboard", {"entity_id": body.entity_id, "year": body.year},
                         idempotency_key="policy_onboard:%s:%d:%s" % (
                             body.entity_id, body.year, state))
    return OnboardQueued(job_id=job_id, entity_id=body.entity_id, year=body.year)
