"""work/projections.py: pure event -> row changes, and the applier that
refuses a history that disagrees with the state it is applied to."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from work_world import ACTORS, bay_item, world_fixture  # noqa: F401  (the `world` fixture)

from app.work.events import Event
from app.work.projections import ProjectionError, RowChange, apply, apply_event, project
from app.work.transitions import create_item, transition

AT = datetime(2026, 1, 31, 12, tzinfo=timezone.utc)


def event(action="propose", diff=None, seq=10, subject_id="7", allowed=True,
          subject_type="work_item", actor_id="agent:checker"):
    return Event(seq=seq, at=AT, actor_id=actor_id, action=action, subject_type=subject_type,
                 subject_id=subject_id, allowed=allowed, reason=None, diff=diff, evidence=None,
                 policy_ref=None, model_ref=None, prev_hash="0" * 64, hash="1" * 64)


def test_create_inserts_the_whole_row_with_decoded_values():
    [change] = project(event("create", {"from": None, "to": "NEW", "set": {
        "kind": "CHARGE_CHECK", "subject_type": "landlord_charge", "subject_id": "c",
        "title": "t", "period": "2026-01-01", "amount": "12.50", "evidence": {"a": 1}}}))
    assert change.table == "work_item" and change.op == "insert"
    assert change.values["id"] == 7 and change.values["state"] == "NEW"
    assert change.values["period"] == date(2026, 1, 1)
    assert change.values["amount"] == Decimal("12.50")
    assert change.values["created_at"] == change.values["updated_at"] == AT
    assert change.values["last_event_seq"] == 10


def test_a_transition_updates_only_from_the_state_it_names():
    [change] = project(event("hold", {"from": "PROPOSED", "to": "HELD", "set": {"reason": "r"}}))
    assert change.op == "update"
    assert change.key == {"id": 7, "state": "PROPOSED"}
    assert change.values == {"state": "HELD", "reason": "r", "updated_at": AT,
                             "last_event_seq": 10}


def test_ask_and_answer_carry_a_question():
    ask = project(event("ask", {"from": "NEW", "to": "NEEDS_INFO", "set": {},
                                "question": {"id": 3, "asked_to": "RM", "body": "?"}}))
    assert ask[1] == RowChange("question", "insert", {}, {
        "id": 3, "work_item_id": 7, "asked_to": "RM", "asked_by": "agent:checker",
        "body": "?", "asked_at": AT, "due_at": None})
    answer = project(event("answer", {"from": "NEEDS_INFO", "to": "PROPOSED", "set": {},
                                      "question": {"id": 3, "answer": "!"}}, actor_id="RM"))
    assert answer[1].key == {"id": 3, "work_item_id": 7, "answered_by": None}
    assert answer[1].values == {"answer": "!", "answered_by": "RM", "answered_at": AT}


@pytest.mark.parametrize("ev", [
    event(allowed=False, diff={"from": "NEW", "to": "NEW", "set": {}}),
    event(subject_type="journal_entry", diff={"anything": 1}),
])
def test_denials_and_other_subjects_change_nothing(ev):
    assert project(ev) == []


@pytest.mark.parametrize("ev", [
    event(diff=None),
    event(diff={"from": "NEW"}),
    event(diff={"from": "NEW", "to": "PROPOSED", "set": {"state": "POSTED"}}),
    event(diff={"from": "NEW", "to": "PROPOSED", "set": {"last_event_seq": 1}}),
    event(diff={"from": "NEW", "to": "PROPOSED", "set": {"amount": "lots"}}),
    event(diff={"from": "NEW", "to": "PROPOSED", "set": {"period": "soon"}}),
    event(diff={"from": "NEW", "to": "PROPOSED", "set": {}}, subject_id="seven"),
    event("ask", {"from": "NEW", "to": "NEEDS_INFO", "set": {}}),
    event("ask", {"from": "NEW", "to": "NEEDS_INFO", "set": {}, "question": {"id": 1}}),
    event("answer", {"from": "NEEDS_INFO", "to": "PROPOSED", "set": {}, "question": {"id": 1}}),
    event("approve", {"from": "PROPOSED", "to": "APPROVED", "set": {},
                      "confirms": {"lease_version_id": None}}),
])
def test_malformed_events_fail_loudly(ev):
    with pytest.raises(ProjectionError):
        project(ev)


def _item(world):
    with world["lease_agent"].begin() as conn:
        return create_item(conn, ACTORS["agent:checker"], **bay_item())


def test_an_event_from_the_wrong_state_does_not_apply(world):
    item = _item(world)
    stale = event("approve", {"from": "PROPOSED", "to": "APPROVED", "set": {}},
                  subject_id=str(item["id"]), seq=999)
    with world["lease_api"].begin() as conn:
        with pytest.raises(ProjectionError, match="expected one row"):
            apply_event(conn, stale)


def test_an_event_for_a_missing_item_does_not_apply(world):
    with world["lease_api"].begin() as conn:
        with pytest.raises(ProjectionError):
            apply_event(conn, event("hold", {"from": "NEW", "to": "HELD", "set": {}},
                                    subject_id="424242"))


def test_the_applier_refuses_unknown_tables_columns_and_ops(world):
    with world["lease_api"].begin() as conn:
        for change in (RowChange("work_item", "update", {"id": 1}, {"nonsense": 1}),
                       RowChange("work_item", "upsert", {}, {}),
                       RowChange("work_item", "update", {"no_such_key": 1}, {"title": "x"})):
            with pytest.raises(ProjectionError):
                apply(conn, [change])
        with pytest.raises(KeyError):
            apply(conn, [RowChange("journal_entry", "insert", {}, {"memo": "x"})])


def test_a_gateway_post_projects_within_the_gateways_column_grants(world):
    """lease_gateway may update only state, updated_at and last_event_seq on
    work_item; a post must touch nothing else."""
    item = _item(world)
    with world["lease_agent"].begin() as conn:
        transition(conn, ACTORS["agent:checker"], item["id"], "propose")
    with world["lease_api"].begin() as conn:
        transition(conn, ACTORS["RM-BAY"], item["id"], "approve")
    with world["lease_gateway"].begin() as conn:
        row = transition(conn, ACTORS["system:gateway"], item["id"], "post",
                         reason="posted as JE 1")
    assert row["state"] == "POSTED"
    with world["lease_reader"].connect() as conn:
        assert conn.execute(text("SELECT reason FROM work_item")).scalar_one() is None
