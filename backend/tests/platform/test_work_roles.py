"""work/roles.py: the ROLES matrix, can(), and loading actors."""

import pytest
from sqlalchemy import text
from work_world import ACTORS, world_fixture  # noqa: F401  (the `world` fixture)

from app.db.models import ACTOR_ROLES
from app.work.roles import GATEWAY_ACTOR, ROLES, Actor, UnknownActor, can, load_actor

A = ACTORS
BAY = {"kind": "CHARGE_CHECK", "entity_id": "ENT-CA", "region_id": "REG-BAY",
       "proposed_by": "agent:checker"}


def test_every_actor_role_has_a_row_in_the_matrix():
    assert set(ROLES) == set(ACTOR_ROLES)


@pytest.mark.parametrize("actor,action", [
    ("agent:checker", "create"), ("agent:checker", "propose"), ("agent:checker", "ask"),
    ("agent:checker", "hold"),
    ("RM-BAY", "approve"), ("RM-BAY", "reject"), ("RM-BAY", "answer"), ("RM-BAY", "hold"),
    ("RM-BAY", "resume"),
    ("CTRL", "approve"), ("CTRL", "reject"), ("CTRL", "close"),
    ("system:gateway", "post"),
])
def test_the_matrix_allows(actor, action):
    assert can(A[actor], action, BAY) == (True, "allowed")


@pytest.mark.parametrize("actor,action", [
    ("agent:checker", "approve"), ("agent:checker", "post"), ("agent:checker", "close"),
    ("RM-BAY", "propose"), ("RM-BAY", "post"), ("RM-BAY", "close"), ("RM-BAY", "create"),
    ("CTRL", "post"), ("CTRL", "propose"),
    ("AP", "approve"),                                 # not a payment release
    ("system:gateway", "approve"), ("system:gateway", "create"),
] + [("AUD", a) for a in ("create", "propose", "ask", "answer", "hold", "resume",
                           "approve", "reject", "post", "close")])
def test_the_matrix_refuses(actor, action):
    allowed, reason = can(A[actor], action, BAY)
    assert not allowed
    assert "may not %s" % action in reason


def test_ap_clerk_acts_only_on_payment_release():
    release = dict(BAY, kind="PAYMENT_RELEASE")
    assert can(A["AP"], "approve", release)[0]
    assert not can(A["AP"], "reject", release)[0]
    assert not can(A["AP"], "hold", BAY)[0]


def test_regional_manager_is_confined_to_their_region():
    desert = dict(BAY, region_id="REG-DESERT")
    allowed, reason = can(A["RM-BAY"], "approve", desert)
    assert not allowed and "region REG-DESERT" in reason
    assert can(A["RM-DESERT"], "approve", desert)[0]
    assert not can(A["RM-BAY"], "approve", dict(BAY, region_id=None))[0]


def test_entity_scope():
    allowed, reason = can(A["CTRL-NV"], "approve", BAY)
    assert not allowed and "entity ENT-NV" in reason
    assert can(A["CTRL-NV"], "approve", dict(BAY, entity_id="ENT-NV"))[0]
    assert can(A["CTRL"], "approve", dict(BAY, entity_id="ENT-NV"))[0]   # None means all
    assert not can(A["CTRL-NV"], "approve", dict(BAY, entity_id=None))[0]


def test_nobody_approves_what_they_proposed():
    mine = dict(BAY, proposed_by="CTRL")
    allowed, reason = can(A["CTRL"], "approve", mine)
    assert not allowed and "separation of duties" in reason and "proposed" in reason
    # An earlier proposer still counts after someone else re-proposed.
    assert not can(A["CTRL"], "approve", dict(BAY, proposers=["CTRL", "agent:checker"]))[0]
    # Rejecting your own proposal is fine: it is not signing it off.
    assert can(A["CTRL"], "reject", mine)[0]


def test_nobody_approves_what_they_answered():
    answered = dict(BAY, answered_by=["RM-BAY"])
    allowed, reason = can(A["RM-BAY"], "approve", answered)
    assert not allowed and "answered" in reason
    assert can(A["CTRL"], "approve", answered)[0]


def test_unknown_role_and_unknown_action_are_refused():
    assert can(Actor("x", "intern", None, None), "approve", BAY) == (False, "unknown role 'intern'")
    assert not can(A["CTRL"], "delete", BAY)[0]
    assert not can(A["RM-BAY"], "approve", {})[0]   # no region on the item: not provably theirs


def test_load_actor_reads_scope_through_every_role(world):
    for role in ("lease_agent", "lease_api", "lease_gateway", "lease_reader"):
        with world[role].connect() as conn:
            assert load_actor(conn, "RM-BAY") == A["RM-BAY"]
            assert load_actor(conn, GATEWAY_ACTOR).role == "system"


@pytest.mark.parametrize("bad", ["nobody", "", None, 42])
def test_load_actor_refuses_unknown_ids(world, bad):
    with world["lease_api"].connect() as conn:
        with pytest.raises(UnknownActor):
            load_actor(conn, bad)


def test_an_inactive_actor_cannot_act(world):
    with world["owner"].begin() as conn:
        conn.execute(text("UPDATE actor SET active = false WHERE id = 'RM-BAY'"))
    with world["lease_api"].connect() as conn:
        with pytest.raises(UnknownActor):
            load_actor(conn, "RM-BAY")
