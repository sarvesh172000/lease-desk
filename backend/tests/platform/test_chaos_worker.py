"""Chaos on the worker itself: a worker that dies mid-job, a job that must
wait, a database connection lost mid-job, a database that goes away while
the worker serves (jobs/recovery.py, jobs/worker.py).

The database outage is simulated per connection, never by restarting the
shared Postgres: a backend is terminated with pg_terminate_backend (a role
may terminate its own sessions), or the worker talks to Postgres through
ops/chaos/faults.FlakyProxy, which can refuse and cut connections.
"""

import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text

from app.jobs import recovery, worker
from app.jobs.queue import MAX_ATTEMPTS, claim, enqueue
from app.jobs.recovery import JobHeld
from app.jobs.worker import drain, run_one, serve
from app.settings import get_settings
from ops.chaos.faults import FlakyProxy, terminate


@pytest.fixture
def agent(clean):
    return clean["lease_agent"]


def add(agent, kind, payload=None, **kwargs):
    with agent.begin() as conn:
        return enqueue(conn, kind, payload or {}, **kwargs)


def q(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def job(eng, job_id):
    with eng.connect() as conn:
        return conn.execute(text("SELECT * FROM job WHERE id = :i"), {"i": job_id}).mappings().one()


def write(conn, payload):
    conn.execute(text("INSERT INTO sync_cursor (source, cursor) VALUES (:s, 'x')"),
                 {"s": payload["name"]})
    return {"wrote": payload["name"]}


def claim_like_a_worker(agent):
    """What run_one does before the handler: claim and take the liveness
    lock in one transaction, on a connection that stays open."""
    conn = agent.connect()
    with conn.begin():
        claimed = claim(conn, "doomed:1")
        recovery.hold_liveness(conn, claimed.id)
    pid = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
    conn.commit()
    return conn, claimed, pid


def kill_backend(agent, pid):
    with agent.connect() as conn:
        assert terminate(conn, pid)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with agent.connect() as conn:
            if not conn.execute(text("SELECT 1 FROM pg_stat_activity WHERE pid = :p"),
                                {"p": pid}).first():
                return
        time.sleep(0.02)
    raise AssertionError("backend %d did not go" % pid)


# ------------------------------------------------------------- recovery

def test_a_job_whose_worker_died_is_put_back_at_once_and_then_finishes(agent):
    job_id = add(agent, "write", {"name": "resumed"})
    conn, claimed, pid = claim_like_a_worker(agent)
    kill_backend(agent, pid)                      # the worker's connection is gone
    conn.invalidate()

    with agent.begin() as c:
        assert recovery.recover(c) == [job_id]
    row = job(agent, job_id)
    assert (row["status"], row["attempts"], row["locked_by"]) == ("failed", 1, None)
    assert "doomed:1 died mid-run" in row["last_error"]

    [outcome] = drain(agent, "w", {"write": write})          # no 15-minute wait
    assert (outcome.status, outcome.job.attempts) == ("done", 2)
    assert q(agent, "SELECT count(*) FROM sync_cursor WHERE source = 'resumed'") == 1


def test_a_live_workers_job_is_never_taken_from_it(agent):
    job_id = add(agent, "write", {"name": "busy"})
    conn, claimed, _ = claim_like_a_worker(agent)
    try:
        with agent.begin() as c:
            assert recovery.recover(c) == []
            assert [(r.id, r.alive) for r in recovery.running_jobs(c)] == [(job_id, True)]
        assert drain(agent, "w", {"write": write}) == []         # drain does not steal it
        assert job(agent, job_id)["status"] == "running"
    finally:
        conn.invalidate()                         # the worker's connection drops for good
    with agent.begin() as c:                      # now it is orphaned
        assert [(r.id, r.alive) for r in recovery.running_jobs(c)] == [(job_id, False)]


def test_a_job_that_kills_its_worker_every_time_ends_dead(agent):
    job_id = add(agent, "write", {"name": "poison"})
    for attempt in range(1, MAX_ATTEMPTS + 1):
        conn, claimed, pid = claim_like_a_worker(agent)
        assert claimed.attempts == attempt
        kill_backend(agent, pid)
        conn.invalidate()
        with agent.begin() as c:
            recovery.recover(c)
    assert job(agent, job_id)["status"] == "dead"
    assert drain(agent, "w", {"write": write}) == []


# ----------------------------------------------------------------- holds

def test_a_held_job_waits_without_spending_an_attempt_and_leaves_no_trace(agent):
    def held(conn, payload):
        write(conn, payload)
        raise JobHeld("provider down", delay=timedelta(hours=1))

    job_id = add(agent, "held", {"name": "ghost"})
    [outcome] = drain(agent, "w", {"held": held})
    assert outcome.status == "held"
    row = job(agent, job_id)
    assert (row["status"], row["attempts"]) == ("queued", 0)
    assert row["last_error"] == "held: provider down"
    assert q(agent, "SELECT count(*) FROM sync_cursor") == 0      # its writes rolled back
    assert run_one(agent, "w", {"held": held}) is None            # not before the delay
    with agent.begin() as c:
        assert [r[0] for r in recovery.held_jobs(c)] == [job_id]

    # Held as often as the outage lasts, it never dies.
    with agent.begin() as c:
        c.execute(text("UPDATE job SET run_after = now()"))
    for _ in range(MAX_ATTEMPTS + 2):
        assert drain(agent, "w", {"held": held})[0].status == "held"
        with agent.begin() as c:
            c.execute(text("UPDATE job SET run_after = now()"))
    assert (job(agent, job_id)["status"], job(agent, job_id)["attempts"]) == ("queued", 0)
    [outcome] = drain(agent, "w", {"held": write})                # the outage ends
    assert outcome.status == "done"
    assert q(agent, "SELECT count(*) FROM sync_cursor WHERE source = 'ghost'") == 1


# ------------------------------------------------- lost database connection

def test_a_connection_lost_mid_job_is_retried_at_once_and_writes_once(agent):
    attempts = []

    def flaky(conn, payload):
        write(conn, payload)
        attempts.append(1)
        if len(attempts) == 1:                    # the server drops us mid-transaction
            conn.execute(text("SELECT pg_terminate_backend(pg_backend_pid())"))
        return {"ok": True}

    job_id = add(agent, "flaky", {"name": "once"})
    outcomes = drain(agent, "w", {"flaky": flaky})                 # default 30 s backoff
    assert [o.status for o in outcomes] == ["failed", "done"], "retried in the same drain"
    assert "server closed the connection" in outcomes[0].error.lower() or \
        "terminat" in outcomes[0].error.lower()
    assert q(agent, "SELECT count(*) FROM sync_cursor WHERE source = 'once'") == 1
    assert (job(agent, job_id)["status"], job(agent, job_id)["attempts"]) == ("done", 2)


def test_serve_rides_out_a_database_outage_mid_job_and_finishes_once(agent, database,
                                                                    monkeypatch):
    monkeypatch.setattr(worker, "POLL_SECONDS", 0.05)
    settings = get_settings()
    proxy = FlakyProxy(settings.db_host, settings.db_port).up()
    url = settings.db_url("lease_agent", database).replace(
        "@%s:%d/" % (settings.db_host, settings.db_port), "@127.0.0.1:%d/" % proxy.port)
    via_proxy = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 2})

    in_job = threading.Event()
    calls = []

    def slow(conn, payload):
        calls.append(1)
        write(conn, payload)
        if len(calls) == 1:
            in_job.set()
            conn.execute(text("SELECT pg_sleep(30)"))      # the outage lands here
        return {"ok": True}

    job_id = add(agent, "slow", {"name": "survivor"})
    stop = threading.Event()
    errors = []

    def run():
        try:
            serve(via_proxy, stop.is_set, "proxied:1", {"slow": slow})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        assert in_job.wait(20), "the job never started"
        proxy.down()                              # Postgres "goes away" for the worker
        time.sleep(2.5)                           # the worker is still alive, waiting
        assert thread.is_alive() and not errors, errors
        assert job(agent, job_id)["status"] in ("running", "failed")
        proxy.up()
        deadline = time.monotonic() + 30
        while job(agent, job_id)["status"] != "done" and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        stop.set()
        thread.join(15)
        proxy.down()
        via_proxy.dispose()
    assert not errors, errors
    assert job(agent, job_id)["status"] == "done"
    assert len(calls) == 2
    assert q(agent, "SELECT count(*) FROM sync_cursor WHERE source = 'survivor'") == 1
