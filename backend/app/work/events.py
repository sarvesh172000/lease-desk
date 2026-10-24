"""The event stream: `append_event()` writes one hash-chained row.

The database computes `seq`, `prev_hash` and `hash` (see db/sql/002_integrity.sql),
so a caller cannot forge or skip a link. `verify_chain()` walks the stream and
names the first broken link.

Every change to work goes through here, inside the same transaction as the
projection it drives, so the history and the state can never disagree.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

_INSERT = text("""
    INSERT INTO audit_event (actor_id, action, subject_type, subject_id, allowed,
                             reason, diff, evidence, policy_ref, model_ref)
    VALUES (:actor_id, :action, :subject_type, :subject_id, :allowed,
            :reason, CAST(:diff AS jsonb), CAST(:evidence AS jsonb), :policy_ref, :model_ref)
    RETURNING seq, at, prev_hash, hash
""")


@dataclass(frozen=True)
class Event:
    seq: int
    at: datetime
    actor_id: str
    action: str
    subject_type: str
    subject_id: str
    allowed: bool
    reason: Optional[str]
    diff: Optional[Mapping[str, Any]]
    evidence: Optional[Mapping[str, Any]]
    policy_ref: Optional[str]
    model_ref: Optional[str]
    prev_hash: str
    hash: str


@dataclass(frozen=True)
class ChainBreak:
    seq: int
    problem: str


def append_event(
    conn: Connection,
    *,
    actor_id: str,
    action: str,
    subject_type: str,
    subject_id: Any,
    allowed: bool = True,
    reason: Optional[str] = None,
    diff: Optional[Mapping[str, Any]] = None,
    evidence: Optional[Mapping[str, Any]] = None,
    policy_ref: Optional[str] = None,
    model_ref: Optional[str] = None,
) -> Event:
    """Append one event in the caller's transaction and return it as stored."""
    params = dict(
        actor_id=actor_id, action=action, subject_type=subject_type,
        subject_id=str(subject_id), allowed=allowed, reason=reason,
        diff=_json(diff), evidence=_json(evidence), policy_ref=policy_ref, model_ref=model_ref,
    )
    row = conn.execute(_INSERT, params).one()
    return Event(seq=row.seq, at=row.at, prev_hash=row.prev_hash, hash=row.hash,
                 actor_id=actor_id, action=action, subject_type=subject_type,
                 subject_id=str(subject_id), allowed=allowed, reason=reason, diff=diff,
                 evidence=evidence, policy_ref=policy_ref, model_ref=model_ref)


def verify_chain(conn: Connection) -> Optional[ChainBreak]:
    """None when the whole chain verifies, else the first broken link."""
    row = conn.execute(text("SELECT broken_seq, problem FROM audit_verify_chain()")).first()
    return ChainBreak(seq=row.broken_seq, problem=row.problem) if row else None


def events_for(conn: Connection, subject_type: str, subject_id: Any) -> list:
    """The timeline for one subject, oldest first."""
    rows = conn.execute(text("""
        SELECT * FROM audit_event WHERE subject_type = :t AND subject_id = :i ORDER BY seq
    """), {"t": subject_type, "i": str(subject_id)}).mappings().all()
    return [Event(**{k: r[k] for k in Event.__dataclass_fields__}) for r in rows]


def _json(value: Optional[Mapping[str, Any]]) -> Optional[str]:
    return None if value is None else json.dumps(value, sort_keys=True, default=str)
