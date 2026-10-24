"""Property tests: random actors throwing random actions at random items.

Whatever they try, in whatever order, through their real database roles:
  - an item is only ever in one of the eight states, and only ever moves
    along an edge of TRANSITIONS;
  - nobody approves an item they proposed or answered a question on;
  - only the gateway posts;
  - every refusal is on the record;
  - the hash chain verifies afterwards, and replay rebuilds the same state.
"""

import itertools

from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from app.db.models import WORK_STATES
from app.work.events import events_for, verify_chain
from app.work.replay import replay
from app.work.roles import ROLES, Actor, can
from app.work.transitions import (
    ACTIONS, TRANSITIONS, Denied, IllegalTransition, create_item, transition,
)
from work_world import ACTORS, engine_for, world_fixture  # noqa: F401  (the `world` fixture)

SETTINGS = settings(max_examples=50, deadline=None, database=None,
                    suppress_health_check=[HealthCheck.too_slow])

# Pure noise rarely gets past PROPOSED. So a history is built from chunks:
# one thing the actor's role could plausibly do, one thing at all, or a run
# along the happy path (which may be cut short, or land on the wrong item).
_PLAUSIBLE = sorted((a, action) for a, actor in ACTORS.items()
                    for action in set().union(*ROLES[actor.role].values()) - {"create"})
_ANYTHING = sorted((a, action) for a in ACTORS for action in ACTIONS)
_HAPPY = [("agent:checker", "propose"), ("RM-BAY", "approve"), ("system:gateway", "post"),
          ("CTRL", "close")]
_chunk = st.one_of(
    st.sampled_from(_PLAUSIBLE).map(lambda s: [s]),
    st.sampled_from(_ANYTHING).map(lambda s: [s]),
    st.integers(1, len(_HAPPY)).map(lambda n: _HAPPY[:n]),
)
steps = st.lists(_chunk, min_size=1, max_size=10).map(lambda chunks: sum(chunks, []))
items = st.fixed_dictionaries({
    "kind": st.sampled_from(["CHARGE_CHECK", "CHARGE_CHECK", "PAYMENT_RELEASE"]),
    "region_id": st.sampled_from(["REG-BAY", "REG-BAY", "REG-DESERT"]),
    "entity_id": st.sampled_from(["ENT-CA", "ENT-CA", "ENT-NV"]),
})

_subjects = itertools.count()


def _extras(action):
    if action == "ask":
        return {"patch": {"asked_to": "RM-BAY", "body": "Which suite is this for?"}}
    if action == "answer":
        return {"patch": {"answer": "Suite 100"}}
    return {}


def test_random_histories_never_break_the_rules(world):
    @SETTINGS
    @given(item=items, history=steps)
    def run(item, history):
        agent = ACTORS["agent:checker"]
        with world["lease_agent"].begin() as conn:
            row = create_item(conn, agent, subject_type="landlord_charge",
                              subject_id="prop-%d" % next(_subjects), title="t", **item)
        item_id, state = row["id"], row["state"]
        proposers, answerers = set(), set()

        for actor_id, action in history:
            actor = ACTORS[actor_id]
            before = len(_timeline(world, item_id))
            try:
                with engine_for(world, actor).begin() as conn:
                    state_after = transition(conn, actor, item_id, action,
                                             **_extras(action))["state"]
            except Denied:
                last = _timeline(world, item_id)[-1]
                assert len(_timeline(world, item_id)) == before + 1
                assert (last.actor_id, last.action, last.allowed) == (actor_id, action, False)
                continue
            except IllegalTransition:
                assert (state, action) not in TRANSITIONS
                assert len(_timeline(world, item_id)) == before
                continue

            assert state_after in WORK_STATES
            assert state_after == TRANSITIONS[(state, action)]
            if action == "approve":
                assert actor_id not in proposers | answerers
            if action == "post":
                assert actor.role == "system"
            proposers |= {actor_id} if action == "propose" else set()
            answerers |= {actor_id} if action == "answer" else set()
            state = state_after
            event("reached %s" % state)

        with world["lease_reader"].connect() as conn:
            stored = conn.execute(text("SELECT state FROM work_item WHERE id = :i"),
                                  {"i": item_id}).scalar_one()
            assert stored == state
            assert verify_chain(conn) is None

    run()
    with world["owner"].connect() as conn:
        with conn.begin():
            report = replay(conn)
    assert report.identical, report.differences[:5]


def _timeline(engines, item_id):
    with engines["lease_reader"].connect() as conn:
        return events_for(conn, "work_item", item_id)


# ------------------------------------------------- can() on its own, faster

actors = st.builds(Actor, id=st.sampled_from(["A", "B", "C"]), role=st.sampled_from(sorted(ROLES)),
                   region_id=st.sampled_from([None, "R1", "R2"]),
                   entity_id=st.sampled_from([None, "E1", "E2"]))
bare_items = st.fixed_dictionaries({
    "kind": st.sampled_from(["CHARGE_CHECK", "PAYMENT_RELEASE", "LEASE_ABSTRACTION"]),
    "region_id": st.sampled_from([None, "R1", "R2"]),
    "entity_id": st.sampled_from([None, "E1", "E2"]),
    "proposed_by": st.sampled_from([None, "A", "B", "C"]),
    "proposers": st.lists(st.sampled_from(["A", "B", "C"]), max_size=3),
    "answered_by": st.lists(st.sampled_from(["A", "B", "C"]), max_size=3),
})


@settings(max_examples=500, deadline=None, database=None)
@given(actor=actors, action=st.sampled_from(ACTIONS + ("create",)), item=bare_items)
def test_can_never_breaks_scope_or_separation_of_duties(actor, action, item):
    allowed, reason = can(actor, action, item)
    assert isinstance(reason, str) and reason
    if not allowed:
        return
    if action == "approve":
        assert actor.id != item["proposed_by"]
        assert actor.id not in item["proposers"] and actor.id not in item["answered_by"]
    if action == "post":
        assert actor.role == "system"
    assert actor.role != "auditor"
    if actor.entity_id is not None:
        assert item["entity_id"] == actor.entity_id
    if actor.role == "regional_manager":
        assert item["region_id"] == actor.region_id
