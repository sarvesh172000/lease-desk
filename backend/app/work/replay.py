"""`make replay`: throw the work projections away and rebuild them from
audit_event.

If the events really are the source of truth, this must reproduce the live
state exactly, and it is the proof: replay() snapshots every projected row
as Postgres's own text form of the row, rebuilds, snapshots again and
compares. The text form is byte-exact: numeric scale, jsonb, timestamps.

What is rebuilt: work_item, question, and the lease_version confirmations
that events made. audit_event itself is never touched. Rows keep their ids
(projections insert with OVERRIDING SYSTEM VALUE), so journal entries that
point at work items still point at the same ones; their foreign key is
deferred to commit (migration 0003), which re-checks every one of them.

It runs as the database owner, in one transaction:

    python -m app.work.replay           rebuild, commit, report any difference
    python -m app.work.replay --check   rebuild, compare, always roll back;
                                        exit 1 if the rebuild would differ
"""

import argparse
import sys
from dataclasses import dataclass, field
from typing import Dict, List

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .events import Event
from .projections import apply, project

PROJECTIONS = ("work_item", "question")
_BATCH = 1000


@dataclass
class ReplayReport:
    events: int
    rows: Dict[str, int]
    differences: List[str] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        return not self.differences


def snapshot(conn: Connection) -> Dict[str, Dict[int, str]]:
    """Every projected row, as id -> the row's text. Confirmations only:
    lease_version rows themselves are drafts written by agents, not events."""
    shot = {table: dict(conn.execute(text(
        "SELECT id, t::text FROM %s t ORDER BY id" % table)).all()) for table in PROJECTIONS}
    shot["lease_version"] = dict(conn.execute(text("""
        SELECT id, row(confirmed_by, confirmed_at)::text FROM lease_version ORDER BY id
    """)).all())
    return shot


def rebuild(conn: Connection) -> int:
    """Delete the projections and re-apply every work_item event in order.
    Returns the number of events applied."""
    conn.execute(text("SET CONSTRAINTS journal_entry_work_item_id_fkey DEFERRED"))
    conn.execute(text("DELETE FROM question"))
    conn.execute(text("DELETE FROM work_item"))
    # Clear only the confirmations the history will set again; a version
    # confirmed some other way is not this history's to undo.
    conn.execute(text("""
        UPDATE lease_version SET confirmed_by = NULL, confirmed_at = NULL
         WHERE id IN (SELECT (diff->'confirms'->>'lease_version_id')::bigint
                        FROM audit_event
                       WHERE subject_type = 'work_item' AND allowed AND diff ? 'confirms')
    """))

    applied, after = 0, 0
    while True:
        rows = conn.execute(text("""
            SELECT * FROM audit_event
             WHERE seq > :after AND subject_type = 'work_item' AND allowed
             ORDER BY seq LIMIT :n
        """), {"after": after, "n": _BATCH}).mappings().all()
        if not rows:
            break
        for row in rows:
            apply(conn, project(Event(**{k: row[k] for k in Event.__dataclass_fields__})))
            applied += 1
        after = rows[-1]["seq"]

    for table in PROJECTIONS:
        _catch_up_identity(conn, table)
    return applied


def replay(conn: Connection) -> ReplayReport:
    """Rebuild in the caller's transaction and say how it compares to what
    was there. The caller decides whether to commit."""
    before = snapshot(conn)
    events = rebuild(conn)
    after = snapshot(conn)
    report = ReplayReport(events=events, rows={t: len(after[t]) for t in PROJECTIONS})
    for table in before:
        for row_id in sorted(set(before[table]) | set(after[table])):
            was, now = before[table].get(row_id), after[table].get(row_id)
            if was != now:
                report.differences.append("%s %s: live %s, rebuilt %s" % (table, row_id, was, now))
    return report


def _catch_up_identity(conn: Connection, table: str) -> None:
    """Rows were inserted with explicit ids, which a sequence does not see.
    Move it past the highest id if it is behind (a fresh database restored
    from events); never move it back, so no id is ever handed out twice."""
    top = conn.execute(text("SELECT max(id) FROM %s" % table)).scalar()
    if top is None:
        return
    seq = conn.execute(text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": table}).scalar_one()
    last, called = conn.execute(text("SELECT last_value, is_called FROM %s" % seq)).one()
    issued = last if called else last - 1
    if top > issued:
        conn.execute(text("SELECT setval(:s, :v)"), {"s": seq, "v": top})


def main(argv=None) -> int:
    from ..db.engine import engine

    parser = argparse.ArgumentParser(prog="replay", description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="compare only; roll back whatever the rebuild did")
    args = parser.parse_args(argv)

    with engine("owner").connect() as conn:
        with conn.begin() as tx:
            report = replay(conn)
            if args.check:
                tx.rollback()
    print("replayed %d events into %s" % (report.events, ", ".join(
        "%d %s rows" % (n, t) for t, n in report.rows.items())))
    if report.identical:
        print("rebuilt state is identical to the live state")
        return 0
    print("rebuilt state differs from the live state in %d rows%s:" % (
        len(report.differences), " (rolled back)" if args.check else " (rebuilt state kept)"))
    for line in report.differences[:50]:
        print("  " + line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
