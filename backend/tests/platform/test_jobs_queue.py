"""jobs/queue.py: idempotent enqueue, SKIP LOCKED claims, dependencies,
backoff and dead-lettering, all as the worker's role, lease_agent."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.jobs.queue import JobError, claim, complete, enqueue, fail, release_stale


@pytest.fixture
def agent(clean):
    return clean["lease_agent"]


def q(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def add(agent, kind="noop", payload=None, **kwargs):
    with agent.begin() as conn:
        return enqueue(conn, kind, payload or {}, **kwargs)


def take(agent, worker="w1"):
    with agent.begin() as conn:
        return claim(conn, worker)


# ------------------------------------------------------------------ enqueue

def test_enqueue_stores_a_queued_job(agent):
    job_id = add(agent, "ingest", {"period": "2026-01-01"})
    assert q(agent, "SELECT status FROM job WHERE id = :i", i=job_id) == "queued"
    assert q(agent, "SELECT payload->>'period' FROM job WHERE id = :i", i=job_id) == "2026-01-01"


def test_a_repeated_idempotency_key_returns_the_existing_job(agent):
    first = add(agent, "ingest", {"a": 1}, idempotency_key="k1")
    second = add(agent, "ingest", {"a": 2}, idempotency_key="k1")
    assert first == second
    assert q(agent, "SELECT count(*) FROM job") == 1
    assert q(agent, "SELECT payload->>'a' FROM job") == "1", "the first payload stands"


def test_jobs_without_a_key_are_never_deduplicated(agent):
    add(agent)
    add(agent)
    assert q(agent, "SELECT count(*) FROM job") == 2


# -------------------------------------------------------------------- claim

def test_claim_marks_running_and_counts_the_attempt(agent):
    job_id = add(agent, "ingest", {"x": 1})
    job = take(agent, "w1")
    assert (job.id, job.kind, job.payload, job.attempts) == (job_id, "ingest", {"x": 1}, 1)
    assert q(agent, "SELECT status || ':' || locked_by FROM job") == "running:w1"
    assert take(agent) is None, "a running job is not claimable again"


def test_claim_on_an_empty_queue_is_none(agent):
    assert take(agent) is None


def test_two_workers_never_claim_the_same_job_and_neither_waits(agent):
    a, b = add(agent), add(agent)
    with agent.connect() as one, agent.connect() as two:
        tx = one.begin()
        first = claim(one, "w1")                    # row lock held, uncommitted
        with two.begin():
            second = claim(two, "w2")               # skips it instead of blocking
        tx.commit()
    assert {first.id, second.id} == {a, b}


def test_jobs_are_claimed_in_run_after_order(agent):
    later = add(agent, run_after=datetime.now(timezone.utc) - timedelta(seconds=1))
    earlier = add(agent, run_after=datetime.now(timezone.utc) - timedelta(hours=1))
    assert take(agent).id == earlier
    assert take(agent).id == later


def test_a_future_run_after_is_not_claimable(agent):
    add(agent, run_after=datetime.now(timezone.utc) + timedelta(hours=1))
    assert take(agent) is None


def test_a_job_waits_until_every_dependency_is_done(agent):
    a = add(agent, "a")
    b = add(agent, "b")
    c = add(agent, "c", depends_on=(a, b))
    claimed = {take(agent).id, take(agent).id}
    assert claimed == {a, b}
    assert take(agent) is None
    with agent.begin() as conn:
        complete(conn, a)
    assert take(agent) is None, "b is still running"
    with agent.begin() as conn:
        complete(conn, b)
    assert take(agent).id == c


def test_a_dead_dependency_blocks_its_dependents(agent):
    a = add(agent, "a")
    add(agent, "b", depends_on=(a,))
    take(agent)
    with agent.begin() as conn:
        assert fail(conn, a, "boom", max_attempts=1) == "dead"
    assert take(agent) is None


# ------------------------------------------------------- complete and fail

def test_complete_keeps_the_result_in_the_payload(agent):
    job_id = add(agent, "ingest", {"period": "2026-01-01"})
    take(agent)
    with agent.begin() as conn:
        complete(conn, job_id, {"charges": 12})
    assert q(agent, "SELECT status FROM job") == "done"
    assert q(agent, "SELECT payload->'result'->>'charges' FROM job") == "12"
    assert q(agent, "SELECT payload->>'period' FROM job") == "2026-01-01"


def test_fail_backs_off_exponentially(agent):
    job_id = add(agent)
    for attempt in (1, 2):
        with agent.begin() as conn:
            conn.execute(text("UPDATE job SET run_after = now() - interval '1 s'"))
        assert take(agent).attempts == attempt
        with agent.begin() as conn:
            assert fail(conn, job_id, "boom", base=timedelta(seconds=10)) == "failed"
        wait = q(agent, "SELECT extract(epoch FROM run_after - now()) FROM job")
        assert 10 * 2 ** attempt - 2 < float(wait) <= 10 * 2 ** attempt
    assert take(agent) is None, "still backing off"
    assert q(agent, "SELECT last_error FROM job") == "boom"


def test_a_job_is_dead_after_max_attempts_and_keeps_its_last_error(agent):
    job_id = add(agent)
    statuses = []
    for n in range(3):
        assert take(agent) is not None
        with agent.begin() as conn:
            statuses.append(fail(conn, job_id, "error %d" % n, max_attempts=3,
                                 base=timedelta(0)))
    assert statuses == ["failed", "failed", "dead"]
    assert take(agent) is None
    assert q(agent, "SELECT last_error FROM job") == "error 2"
    assert q(agent, "SELECT attempts FROM job") == 3


def test_a_retried_job_that_succeeds_clears_its_error(agent):
    job_id = add(agent)
    take(agent)
    with agent.begin() as conn:
        fail(conn, job_id, "transient", base=timedelta(0))
    take(agent)
    with agent.begin() as conn:
        complete(conn, job_id)
    assert q(agent, "SELECT status FROM job") == "done"
    assert q(agent, "SELECT last_error FROM job") is None


def test_release_stale_puts_back_a_job_whose_worker_died(agent):
    job_id = add(agent)
    take(agent, "dead-worker")
    with agent.begin() as conn:
        conn.execute(text("UPDATE job SET locked_at = now() - interval '1 hour'"))
        assert release_stale(conn, timedelta(minutes=15)) == 1
    assert "dead-worker" in q(agent, "SELECT last_error FROM job")
    assert take(agent).id == job_id


def test_release_stale_leaves_a_fresh_claim_alone(agent):
    add(agent)
    take(agent)
    with agent.begin() as conn:
        assert release_stale(conn, timedelta(minutes=15)) == 0


# ---------------------------------------------------------------- bad input

@pytest.mark.parametrize("kind", ["", "  ", None, 3])
def test_a_job_needs_a_kind(agent, kind):
    with pytest.raises(JobError, match="kind"):
        add(agent, kind)


@pytest.mark.parametrize("payload, match", [
    (["not", "a", "mapping"], "mapping"),
    ({"when": {1, 2}}, "JSON"),
])
def test_a_bad_payload_is_refused(agent, payload, match):
    with agent.begin() as conn, pytest.raises(JobError, match=match):
        enqueue(conn, "noop", payload)


def test_depending_on_a_job_that_does_not_exist_is_refused(agent):
    with pytest.raises(JobError, match=r"unknown job\(s\) \[999\]"):
        add(agent, depends_on=(999,))


@pytest.mark.parametrize("deps", [("1",), (1.5,), (True,)])
def test_depends_on_must_be_integer_ids(agent, deps):
    with pytest.raises(JobError, match="integers"):
        add(agent, depends_on=deps)


def test_a_naive_run_after_is_refused(agent):
    with pytest.raises(JobError, match="timezone-aware"):
        add(agent, run_after=datetime.now())


def test_a_blank_idempotency_key_is_refused(agent):
    with pytest.raises(JobError, match="idempotency_key"):
        add(agent, idempotency_key=" ")


def test_complete_or_fail_a_job_that_is_not_running_is_refused(agent):
    job_id = add(agent)
    with agent.begin() as conn, pytest.raises(JobError, match="not running"):
        complete(conn, job_id)
    with agent.begin() as conn, pytest.raises(JobError, match="not running"):
        fail(conn, job_id, "boom")
    with agent.begin() as conn, pytest.raises(JobError, match="not running"):
        complete(conn, 12345)


def test_claim_needs_a_worker_id(agent):
    with agent.begin() as conn, pytest.raises(JobError, match="worker_id"):
        claim(conn, "")


def test_max_attempts_below_one_is_refused(agent):
    job_id = add(agent)
    take(agent)
    with agent.begin() as conn, pytest.raises(JobError, match="max_attempts"):
        fail(conn, job_id, "boom", max_attempts=0)


def test_the_auditor_cannot_enqueue(clean):
    with clean["lease_reader"].begin() as conn, pytest.raises(ProgrammingError,
                                                             match="permission denied"):
        enqueue(conn, "noop", {})
