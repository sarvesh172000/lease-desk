"""work/transitions.py: the state machine, transition(), create_item().

Every action runs through the database role its real caller uses (agents on
lease_agent, people on lease_api, the gateway on lease_gateway), so a missing
grant fails here before it fails in the demo.
"""

from decimal import Decimal

import pytest
from sqlalchemy import text
from work_world import ACTORS, bay_item, engine_for, world_fixture  # noqa: F401  (the `world` fixture)

from app.db.models import WORK_STATES
from app.work.events import events_for, verify_chain
from app.work.transitions import (
    ACTIONS,
    TRANSITIONS,
    Denied,
    IllegalTransition,
    UnknownItem,
    allowed_actions,
    create_item,
    load_item,
    transition,
)

A = ACTORS


def create(engines, actor="agent:checker", **overrides):
    with engine_for(engines, A[actor]).begin() as conn:
        return create_item(conn, A[actor], **bay_item(**overrides))


def act(engines, actor, item_id, action, **kwargs):
    with engine_for(engines, A[actor]).begin() as conn:
        return transition(conn, A[actor], item_id, action, **kwargs)


def timeline(engines, item_id):
    with engines["lease_reader"].connect() as conn:
        return events_for(conn, "work_item", item_id)


# ------------------------------------------------------------- the machine

def test_the_machine_uses_only_the_frozen_states_and_actions():
    assert {s for pair in TRANSITIONS for s in (pair[0], TRANSITIONS[pair])} <= set(WORK_STATES)
    assert {action for _, action in TRANSITIONS} == set(ACTIONS)
    assert len(ACTIONS) == 9
    assert not [pair for pair in TRANSITIONS if pair[0] == "CLOSED"]   # terminal


def test_only_post_reaches_posted_and_only_approve_reaches_approved():
    assert {a for (_, a), to in TRANSITIONS.items() if to == "POSTED"} == {"post"}
    assert {a for (_, a), to in TRANSITIONS.items() if to == "APPROVED"} == {"approve"}
    assert {s for (s, a) in TRANSITIONS if a == "post"} == {"APPROVED"}


# ---------------------------------------------------------------- create

def test_create_opens_a_new_item_and_records_every_initial_column(world):
    item = create(world)
    assert item["state"] == "NEW"
    assert item["amount"] == Decimal("12500.00")
    assert str(item["period"]) == "2026-01-01"
    assert item["evidence"] == {"invoice": "inv-1", "page": 1}
    [event] = timeline(world, item["id"])
    assert event.action == "create" and event.actor_id == "agent:checker"
    assert event.diff["from"] is None and event.diff["to"] == "NEW"
    assert event.diff["set"]["subject_id"] == "chg-1"
    assert event.diff["set"]["amount"] == "12500.00"
    assert item["last_event_seq"] == event.seq and item["created_at"] == event.at


def test_create_is_idempotent(world):
    first = create(world)
    again = create(world, title="a different title the second time")
    assert again == first
    assert len(timeline(world, first["id"])) == 1
    with world["owner"].connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM work_item")).scalar_one() == 1


def test_a_person_cannot_create_work_and_the_attempt_is_recorded(world):
    with pytest.raises(Denied):
        create(world, actor="RM-BAY")
    with world["owner"].connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM work_item")).scalar_one() == 0
        denied = conn.execute(text(
            "SELECT actor_id, action, allowed FROM audit_event")).one()
    assert tuple(denied) == ("RM-BAY", "create", False)


@pytest.mark.parametrize("bad", [
    {"kind": ""}, {"title": None}, {"subject_id": None}, {"subject_type": " "},
    {"period": "2026-01-15"}, {"period": "January"}, {"amount": "twelve"},
    {"amount": "NaN"}, {"evidence": ["not", "a", "mapping"]},
])
def test_create_rejects_bad_input_before_writing_anything(world, bad):
    with pytest.raises(ValueError):
        create(world, **bad)
    with world["owner"].connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_event")).scalar_one() == 0


# ------------------------------------------------------------ transitions

def test_the_happy_path_from_proposal_to_close(world):
    item = create(world)
    proposed = act(world, "agent:checker", item["id"], "propose", reason="matches the lease",
                   patch={"proposal": "approve"})
    assert proposed["state"] == "PROPOSED"
    assert proposed["proposed_by"] == "agent:checker"
    assert proposed["proposal"] == "approve" and proposed["reason"] == "matches the lease"
    assert act(world, "RM-BAY", item["id"], "approve")["state"] == "APPROVED"
    posted = act(world, "system:gateway", item["id"], "post", evidence={"journal_entry_id": 1})
    assert posted["state"] == "POSTED"
    assert posted["reason"] == "matches the lease"         # post changes state only
    assert act(world, "CTRL", item["id"], "close")["state"] == "CLOSED"

    events = timeline(world, item["id"])
    assert [e.action for e in events] == ["create", "propose", "approve", "post", "close"]
    assert [(e.diff["from"], e.diff["to"]) for e in events[1:]] == [
        ("NEW", "PROPOSED"), ("PROPOSED", "APPROVED"), ("APPROVED", "POSTED"),
        ("POSTED", "CLOSED")]
    assert events[3].evidence == {"journal_entry_id": 1}
    with world["lease_reader"].connect() as conn:
        assert verify_chain(conn) is None
        assert load_item(conn, item["id"])["last_event_seq"] == events[-1].seq


def test_denied_attempt_is_recorded_and_survives_the_callers_rollback(world):
    """The acceptance demo: the Bay Area manager approves a Desert item."""
    item = create(world, region_id="REG-DESERT")
    act(world, "agent:checker", item["id"], "propose")
    with pytest.raises(Denied) as info:
        act(world, "RM-BAY", item["id"], "approve")      # the `with` rolls back
    assert "region REG-DESERT" in info.value.reason
    last = timeline(world, item["id"])[-1]
    assert (last.actor_id, last.action, last.allowed) == ("RM-BAY", "approve", False)
    assert last.diff == {"from": "PROPOSED", "to": "PROPOSED", "set": {}}
    assert last.reason == info.value.reason
    assert info.value.event.seq == last.seq
    with world["lease_reader"].connect() as conn:
        assert load_item(conn, item["id"])["state"] == "PROPOSED"
        assert verify_chain(conn) is None


def test_a_denial_inside_a_transaction_that_already_wrote_an_event(world):
    """The caller holds the chain lock, so the denial goes in its own
    transaction instead of deadlocking on a second connection."""
    with world["lease_agent"].begin() as conn:
        item = create_item(conn, A["agent:checker"], **bay_item())
        with pytest.raises(Denied):
            transition(conn, A["agent:checker"], item["id"], "approve")
    actions = [(e.action, e.allowed) for e in timeline(world, item["id"])]
    assert actions == [("create", True), ("approve", False)]


def test_nobody_approves_their_own_proposal(world):
    item = create(world, kind="PAYMENT_RELEASE")
    act(world, "agent:checker", item["id"], "propose")
    # Only agents propose and agents never approve, so this rule is defence
    # in depth. Plant a person as the proposer to show it still holds.
    with world["owner"].begin() as conn:
        conn.execute(text("UPDATE work_item SET proposed_by = 'CTRL' WHERE id = :i"),
                     {"i": item["id"]})
    with pytest.raises(Denied, match="separation of duties"):
        act(world, "CTRL", item["id"], "approve")


def test_nobody_approves_after_answering_the_question(world):
    item = create(world)
    act(world, "agent:checker", item["id"], "ask", patch={"asked_to": "RM-BAY",
                                                          "body": "Did suite 100 move?"})
    answered = act(world, "RM-BAY", item["id"], "answer", patch={"answer": "No, same suite"})
    assert answered["state"] == "PROPOSED"
    with pytest.raises(Denied, match="answered"):
        act(world, "RM-BAY", item["id"], "approve")
    assert act(world, "CTRL", item["id"], "approve")["state"] == "APPROVED"


def test_ask_and_answer_project_the_question(world):
    item = create(world)
    act(world, "agent:checker", item["id"], "ask", reason="Is the escalation simple?",
        patch={"asked_to": "RM-BAY", "due_at": "2026-02-05T17:00:00+00:00"})
    with world["lease_reader"].connect() as conn:
        q = conn.execute(text("SELECT * FROM question")).mappings().one()
    assert (q["work_item_id"], q["asked_to"], q["asked_by"]) == (item["id"], "RM-BAY",
                                                                 "agent:checker")
    assert q["body"] == "Is the escalation simple?" and q["answer"] is None
    assert q["due_at"].isoformat() == "2026-02-05T17:00:00+00:00"
    act(world, "RM-BAY", item["id"], "answer", reason="Simple, 3% a year")
    with world["lease_reader"].connect() as conn:
        q = conn.execute(text("SELECT * FROM question")).mappings().one()
    assert (q["answer"], q["answered_by"]) == ("Simple, 3% a year", "RM-BAY")
    assert q["answered_at"] is not None


@pytest.mark.parametrize("patch", [{}, {"asked_to": "RM-BAY"}, {"body": "who?"}])
def test_ask_needs_a_recipient_and_a_body(world, patch):
    item = create(world)
    with pytest.raises(ValueError):
        act(world, "agent:checker", item["id"], "ask", patch=patch)


def test_answer_needs_an_answer(world):
    item = create(world)
    act(world, "agent:checker", item["id"], "ask", patch={"asked_to": "RM-BAY", "body": "?"})
    with pytest.raises(ValueError):
        act(world, "RM-BAY", item["id"], "answer")


def test_illegal_transitions_are_impossible_and_write_nothing(world):
    item = create(world)
    with pytest.raises(IllegalTransition, match="cannot approve an item in NEW"):
        act(world, "RM-BAY", item["id"], "approve")
    with pytest.raises(IllegalTransition, match="cannot post"):
        act(world, "system:gateway", item["id"], "post")
    with pytest.raises(IllegalTransition, match="cannot answer"):
        act(world, "RM-BAY", item["id"], "answer", patch={"answer": "x"})
    assert len(timeline(world, item["id"])) == 1


@pytest.mark.parametrize("action", ["delete", "create", "APPROVE", "", None])
def test_unknown_actions_are_illegal(world, action):
    item = create(world)
    with pytest.raises(IllegalTransition):
        act(world, "CTRL", item["id"], action)


@pytest.mark.parametrize("item_id", [999999, "abc", None, True, -1])
def test_unknown_items(world, item_id):
    with pytest.raises(UnknownItem):
        act(world, "CTRL", item_id, "approve")


def test_only_the_gateway_posts(world):
    item = create(world)
    act(world, "agent:checker", item["id"], "propose")
    act(world, "RM-BAY", item["id"], "approve")
    for actor in ("CTRL", "RM-BAY", "agent:checker", "AP", "AUD"):
        with pytest.raises(Denied):
            act(world, actor, item["id"], "post")
    assert act(world, "system:gateway", item["id"], "post")["state"] == "POSTED"


def test_the_auditor_never_writes(world):
    item = create(world)
    for action in ("propose", "hold", "ask"):
        with pytest.raises(Denied):
            act(world, "AUD", item["id"], action)


def test_patch_changes_only_patchable_columns(world):
    item = create(world)
    proposed = act(world, "agent:checker", item["id"], "propose",
                   patch={"amount": "13000.5", "evidence": {"calc": "12500 * 1.04"}})
    assert proposed["amount"] == Decimal("13000.50")
    assert proposed["evidence"] == {"calc": "12500 * 1.04"}
    event = timeline(world, item["id"])[-1]
    assert event.diff["was"]["amount"] == "12500.00"
    for bad in ({"state": "APPROVED"}, {"proposed_by": "someone"}, {"region_id": "REG-DESERT"},
                {"amount": "lots"}, {"title": ""}, {"proposal": 7}):
        with pytest.raises(ValueError):
            act(world, "agent:checker", item["id"], "propose", patch=bad)
    with pytest.raises(ValueError):
        act(world, "agent:checker", item["id"], "propose", patch=["not", "a", "mapping"])


def test_approving_a_lease_version_item_confirms_the_version(world):
    with world["owner"].begin() as conn:
        conn.execute(text("""
            INSERT INTO landlord (id, name) VALUES ('LL', 'Landlord');
            INSERT INTO center (id, name, landlord_id, total_rsf) VALUES ('CTR', 'C', 'LL', 1000);
            INSERT INTO clinic VALUES ('CL', 'Clinic', 'ENT-CA', 'REG-BAY', 'CTR', '100', 500);
            INSERT INTO lease (id, clinic_id, landlord_id) VALUES ('LS', 'CL', 'LL');
        """))
    with world["lease_agent"].begin() as conn:
        version_id = conn.execute(text("""
            INSERT INTO lease_version (lease_id, version, effective_from)
            VALUES ('LS', 1, '2024-01-01') RETURNING id""")).scalar_one()
    item = create(world, kind="LEASE_ABSTRACTION", subject_type="lease_version",
                  subject_id=version_id, clinic_id="CL", amount=None, period=None)
    act(world, "agent:abstraction", item["id"], "propose")
    approved = act(world, "RM-BAY", item["id"], "approve")
    with world["lease_reader"].connect() as conn:
        version = conn.execute(text("SELECT * FROM lease_version")).mappings().one()
    assert version["confirmed_by"] == "RM-BAY"
    assert version["confirmed_at"] == timeline(world, item["id"])[-1].at
    assert approved["state"] == "APPROVED"


def test_allowed_actions_matches_what_transition_will_do(world):
    item = create(world)
    with world["lease_api"].connect() as conn:
        assert allowed_actions(A["RM-BAY"], load_item(conn, item["id"])) == ["hold"]
        assert allowed_actions(A["AUD"], load_item(conn, item["id"])) == []
    act(world, "agent:checker", item["id"], "propose")
    with world["lease_api"].connect() as conn:
        loaded = load_item(conn, item["id"])
        assert loaded["proposers"] == ["agent:checker"]
        assert allowed_actions(A["RM-BAY"], loaded) == ["hold", "approve", "reject"]
        assert allowed_actions(A["RM-DESERT"], loaded) == []
        assert allowed_actions(A["agent:checker"], loaded) == ["propose", "ask", "hold"]
