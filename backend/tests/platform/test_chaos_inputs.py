"""Chaos on the inputs: the same sync file delivered twice (one after the
other, and two at once), and jobs and events arriving out of order. Each run
must end in exactly the state an orderly run ends in: no duplicate rows,
items, entries, outbox rows or events; the chain verifies; replay equals live.
"""

import threading

import lease_world as lw
import pytest
from sqlalchemy import text

from app.jobs.monthly import run_month
from app.jobs.queue import enqueue
from app.jobs.worker import drain
from app.records.ingest import ingest_all
from app.work.confirm_leases import confirm_all
from app.work.gateway import GatewayError, post_approved, release_batch, send_outbox
from app.work.roles import load_actor
from app.work.transitions import IllegalTransition, transition
from ops.chaos import harness as h
from ops.chaos.faults import deliver_sync_twice

COMPARED = ("lease_version", "lease_term", "agent_run", "work_item", "question",
            "journal_entry", "journal_line", "outbox", "sync_cursor", "audit_event")


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    return h.generate(tmp_path_factory.mktemp("generated"))


@pytest.fixture
def seeded(clean, generated, monkeypatch):
    h.seed_db(clean, generated)
    lw.use_documents(monkeypatch, generated)
    return clean


def worker(eng):
    return lambda step: drain(eng["lease_agent"], "w")


def compared(eng):
    state = h.canonical_state(eng)
    return {k: state[k] for k in COMPARED}


def reset(eng, generated):
    h.truncate_all(eng)
    h.seed_db(eng, generated)


def footprint(eng):
    with eng["lease_reader"].connect() as conn:
        return {t: conn.execute(text("SELECT count(*) FROM %s" % t)).scalar()
                for t in ("source_document", "raw_row", "landlord_charge", "payment", "work_item",
                          "journal_entry", "outbox", "audit_event", "job")}


# ------------------------------------------------------------ duplicate sync

def test_the_same_sync_file_twice_adds_nothing_and_changes_no_result(seeded, generated, tmp_path):
    eng = seeded
    h.january(eng, worker(eng), tmp_path / "a")
    reference = compared(eng)
    before = footprint(eng)

    first, second = deliver_sync_twice(eng["lease_agent"], generated)   # re-delivered, twice
    assert first.rows == second.rows > 0
    counts = h.seed_db(eng, generated)                                  # and standardized again
    assert {name: c["added"] for name, c in counts.items()} == {name: 0 for name in counts}
    h.january(eng, worker(eng), tmp_path / "a")
    assert footprint(eng) == before
    assert compared(eng) == reference


def test_two_deliveries_of_the_same_file_at_once_store_it_once(seeded, generated):
    before = footprint(seeded)
    errors, barrier = [], threading.Barrier(2)

    def deliver():
        try:
            with seeded["lease_agent"].begin() as conn:
                barrier.wait(5)
                ingest_all(conn, generated)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=deliver) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert errors == []
    assert footprint(seeded) == before


# --------------------------------------------------------------- out of order

def test_jobs_and_events_out_of_order_end_where_an_orderly_month_ends(seeded, generated,
                                                                      tmp_path):
    eng = seeded
    h.january(eng, worker(eng), tmp_path / "orderly")
    orderly = compared(eng)

    reset(eng, generated)
    agent, api, gw = eng["lease_agent"], eng["lease_api"], eng["lease_gateway"]

    # A checking job arrives before the month (no dependencies): it runs
    # first, finds nothing confirmed, proposes nothing.
    with agent.begin() as conn:
        enqueue(conn, "checking", {"entity_id": h.ENTITY, "period": h.JAN.isoformat()},
                idempotency_key="stray:checking")
    [stray] = drain(agent, "w")
    assert (stray.status, stray.result["created"], stray.result["waiting"]) == ("done", 0, 12)

    # The gateway and the clerk are early: nothing approved, nothing to post,
    # release or send.
    with gw.begin() as conn:
        assert post_approved(conn, h.ENTITY, h.JAN) == []
        with pytest.raises(GatewayError, match="nothing to release"):
            release_batch(conn, h.JAN, h.AP, entity_id=h.ENTITY)
    with gw.connect() as conn:
        assert send_outbox(conn, tmp_path / "early") == []

    # The month is requested twice, from two places at once.
    def request():
        with agent.begin() as conn:
            run_month(conn, h.ENTITY, h.JAN)
    threads = [threading.Thread(target=request) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    drain(agent, "w")

    # Confirmations delivered twice; an approve replayed on a confirmed item.
    for _ in range(2):
        with api.begin() as conn:
            confirm_all(conn, load_actor(conn, h.RM_BAY), h.ENTITY)
    with api.connect() as conn:
        some = conn.execute(text("SELECT id FROM work_item WHERE kind = 'LEASE_ABSTRACTION' "
                                 "ORDER BY id LIMIT 1")).scalar_one()
    with pytest.raises(IllegalTransition):
        with api.begin() as conn:
            transition(conn, load_actor(conn, h.RM_BAY), some, "approve")

    h.enqueue_month(eng)
    drain(agent, "w")
    h.approve_all(eng)
    with api.connect() as conn:
        one = conn.execute(text("SELECT id FROM work_item WHERE kind = 'CHARGE_CHECK' "
                                "ORDER BY id LIMIT 1")).scalar_one()
    with pytest.raises(IllegalTransition):                   # the same approval, again
        with api.begin() as conn:
            transition(conn, load_actor(conn, h.RM_BAY), one, "approve")

    # The clerk releases before the gateway posts; then it posts, twice.
    with gw.begin() as conn:
        assert release_batch(conn, h.JAN, h.AP, entity_id=h.ENTITY).created
    for _ in range(2):
        with gw.begin() as conn:
            post_approved(conn, h.ENTITY, h.JAN)
    with gw.connect() as conn:
        assert len(send_outbox(conn, tmp_path / "late")) == 1
        assert send_outbox(conn, tmp_path / "late") == []

    shuffled = compared(eng)
    assert h.differences(orderly, shuffled) == []
    check = h.integrity(eng)
    assert check["chain"] and check["replay_identical"] and check["tb_balanced"]
