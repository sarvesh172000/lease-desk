"""The state machine for work items, and the one function that moves them.

TRANSITIONS is the whole machine. A (state, action) pair that is not in it is
impossible, not merely disallowed: there is no role that could make it
happen, so it raises IllegalTransition and nothing is written.

transition() does, in the caller's transaction: lock the item, ask can(),
take a snapshot, build the patch, append the event, project it. The event is
the change; the work_item row is only its projection. A refusal from can() is
itself history: it is appended with allowed = false *on its own connection
and committed at once*, so it survives the caller rolling back after Denied
(see _record_denial for the one exception).

Ids are drawn before rows exist (create_item, ask), so the event that makes
a row can carry its id and replay can recreate it under the same one.
"""

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from . import live
from .events import Event, append_event
from .projections import apply, project
from .roles import Actor, can

ACTIONS = ("propose", "ask", "answer", "hold", "resume", "approve", "reject", "post", "close")

# (from_state, action) -> to_state. Anything absent is impossible.
TRANSITIONS = {
    ("NEW", "propose"): "PROPOSED",
    ("NEW", "ask"): "NEEDS_INFO",
    ("NEW", "hold"): "HELD",
    ("PROPOSED", "propose"): "PROPOSED",       # revise the proposal, e.g. after an answer
    ("PROPOSED", "ask"): "NEEDS_INFO",
    ("PROPOSED", "hold"): "HELD",
    ("PROPOSED", "approve"): "APPROVED",
    ("PROPOSED", "reject"): "REJECTED",
    ("NEEDS_INFO", "answer"): "PROPOSED",      # back in front of a reviewer, with the answer
    ("NEEDS_INFO", "hold"): "HELD",
    ("HELD", "resume"): "PROPOSED",
    ("HELD", "ask"): "NEEDS_INFO",
    ("HELD", "reject"): "REJECTED",
    ("APPROVED", "post"): "POSTED",
    ("APPROVED", "hold"): "HELD",              # pulled back before the gateway posts it
    ("APPROVED", "close"): "CLOSED",           # approved work with nothing to post
    ("REJECTED", "close"): "CLOSED",
    ("POSTED", "close"): "CLOSED",
}

# Columns a caller may change through `patch`. Everything else on the row is
# either identity (kind, subject, scope) or set by the machine itself.
PATCHABLE = frozenset({"title", "amount", "proposal", "reason", "evidence"})

# Actions whose `reason` is the item's current reason, not just the event's.
_REASON_ON_ITEM = frozenset({"propose", "hold", "reject"})

_CHAIN_LOCK = "lease_desk.audit_event_chain"   # the key in 002_integrity.sql


class Denied(Exception):
    """can() refused. The allowed = false event was already appended."""

    def __init__(self, reason: str, event: Optional[Event] = None):
        super().__init__(reason)
        self.reason = reason
        self.event = event


class IllegalTransition(Exception):
    """The (state, action) pair is not in TRANSITIONS, or the action is unknown."""


class UnknownItem(LookupError):
    """No work item has this id."""


# -------------------------------------------------------------------- reads

def load_item(conn: Connection, item_id: Any, *, lock: bool = False) -> Dict[str, Any]:
    """The work_item row, plus the history can() needs for separation of
    duties: `proposers` (everyone whose propose was allowed) and
    `answered_by` (everyone who answered a question on it)."""
    item_id = _as_id(item_id)
    row = conn.execute(text("SELECT * FROM work_item WHERE id = :id"
                            + (" FOR UPDATE" if lock else "")), {"id": item_id}).mappings().first()
    if row is None:
        raise UnknownItem("no work item %s" % item_id)
    item = dict(row)
    item["proposers"] = sorted(conn.execute(text("""
        SELECT DISTINCT actor_id FROM audit_event
         WHERE subject_type = 'work_item' AND subject_id = :sid
           AND action = 'propose' AND allowed
    """), {"sid": str(item_id)}).scalars())
    item["answered_by"] = sorted(conn.execute(text("""
        SELECT DISTINCT answered_by FROM question
         WHERE work_item_id = :id AND answered_by IS NOT NULL
    """), {"id": item_id}).scalars())
    return item


def allowed_actions(actor: Actor, item: Mapping) -> List[str]:
    """What this actor could do to this item right now: possible in the
    machine and allowed by can(). The UI draws exactly these buttons."""
    return [a for a in ACTIONS
            if (item.get("state"), a) in TRANSITIONS and can(actor, a, item)[0]]


# ------------------------------------------------------------------- writes

def create_item(conn: Connection, actor: Actor, *, kind: str, subject_type: str,
                subject_id: Any, title: str, entity_id: Optional[str] = None,
                region_id: Optional[str] = None, clinic_id: Optional[str] = None,
                period: Any = None, amount: Any = None,
                evidence: Optional[Mapping] = None) -> Dict[str, Any]:
    """Open a work item in NEW. Idempotent on (kind, subject_type, subject_id):
    running a month twice returns the existing rows and appends nothing."""
    initial = {
        "kind": _required(kind, "kind"), "subject_type": _required(subject_type, "subject_type"),
        "subject_id": _required(None if subject_id is None else str(subject_id), "subject_id"),
        "title": _required(title, "title"), "entity_id": entity_id, "region_id": region_id,
        "clinic_id": clinic_id, "period": _period(period), "amount": _amount(amount),
        "evidence": _mapping(evidence, "evidence") or {},
    }
    allowed, reason = can(actor, "create", initial)
    if not allowed:
        event = _record_denial(conn, actor, "create", "work_item", "new", "NEW", reason,
                               evidence={"item": _jsonable(initial)})
        raise Denied(reason, event)

    # Serialize creators of the same item, so two workers cannot both miss
    # the existing row and race to insert it.
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                 {"k": "work_item|%s|%s|%s" % (initial["kind"], initial["subject_type"],
                                               initial["subject_id"])})
    existing = conn.execute(text("""
        SELECT * FROM work_item WHERE kind = :kind AND subject_type = :st AND subject_id = :sid
    """), {"kind": initial["kind"], "st": initial["subject_type"],
           "sid": initial["subject_id"]}).mappings().first()
    if existing is not None:
        return dict(existing)

    item_id = conn.execute(text(
        "SELECT nextval(pg_get_serial_sequence('work_item', 'id'))")).scalar_one()
    diff = {"from": None, "to": "NEW", "set": initial}
    _append_and_project(conn, actor, "create", item_id, diff)
    return _row(conn, item_id)


def transition(conn: Connection, actor: Actor, item_id: Any, action: str, *,
               reason: Optional[str] = None, evidence: Optional[Mapping] = None,
               patch: Optional[Mapping] = None,
               policy_ref: Optional[str] = None) -> Dict[str, Any]:
    """Move one item by one action and return the projected work_item row.

    patch: columns from PATCHABLE to change alongside the move. For `ask` it
    also carries the question ({"asked_to", "body", "due_at"}; body defaults
    to reason); for `answer`, {"answer"} (defaults to reason).

    policy_ref: the approved policy that drove this decision, as
    `policy:<id>@v<version>` (work/policies.py); it goes on the event's
    policy_ref column.
    """
    if action not in ACTIONS:
        raise IllegalTransition("unknown action %r; the actions are %s" % (action, ", ".join(ACTIONS)))
    patch = dict(_mapping(patch, "patch") or {})
    evidence = _mapping(evidence, "evidence")

    item = load_item(conn, item_id, lock=True)
    state = item["state"]
    allowed, why = can(actor, action, item)
    if not allowed:
        event = _record_denial(conn, actor, action, "work_item", item["id"], state, why,
                               evidence=evidence)
        raise Denied(why, event)
    to = TRANSITIONS.get((state, action))
    if to is None:
        raise IllegalTransition("cannot %s an item in %s (item %s)" % (action, state, item["id"]))

    initial_modification_proposal = (
        item.get("kind") == "LEASE_MODIFICATION" and state == "NEW"
        and action == "propose" and actor.id == "agent:investigation"
    )
    if item.get("kind") == "LEASE_MODIFICATION" and patch \
            and not initial_modification_proposal:
        raise ValueError("a lease modification proposal is immutable after its initial propose")

    diff: Dict[str, Any] = {"from": state, "to": to}
    if action == "ask":
        diff["question"] = _new_question(conn, patch, reason)
    elif action == "answer":
        diff["question"] = _open_answer(conn, item["id"], patch, reason)
    unknown = set(patch) - PATCHABLE
    if unknown:
        raise ValueError("cannot patch %s; patchable columns are %s"
                         % (sorted(unknown), sorted(PATCHABLE)))

    changes = {k: _patch_value(k, v) for k, v in patch.items()}
    if action == "propose":
        changes["proposed_by"] = actor.id
    if action in _REASON_ON_ITEM and reason is not None:
        changes.setdefault("reason", reason)
    diff["set"] = changes
    # The snapshot: what the patched columns held before, for the timeline.
    if changes:
        diff["was"] = {k: item.get(k) for k in changes}
    if action == "approve" and item["subject_type"] == "lease_version":
        diff["confirms"] = {"lease_version_id": _as_id(item["subject_id"])}

    _append_and_project(conn, actor, action, item["id"], diff, reason=reason, evidence=evidence,
                        policy_ref=policy_ref)
    return _row(conn, item["id"])


def record_denial(conn: Connection, actor: Actor, action: str, item: Mapping, reason: str,
                  *, evidence: Optional[Mapping] = None) -> Event:
    """Put a refusal of `action` on `item` on record, the way transition()
    records can()'s, for a rule that lives above can() (work/charges.py's
    pay-as-billed override). The caller raises Denied with the event."""
    return _record_denial(conn, actor, action, "work_item", item["id"], item["state"], reason,
                          evidence=evidence)


# ------------------------------------------------------------------ helpers

def _append_and_project(conn: Connection, actor: Actor, action: str, item_id: int,
                        diff: Mapping, *, reason=None, evidence=None, policy_ref=None) -> Event:
    # Project exactly what was stored: the diff after its JSON round trip,
    # which is also what replay will read back.
    diff = _jsonable(diff)
    event = append_event(conn, actor_id=actor.id, action=action, subject_type="work_item",
                         subject_id=item_id, reason=reason, diff=diff, evidence=evidence,
                         policy_ref=policy_ref)
    apply(conn, project(event))
    # Queued for the live mirror (work/live.py), which sends only once this
    # transaction is seen committed; off, this is one `is None` test.
    live.stage(conn, item_id, actor.id)
    return event


def _record_denial(conn: Connection, actor: Actor, action: str, subject_type: str,
                   subject_id: Any, state: str, reason: str, evidence=None) -> Event:
    """Append the allowed = false event so that it outlives the caller.

    It goes on a fresh connection from the same engine (the same database
    role) and commits immediately. The exception: if the caller's transaction
    already appended an event, it holds the chain lock until it commits, and
    a second connection would wait on it forever. Then the denial is appended
    in the caller's transaction, and survives only if the caller commits.
    """
    fields = dict(actor_id=actor.id, action=action, subject_type=subject_type,
                  subject_id=subject_id, allowed=False, reason=reason,
                  diff={"from": state, "to": state, "set": {}}, evidence=_jsonable(evidence))
    if _holds_chain_lock(conn):
        return append_event(conn, **fields)
    with conn.engine.connect() as side:
        with side.begin():
            return append_event(side, **fields)


def _holds_chain_lock(conn: Connection) -> bool:
    return bool(conn.execute(text("""
        WITH k AS (SELECT hashtext(:key)::bigint AS h)
        SELECT EXISTS (
            SELECT 1 FROM pg_locks, k
             WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND granted
               AND objsubid = 1
               AND classid = ((h >> 32) & 4294967295)::oid
               AND objid = (h & 4294967295)::oid)
    """), {"key": _CHAIN_LOCK}).scalar_one())


def _new_question(conn: Connection, patch: Dict[str, Any], reason: Optional[str]) -> Dict:
    asked_to = patch.pop("asked_to", None)
    body = patch.pop("body", None) or reason
    due_at = patch.pop("due_at", None)
    if not isinstance(asked_to, str) or not asked_to:
        raise ValueError("ask needs patch['asked_to'], the actor the question is for")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("ask needs a question: patch['body'] or reason")
    question_id = conn.execute(text(
        "SELECT nextval(pg_get_serial_sequence('question', 'id'))")).scalar_one()
    return {"id": question_id, "asked_to": asked_to, "body": body, "due_at": due_at}


def _open_answer(conn: Connection, item_id: int, patch: Dict[str, Any],
                 reason: Optional[str]) -> Dict:
    answer = patch.pop("answer", None) or reason
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("answer needs patch['answer'] or reason")
    # NEEDS_INFO has exactly one open question: ask only leaves states that
    # have none, and answer is the only way out of NEEDS_INFO but hold.
    question_id = conn.execute(text("""
        SELECT id FROM question WHERE work_item_id = :id AND answered_by IS NULL
         ORDER BY id DESC LIMIT 1
    """), {"id": item_id}).scalar()
    if question_id is None:
        raise IllegalTransition("item %s has no open question to answer" % item_id)
    return {"id": question_id, "answer": answer}


def _row(conn: Connection, item_id: int) -> Dict[str, Any]:
    return dict(conn.execute(text("SELECT * FROM work_item WHERE id = :id"),
                             {"id": item_id}).mappings().one())


def _as_id(value: Any) -> int:
    if isinstance(value, bool):
        raise UnknownItem("not a work item id: %r" % (value,))
    try:
        return int(value)
    except (TypeError, ValueError):
        raise UnknownItem("not a work item id: %r" % (value,)) from None


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string, got %r" % (name, value))
    return value


def _mapping(value: Any, name: str) -> Optional[Mapping]:
    if value is not None and not isinstance(value, Mapping):
        raise ValueError("%s must be a mapping, got %r" % (name, type(value).__name__))
    return value


def _period(value: Any) -> Optional[date]:
    if value is None:
        return None
    try:
        period = value if isinstance(value, date) else date.fromisoformat(str(value))
    except ValueError:
        raise ValueError("period must be an ISO date, got %r" % (value,)) from None
    if period.day != 1:
        raise ValueError("period must be the first day of a month, got %s" % period)
    return period


def _amount(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, float):
        value = repr(value)   # 0.1, not 0.1000000000000000055511151231257827
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("amount must be a number, got %r" % (value,)) from None
    if not amount.is_finite():
        raise ValueError("amount must be finite, got %r" % (value,))
    return amount


def _patch_value(column: str, value: Any) -> Any:
    if column == "amount":
        return _amount(value)
    if column == "evidence":
        return dict(_mapping(value, "evidence") or {})
    if column == "title":
        return _required(value, "title")
    if value is not None and not isinstance(value, str):
        raise ValueError("%s must be a string, got %r" % (column, value))
    return value


def _jsonable(value: Any) -> Any:
    return None if value is None else json.loads(json.dumps(value, sort_keys=True, default=str))
