"""work/events.py: the Python face of the hash chain."""

from sqlalchemy import text

from app.db.bootstrap import execute_raw
from app.work.events import append_event, events_for, verify_chain


def test_append_returns_the_stored_chained_event(clean):
    with clean["lease_agent"].begin() as conn:
        first = append_event(conn, actor_id="agent:checker", action="propose",
                             subject_type="work_item", subject_id=7, diff={"state": "PROPOSED"})
        second = append_event(conn, actor_id="agent:checker", action="hold",
                              subject_type="work_item", subject_id=7)
    assert second.prev_hash == first.hash
    assert first.subject_id == "7"


def test_events_for_returns_one_subjects_timeline_in_order(clean):
    with clean["lease_api"].begin() as conn:
        for action in ("propose", "approve"):
            append_event(conn, actor_id="PER-RM-BAY", action=action,
                         subject_type="work_item", subject_id=1)
        append_event(conn, actor_id="PER-RM-BAY", action="propose",
                     subject_type="work_item", subject_id=2)
    with clean["lease_reader"].connect() as conn:
        timeline = events_for(conn, "work_item", 1)
    assert [e.action for e in timeline] == ["propose", "approve"]
    assert timeline[0].diff is None


def test_verify_chain_names_a_tampered_row(clean):
    with clean["lease_agent"].begin() as conn:
        events = [append_event(conn, actor_id="a", action="x", subject_type="t", subject_id=i)
                  for i in range(3)]
    with clean["lease_reader"].connect() as conn:
        assert verify_chain(conn) is None
    with clean["owner"].begin() as conn:
        execute_raw(conn, "ALTER TABLE audit_event DISABLE TRIGGER USER;"
                          "UPDATE audit_event SET allowed = false WHERE seq = %d;"
                          "ALTER TABLE audit_event ENABLE TRIGGER USER;" % events[1].seq)
    with clean["lease_reader"].connect() as conn:
        assert verify_chain(conn).seq == events[1].seq
