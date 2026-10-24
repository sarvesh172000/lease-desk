"""Stuck-job recovery: a job whose worker died is put back at once, not after
fifteen minutes, and a job that cannot run *yet* is held, not failed.

**Liveness, from Postgres itself.** While a worker runs a job it holds a
session-level advisory lock on that job (`hold_liveness`), taken in the same
transaction that claims it, before the claim commits. A process that dies,
however it dies (SIGKILL, OOM, a lost network), loses its connection, and
Postgres drops the lock with the backend. So "is this job's worker alive?" is
one question to the database: can anyone else take the lock? `recover()`
asks it for every `running` job and puts back each one nobody holds. There is
no window in which a live job looks dead: the job is not visible as running
until the claim commits, and by then the lock is held.

This is the worker's heartbeat: Postgres keeps it for as long as the
connection lives. The time-based `queue.release_stale()` stays as the
backstop for a worker that is alive but hung (its lock is still held).

A killed worker's backend that is blocked on a lock does not notice its
client is gone until it next talks to it. `prepare()` sets
`client_connection_check_interval` on the job connection so Postgres checks
every second and drops such a backend, its locks and its uncommitted work.

**Holding.** A handler raises `JobHeld` when the job cannot make progress for
a reason outside it (the model provider is down and the circuit breaker is
open). The worker then calls `hold()`: the job goes back to `queued`, to be
claimed after `delay`, with the attempt it just used given back, so an
outage of any length never dead-letters work. Its `last_error` says why it
is waiting.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .queue import MAX_ATTEMPTS

# The advisory-lock namespace (classid) for job liveness: "LD" for Lease Desk.
# The two-integer form never collides with the single-bigint locks taken
# elsewhere (the audit chain, lease drafting, work item creation).
LOCK_CLASS = 0x4C44
CHECK_INTERVAL_MS = 1000


class JobHeld(RuntimeError):
    """Raised by a handler that must wait: hold the job, do not fail it."""

    def __init__(self, reason: str, delay: timedelta = timedelta(seconds=60)):
        super().__init__(reason)
        self.reason = reason
        self.delay = max(delay, timedelta(seconds=1))


def _objid(job_id: int) -> int:
    return int(job_id) % 2147483647


def prepare(conn: Connection) -> None:
    """Session settings for a job connection (idempotent, cheap)."""
    conn.execute(text("SELECT set_config('client_connection_check_interval', :v, false)"),
                 {"v": str(CHECK_INTERVAL_MS)})


def hold_liveness(conn: Connection, job_id: int) -> None:
    """Take the job's liveness lock for the life of this session."""
    conn.execute(text("SELECT pg_advisory_lock(:c, :o)"), {"c": LOCK_CLASS, "o": _objid(job_id)})


def release_liveness(conn: Connection, job_id: int) -> None:
    conn.execute(text("SELECT pg_advisory_unlock(:c, :o)"), {"c": LOCK_CLASS, "o": _objid(job_id)})


def _alive(conn: Connection, job_id: int) -> bool:
    """True when some session holds the job's liveness lock. Taking it here
    (transaction-scoped) proves nobody does; it is let go at commit."""
    got = conn.execute(text("SELECT pg_try_advisory_xact_lock(:c, :o)"),
                       {"c": LOCK_CLASS, "o": _objid(job_id)}).scalar_one()
    return not got


def orphaned(conn: Connection) -> List[int]:
    """Running jobs whose worker is gone."""
    running = conn.execute(text("SELECT id FROM job WHERE status = 'running' ORDER BY id")).scalars()
    return [job_id for job_id in list(running) if not _alive(conn, job_id)]


def recover(conn: Connection, max_attempts: int = MAX_ATTEMPTS) -> List[int]:
    """Put back every orphaned job: claimable again now, its attempt counted
    (a job that kills its worker every time still ends dead). Returns the ids."""
    ids = orphaned(conn)
    if not ids:
        return []
    return list(conn.execute(text("""
        UPDATE job SET status = CASE WHEN attempts >= :max THEN 'dead' ELSE 'failed' END,
                       run_after = now(),
                       last_error = 'worker ' || coalesce(locked_by, '?')
                                    || ' died mid-run; put back by recovery',
                       locked_by = NULL, locked_at = NULL
         WHERE id = ANY (CAST(:ids AS bigint[])) AND status = 'running'
        RETURNING id
    """), {"ids": ids, "max": max_attempts}).scalars())


def hold(conn: Connection, job_id: int, reason: str, delay: timedelta) -> bool:
    """Requeue a running job after `delay` without spending its attempt."""
    return conn.execute(text("""
        UPDATE job SET status = 'queued', attempts = greatest(attempts - 1, 0),
                       run_after = now() + make_interval(secs => :secs),
                       last_error = :why, locked_by = NULL, locked_at = NULL
         WHERE id = :id AND status = 'running'
        RETURNING id
    """), {"id": job_id, "secs": delay.total_seconds(),
           "why": ("held: %s" % reason)[:4000]}).scalar() is not None


@dataclass(frozen=True)
class RunningJob:
    id: int
    kind: str
    locked_by: Optional[str]
    locked_at: object
    alive: bool


def running_jobs(conn: Connection) -> List[RunningJob]:
    """Every running job and whether its worker is alive (for the ops page).
    Read-only in effect: the probe locks are let go when the caller's
    transaction ends."""
    rows = conn.execute(text(
        "SELECT id, kind, locked_by, locked_at FROM job WHERE status = 'running' ORDER BY id")).all()
    return [RunningJob(r.id, r.kind, r.locked_by, r.locked_at, _alive(conn, r.id)) for r in rows]


def held_jobs(conn: Connection) -> List[tuple]:
    """(id, kind, run_after, last_error) of every job waiting out a hold."""
    return [tuple(r) for r in conn.execute(text("""
        SELECT id, kind, run_after, last_error FROM job
         WHERE status = 'queued' AND last_error LIKE 'held: %' ORDER BY id"""))]
