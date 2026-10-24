"""jobs/worker.py: the loop that claims, dispatches by kind and commits per
job, as lease_agent only."""

import threading
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.jobs import worker
from app.jobs.handlers import HandlerError, handler_for
from app.jobs.queue import enqueue
from app.jobs.worker import WorkerError, drain, run_one, serve


@pytest.fixture
def agent(clean):
    return clean["lease_agent"]


def add(agent, kind, payload=None, **kwargs):
    with agent.begin() as conn:
        return enqueue(conn, kind, payload or {}, **kwargs)


def q(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _write_cursor(conn, payload):
    conn.execute(text("INSERT INTO sync_cursor (source, cursor) VALUES (:s, 'x')"),
                 {"s": payload["name"]})
    return {"wrote": payload["name"]}


def _write_then_explode(conn, payload):
    _write_cursor(conn, payload)
    raise RuntimeError("handler blew up")


REGISTRY = {"write": _write_cursor, "explode": _write_then_explode}


def test_drain_runs_every_ready_job_in_dependency_order(agent):
    first = add(agent, "write", {"name": "one"})
    add(agent, "write", {"name": "two"}, depends_on=(first,))
    outcomes = drain(agent, "w", REGISTRY)
    assert [(o.job.payload["name"], o.status) for o in outcomes] == [("one", "done"), ("two", "done")]
    assert q(agent, "SELECT count(*) FROM sync_cursor") == 2
    assert q(agent, "SELECT payload->'result'->>'wrote' FROM job WHERE id = :i", i=first) == "one"


def test_a_failing_handler_rolls_back_its_writes_and_records_the_error(agent):
    add(agent, "explode", {"name": "ghost"})
    [outcome] = drain(agent, "w", REGISTRY, base=timedelta(hours=1))
    assert outcome.status == "failed"
    assert "handler blew up" in outcome.error
    assert q(agent, "SELECT count(*) FROM sync_cursor") == 0, "the job's writes rolled back"
    assert q(agent, "SELECT status FROM job") == "failed"
    assert "RuntimeError: handler blew up" in q(agent, "SELECT last_error FROM job")


def test_a_job_that_keeps_failing_ends_dead(agent):
    add(agent, "explode", {"name": "ghost"})
    outcomes = drain(agent, "w", REGISTRY, max_attempts=3, base=timedelta(0))
    assert [o.status for o in outcomes] == ["failed", "failed", "dead"]
    assert q(agent, "SELECT status FROM job") == "dead"


def test_an_unknown_kind_fails_the_job_not_the_worker(agent):
    add(agent, "no-such-kind")
    add(agent, "write", {"name": "after"})
    outcomes = drain(agent, "w", REGISTRY, base=timedelta(hours=1))
    assert [o.status for o in outcomes] == ["failed", "done"]
    assert "no handler for job kind 'no-such-kind'" in outcomes[0].error


def test_run_one_on_an_empty_queue_is_none(agent):
    assert run_one(agent, "w", REGISTRY) is None


@pytest.mark.parametrize("role", ["owner", "lease_gateway", "lease_api", "lease_reader"])
def test_the_worker_refuses_any_role_but_lease_agent(clean, role):
    with pytest.raises(WorkerError, match="lease_agent only, not"):
        drain(clean[role], "w", REGISTRY)


def test_serve_works_then_stops_when_asked(agent, monkeypatch):
    monkeypatch.setattr(worker, "POLL_SECONDS", 0.01)
    add(agent, "write", {"name": "served"})
    stop = threading.Event()

    def stop_once_done():
        if q(agent, "SELECT status FROM job") == "done":
            stop.set()
        return stop.is_set()

    thread = threading.Thread(target=serve, args=(agent, stop_once_done, "w", REGISTRY))
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive(), "serve did not stop"
    assert q(agent, "SELECT count(*) FROM sync_cursor WHERE source = 'served'") == 1


def test_once_exits_zero_when_everything_finished(agent, monkeypatch):
    monkeypatch.setattr("app.db.engine.engine", lambda role: agent)
    monkeypatch.setattr(worker, "drain", lambda eng, wid: drain(eng, wid, REGISTRY))
    add(agent, "write", {"name": "ok"})
    assert worker.main(["--once"]) == 0
    assert q(agent, "SELECT status FROM job") == "done"


def test_once_exits_nonzero_while_a_job_is_failed_or_dead(agent, monkeypatch):
    monkeypatch.setattr("app.db.engine.engine", lambda role: agent)
    add(agent, "explode", {"name": "ghost"})
    drain(agent, "w", REGISTRY, base=timedelta(hours=1))         # failed, backing off
    assert worker.main(["--once"]) == 1, "an unfinished month must not look finished"


def test_handler_for_names_the_known_kinds():
    with pytest.raises(HandlerError, match="known: abstraction, checking, ingest"):
        handler_for("bogus")
