"""The job queue: a Postgres table, not a broker.

Jobs live in the `job` table next to the work they produce, so enqueuing a job
and recording why it was enqueued commit or roll back together, and nothing
extra has to run for `make up`. The worker only ever connects as `lease_agent`,
which may SELECT, INSERT and UPDATE `job` and nothing it should not.

Four guarantees, each enforced here rather than hoped for in callers:

  * **Idempotent enqueue.** A repeated `idempotency_key` returns the job that
    already exists. Running a month twice therefore enqueues nothing new.
  * **One worker per job.** `claim()` takes the row with
    `SELECT ... FOR UPDATE SKIP LOCKED`, so two workers never claim the same
    job and neither waits on the other.
  * **Order by dependency, not by hope.** A job is claimable only once every
    job in its `depends_on` is `done`, and only once `run_after` has passed.
  * **Failures back off, then stop.** A failed job is retried after
    `base * 2^attempts`; after `max_attempts` it is `dead` and keeps its last
    error for a person to read. A dead job's dependents stay queued: nothing
    downstream runs on top of a step that never finished.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

MAX_ATTEMPTS = 5
BACKOFF_BASE = timedelta(seconds=30)
STALE_AFTER = timedelta(minutes=15)


class JobError(ValueError):
    """A job request is malformed, or a job is not in the state an operation needs."""


@dataclass(frozen=True)
class Job:
    id: int
    kind: str
    payload: Mapping[str, Any]
    attempts: int
    depends_on: Tuple[int, ...] = field(default_factory=tuple)
    idempotency_key: Optional[str] = None


# ------------------------------------------------------------------ enqueue

def enqueue(
    conn: Connection,
    kind: str,
    payload: Optional[Mapping[str, Any]] = None,
    *,
    idempotency_key: Optional[str] = None,
    depends_on: Iterable[int] = (),
    run_after: Optional[datetime] = None,
) -> int:
    """Add a job and return its id. A key seen before returns the existing id
    and changes nothing, even if the payload differs."""
    _check_kind(kind)
    body = _payload_json(payload)
    deps = _check_depends_on(conn, depends_on)
    if idempotency_key is not None and (not isinstance(idempotency_key, str)
                                        or not idempotency_key.strip()):
        raise JobError("idempotency_key must be a non-empty string or None")
    if run_after is not None and (not isinstance(run_after, datetime) or run_after.tzinfo is None):
        raise JobError("run_after must be a timezone-aware datetime")

    new_id = conn.execute(text("""
        INSERT INTO job (kind, payload, idempotency_key, depends_on, run_after)
        VALUES (:kind, CAST(:payload AS jsonb), :key, CAST(:deps AS bigint[]),
                COALESCE(:run_after, now()))
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id
    """), dict(kind=kind, payload=body, key=idempotency_key, deps=list(deps),
               run_after=run_after)).scalar()
    if new_id is not None:
        return new_id
    return conn.execute(text("SELECT id FROM job WHERE idempotency_key = :key"),
                        {"key": idempotency_key}).scalar_one()


# -------------------------------------------------------------------- claim

_CLAIM = text("""
    WITH next AS (
        SELECT j.id FROM job j
         WHERE j.status IN ('queued', 'failed')
           AND j.run_after <= now()
           AND (SELECT count(*) FROM job d
                 WHERE d.id = ANY (j.depends_on) AND d.status = 'done')
               = cardinality(j.depends_on)
         ORDER BY j.run_after, j.id
         LIMIT 1
           FOR UPDATE OF j SKIP LOCKED
    )
    UPDATE job SET status = 'running', locked_by = :worker, locked_at = now(),
                   attempts = job.attempts + 1
      FROM next WHERE job.id = next.id
    RETURNING job.id, job.kind, job.payload, job.attempts, job.depends_on,
              job.idempotency_key
""")


def claim(conn: Connection, worker_id: str) -> Optional[Job]:
    """Take the next ready job, or None. Commit promptly: the row lock is held
    until the caller's transaction ends."""
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise JobError("worker_id must be a non-empty string")
    row = conn.execute(_CLAIM, {"worker": worker_id}).first()
    if row is None:
        return None
    return Job(id=row.id, kind=row.kind, payload=row.payload or {}, attempts=row.attempts,
               depends_on=tuple(row.depends_on or ()), idempotency_key=row.idempotency_key)


# ------------------------------------------------------- complete and fail

def complete(conn: Connection, job_id: int, result: Optional[Mapping[str, Any]] = None) -> None:
    """Mark a running job done. Its result, if any, is kept in the payload
    under "result" (the table has no result column)."""
    params = {"id": job_id, "result": None if result is None else _payload_json(result)}
    done = conn.execute(text("""
        UPDATE job SET status = 'done', last_error = NULL,
               payload = CASE WHEN CAST(:result AS jsonb) IS NULL THEN payload
                              ELSE payload || jsonb_build_object('result', CAST(:result AS jsonb))
                         END
         WHERE id = :id AND status = 'running'
        RETURNING id
    """), params).scalar()
    if done is None:
        raise JobError("job %s is not running, so it cannot be completed" % job_id)


def fail(
    conn: Connection,
    job_id: int,
    error: str,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    base: timedelta = BACKOFF_BASE,
) -> str:
    """Record a failure. Returns the new status: 'failed' (to be retried after
    base * 2^attempts) or 'dead' once max_attempts is reached."""
    if max_attempts < 1:
        raise JobError("max_attempts must be at least 1")
    row = conn.execute(text("""
        UPDATE job SET
            status = CASE WHEN attempts >= :max THEN 'dead' ELSE 'failed' END,
            run_after = CASE WHEN attempts >= :max THEN run_after
                             ELSE now() + make_interval(secs => :base * power(2, attempts))
                        END,
            last_error = :error, locked_by = NULL, locked_at = NULL
         WHERE id = :id AND status = 'running'
        RETURNING status
    """), {"id": job_id, "error": str(error)[:4000], "max": max_attempts,
           "base": base.total_seconds()}).first()
    if row is None:
        raise JobError("job %s is not running, so it cannot fail" % job_id)
    return row.status


def release_stale(conn: Connection, older_than: timedelta = STALE_AFTER) -> int:
    """Put back jobs whose worker died mid-run (claimed, never finished).
    Their attempt still counts, so a job that kills its worker every time
    still ends up dead rather than looping forever."""
    return conn.execute(text("""
        UPDATE job SET status = CASE WHEN attempts >= :max THEN 'dead' ELSE 'failed' END,
                       last_error = 'worker ' || coalesce(locked_by, '?') || ' stopped mid-run',
                       locked_by = NULL, locked_at = NULL
         WHERE status = 'running' AND locked_at < now() - make_interval(secs => :age)
    """), {"age": older_than.total_seconds(), "max": MAX_ATTEMPTS}).rowcount


# ------------------------------------------------------------- validation

def _check_kind(kind: Any) -> None:
    if not isinstance(kind, str) or not kind.strip():
        raise JobError("job kind must be a non-empty string, got %r" % (kind,))


def _payload_json(payload: Optional[Mapping[str, Any]]) -> str:
    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        raise JobError("job payload must be a mapping, got %s" % type(payload).__name__)
    try:
        return json.dumps(payload, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise JobError("job payload is not JSON-serializable: %s" % exc) from exc


def _check_depends_on(conn: Connection, depends_on: Iterable[int]) -> Tuple[int, ...]:
    deps = tuple(depends_on)
    if any(isinstance(d, bool) or not isinstance(d, int) for d in deps):
        raise JobError("depends_on must be job ids (integers), got %r" % (deps,))
    if not deps:
        return deps
    # A dependency that does not exist could never be done, and the job would
    # wait forever without saying why.
    found = set(conn.execute(text("SELECT id FROM job WHERE id = ANY (CAST(:ids AS bigint[]))"),
                             {"ids": list(deps)}).scalars())
    missing = sorted(set(deps) - found)
    if missing:
        raise JobError("depends_on names unknown job(s) %s" % missing)
    return deps
