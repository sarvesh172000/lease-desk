"""Judge-provided input: how scenario-studio events are marked, and found.

PHASE_3.md group 3: "Studio inputs are tagged as judge-provided in the audit
stream and cleared by demo reset." Every event the studio causes carries
`{"judge_provided": true}` in its evidence, so the audit timeline can badge
it and anyone can tell a judge's invoice from the generated company's:

    from app.demo.judge import judge_evidence, append_judge_event

    transition(conn, actor, item_id, "hold", reason=..., evidence=judge_evidence({"upload": sha}))
    create_item(conn, agent, ..., evidence=judge_evidence({...}))      # lands in the create diff
    append_judge_event(conn, actor_id=..., action="studio_upload", subject_type="source_document",
                       subject_id=doc_id, evidence={"filename": name})

Clearing needs no code of its own: the demo snapshot is taken before any
judge touches anything, so `make demo-reset` / POST /api/demo/reset put back
a stream with none of these events (reset.py reports how many it cleared).
"""

from typing import Any, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..work.events import Event, append_event

JUDGE_KEY = "judge_provided"

# An event is judge-provided when its own evidence says so, or when it created
# a work item whose evidence says so (create_item's event carries the item's
# evidence in diff.set rather than in the evidence column).
JUDGE_PROVIDED_SQL = (
    "(evidence @> '{\"judge_provided\": true}'::jsonb"
    " OR diff -> 'set' -> 'evidence' @> '{\"judge_provided\": true}'::jsonb)"
)


def judge_evidence(evidence: Optional[Mapping[str, Any]] = None) -> dict:
    """`evidence` (or {}) with judge_provided set; never mutates the argument."""
    tagged = dict(evidence or {})
    tagged[JUDGE_KEY] = True
    return tagged


def is_judge_provided(evidence: Optional[Mapping[str, Any]]) -> bool:
    return bool(evidence) and evidence.get(JUDGE_KEY) is True


def append_judge_event(conn: Connection, **fields: Any) -> Event:
    """append_event() with the evidence tagged judge-provided."""
    fields["evidence"] = judge_evidence(fields.get("evidence"))
    return append_event(conn, **fields)


def count_judge_provided(conn: Connection) -> int:
    return conn.execute(text("SELECT count(*) FROM audit_event WHERE " + JUDGE_PROVIDED_SQL)).scalar_one()
