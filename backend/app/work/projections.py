"""From events to state: work_item, question and lease_version confirmations.

`project(event)` is a pure function. It reads one audit event and returns the
row changes it implies, without looking at the database. `apply()` writes
those changes. transition() calls both in the same transaction as the event,
and replay calls exactly the same two functions over the whole stream, so the
live state and the rebuilt state cannot be computed two different ways.

The event convention (the gateway follows it for `post` too):

    subject_type = 'work_item', subject_id = str(item id)
    action       = 'create' or one of the nine transitions
    diff         = {"from": state or null, "to": state, "set": {column: value}}
                   plus, for ask/answer, "question": {...}
                   and, for approving a lease_version item, "confirms": {"lease_version_id": n}

Values in a diff have been through JSON, so dates and money arrive as
strings. They are decoded here, once, for both paths.

An update only applies if the item is still in the state the event says it
came from. A history that disagrees with the state it is applied to is a bug
or tampering, and it fails loudly instead of being papered over.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Mapping

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from ..db import models as m

# Columns a diff's "set" may write. id, state, created_at, updated_at and
# last_event_seq come from the event itself and are never in "set".
WORK_ITEM_COLUMNS = frozenset({
    "kind", "subject_type", "subject_id", "entity_id", "region_id", "clinic_id",
    "period", "title", "amount", "proposal", "reason", "evidence", "proposed_by",
})

_DECODE: Dict[str, Callable[[Any], Any]] = {
    "period": date.fromisoformat,
    "amount": Decimal,
    "due_at": datetime.fromisoformat,
}

_TABLES = {"work_item": m.work_item, "question": m.question, "lease_version": m.lease_version}


class ProjectionError(ValueError):
    """An event cannot be projected: malformed, or it disagrees with the state."""


@dataclass(frozen=True)
class RowChange:
    table: str
    op: str                   # 'insert' or 'update'
    key: Mapping[str, Any]    # update: the WHERE, which must match exactly one row
    values: Mapping[str, Any]


def project(event) -> List[RowChange]:
    """The row changes one event implies. Denied attempts and events about
    other subjects change nothing."""
    if not event.allowed or event.subject_type != "work_item":
        return []
    diff = event.diff
    if not isinstance(diff, Mapping) or "to" not in diff:
        raise ProjectionError("event %s: work_item diff needs a 'to' state" % event.seq)
    item_id = _item_id(event)
    stamp = {"updated_at": event.at, "last_event_seq": event.seq}
    values = dict(_decode_set(event, diff.get("set") or {}), state=diff["to"], **stamp)

    if event.action == "create":
        values.setdefault("evidence", {})
        changes = [RowChange("work_item", "insert", {},
                             dict(values, id=item_id, created_at=event.at))]
    else:
        changes = [RowChange("work_item", "update",
                             {"id": item_id, "state": diff.get("from")}, values)]

    question = diff.get("question")
    if event.action == "ask":
        changes.append(_ask(event, item_id, question))
    elif event.action == "answer":
        changes.append(_answer(event, item_id, question))

    confirms = diff.get("confirms")
    if confirms is not None:
        changes.append(RowChange("lease_version", "update",
                                 {"id": _int(event, confirms.get("lease_version_id"))},
                                 {"confirmed_by": event.actor_id, "confirmed_at": event.at}))
    return changes


def apply(conn: Connection, changes: List[RowChange]) -> None:
    for change in changes:
        if change.op == "insert":
            _insert(conn, change)
        elif change.op == "update":
            _update(conn, change)
        else:
            raise ProjectionError("unknown row change %r" % change.op)


def apply_event(conn: Connection, event) -> None:
    apply(conn, project(event))


# ----------------------------------------------------------------- decoding

def _item_id(event) -> int:
    return _int(event, event.subject_id)


def _int(event, value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ProjectionError("event %s: %r is not an id" % (event.seq, value)) from None


def _decode_set(event, raw: Mapping[str, Any]) -> Dict[str, Any]:
    unknown = set(raw) - WORK_ITEM_COLUMNS
    if unknown:
        raise ProjectionError("event %s sets unknown columns %s" % (event.seq, sorted(unknown)))
    return {column: _decode(event, column, value) for column, value in raw.items()}


def _decode(event, column: str, value: Any) -> Any:
    if value is None or column not in _DECODE:
        return value
    try:
        return _DECODE[column](value)
    except (TypeError, ValueError, ArithmeticError):
        raise ProjectionError("event %s: bad %s %r" % (event.seq, column, value)) from None


def _ask(event, item_id: int, question) -> RowChange:
    if not isinstance(question, Mapping) or not question.get("body") or not question.get("asked_to"):
        raise ProjectionError("event %s: ask needs a question with asked_to and body" % event.seq)
    return RowChange("question", "insert", {}, {
        "id": _int(event, question.get("id")), "work_item_id": item_id,
        "asked_to": question["asked_to"], "asked_by": event.actor_id, "body": question["body"],
        "asked_at": event.at, "due_at": _decode(event, "due_at", question.get("due_at")),
    })


def _answer(event, item_id: int, question) -> RowChange:
    if not isinstance(question, Mapping) or not question.get("answer"):
        raise ProjectionError("event %s: answer needs a question with an answer" % event.seq)
    return RowChange(
        "question", "update",
        {"id": _int(event, question.get("id")), "work_item_id": item_id, "answered_by": None},
        {"answer": question["answer"], "answered_by": event.actor_id, "answered_at": event.at})


# ------------------------------------------------------------------ writing

def _columns(table: str, names) -> List[str]:
    known = _TABLES[table].c
    for name in names:
        if name not in known:
            raise ProjectionError("%s has no column %r" % (table, name))
    return list(names)


def _typed(sql: str, table: str, params: Mapping[str, Any], prefix: str = ""):
    """A text() statement whose binds carry the model's column types, so a
    dict becomes jsonb and a Decimal stays exact."""
    cols = _TABLES[table].c
    return text(sql).bindparams(*[
        bindparam(name, type_=cols[name[len(prefix):] if name.startswith(prefix) else name].type)
        for name in params])


def _insert(conn: Connection, change: RowChange) -> None:
    names = _columns(change.table, change.values)
    # OVERRIDING SYSTEM VALUE: the id comes from the event, so replay
    # recreates the row under the same id it had live.
    sql = "INSERT INTO %s (%s) OVERRIDING SYSTEM VALUE VALUES (%s)" % (
        change.table, ", ".join(names), ", ".join(":" + n for n in names))
    conn.execute(_typed(sql, change.table, change.values), dict(change.values))


def _update(conn: Connection, change: RowChange) -> None:
    names = _columns(change.table, change.values)
    keys = _columns(change.table, change.key)
    params = dict(change.values)
    where = []
    for k in keys:
        if change.key[k] is None:
            where.append("%s IS NULL" % k)
        else:
            where.append("%s = :k_%s" % (k, k))
            params["k_" + k] = change.key[k]
    sql = "UPDATE %s SET %s WHERE %s" % (
        change.table, ", ".join("%s = :%s" % (n, n) for n in names), " AND ".join(where))
    result = conn.execute(_typed(sql, change.table, params, prefix="k_"), params)
    if result.rowcount != 1:
        raise ProjectionError("%s %s: expected one row matching %s, found %d" % (
            change.table, change.op, json.dumps(dict(change.key), default=str), result.rowcount))
