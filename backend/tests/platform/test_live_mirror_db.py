"""work/live.py against Postgres: transition() is mirrored to SpacetimeDB only
after its transaction commits, with the figures GET /api/exceptions shows,
and a SpacetimeDB that is down never touches the approval.

SpacetimeDB is an httpx.MockTransport; the xid check and the committed read
are the real ones, through each actor's real database role.

Each send reads the item's row as committed at that moment, so the mirror
always converges on Postgres; upsert_status makes repeats harmless.
"""

import json

import httpx
import pytest
from work_world import ACTORS, bay_item, engine_for, world_fixture  # noqa: F401  (the `world` fixture)

from app.work import live
from app.work.transitions import create_item, load_item, transition

A = ACTORS
EVIDENCE = {"lease_id": "LEASE-01", "charge_type": "cam_estimate",
            "billed": 6458.33, "supported": 5941.67}


class SpacetimeStub:
    """What SpacetimeDB received: the upsert_status calls, as JSON arrays."""

    def __init__(self):
        self.calls = []
        self.fail = False
        self.mirror = live.Mirror("http://spacetime.test", "leasedesk-live", "tok",
                                  httpx.Client(transport=httpx.MockTransport(self.handle)))

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            raise httpx.ConnectError("spacetimedb is down")
        assert request.url.path == "/v1/database/leasedesk-live/call/upsert_status"
        self.calls.append(json.loads(request.content))
        return httpx.Response(200)

    def drained(self):
        assert self.mirror.flush()
        return self.calls


@pytest.fixture
def st():
    stub = SpacetimeStub()
    token = live.use(stub.mirror)
    yield stub
    live.reset(token)
    stub.mirror.close()


def create(engines, **overrides):
    with engine_for(engines, A["agent:checker"]).begin() as conn:
        return create_item(conn, A["agent:checker"], **bay_item(evidence=EVIDENCE, **overrides))


def act(engines, actor, item_id, action, **kwargs):
    with engine_for(engines, A[actor]).begin() as conn:
        return transition(conn, A[actor], item_id, action, **kwargs)


def row(item_id, status, by):
    return ["exc_%d" % item_id, "LEASE-01", "cam_estimate", 6458.33, 5941.67, status, by]


def test_each_committed_step_is_mirrored_with_the_api_figures(world, st):
    item = create(world)
    assert st.drained()[-1] == row(item["id"], "exception", "agent:checker")
    act(world, "agent:checker", item["id"], "propose", patch={"proposal": "hold"})
    assert st.drained()[-1] == row(item["id"], "pending_review", "agent:checker")
    act(world, "RM-BAY", item["id"], "approve")
    assert st.drained()[-1] == row(item["id"], "balanced", "RM-BAY")
    act(world, "system:gateway", item["id"], "post", evidence={"journal_entry_id": 1})
    assert st.drained()[-1] == row(item["id"], "balanced", "system:gateway")
    assert len(st.calls) == 4 and st.mirror.failures == 0


def test_a_burst_ends_on_the_latest_committed_state(world, st):
    """Each send reads the row as committed *now*, so a backlog can repeat the
    newest state but never finish on an older one."""
    item = create(world)
    act(world, "agent:checker", item["id"], "propose", patch={"proposal": "hold"})
    act(world, "RM-BAY", item["id"], "approve")
    calls = st.drained()
    assert len(calls) == 3
    assert calls[-1] == row(item["id"], "balanced", "RM-BAY")


def test_nothing_is_sent_before_commit(world, st):
    item = create(world)
    st.drained().clear()
    with world["lease_api"].connect() as conn:
        tx = conn.begin()
        transition(conn, A["RM-BAY"], item["id"], "hold", reason="ask the landlord")
        assert not st.mirror.flush(0.3)     # waiting on the open transaction
        assert st.calls == []
        tx.commit()
    assert st.drained() == [row(item["id"], "escalated", "RM-BAY")]


def test_a_rolled_back_transition_is_never_mirrored(world, st):
    item = create(world)
    st.drained().clear()
    with world["lease_api"].connect() as conn:
        tx = conn.begin()
        transition(conn, A["RM-BAY"], item["id"], "hold", reason="changed my mind")
        tx.rollback()
    assert st.drained() == []


def test_spacetimedb_down_never_fails_or_rolls_back_an_approval(world, st):
    st.fail = True
    item = create(world)
    act(world, "agent:checker", item["id"], "propose", patch={"proposal": "hold"})
    assert act(world, "RM-BAY", item["id"], "approve")["state"] == "APPROVED"
    assert st.drained() == [] and st.mirror.failures == 3
    with world["lease_reader"].connect() as conn:
        assert load_item(conn, item["id"])["state"] == "APPROVED"
    st.fail = False                          # and it carries on with the next change
    act(world, "system:gateway", item["id"], "post", evidence={"journal_entry_id": 1})
    assert st.drained() == [row(item["id"], "balanced", "system:gateway")]


def test_items_other_than_charge_checks_are_not_mirrored(world, st):
    item = create(world, kind="PAYMENT_RELEASE", subject_id="chg-2")
    act(world, "agent:checker", item["id"], "propose")
    assert st.drained() == []
