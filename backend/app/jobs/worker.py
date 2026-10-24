"""The background worker. Connects as `lease_agent`, and only as that.

    python -m app.jobs.worker            # run until SIGTERM
    python -m app.jobs.worker --once     # drain what is ready, then exit

The role is checked, not assumed: if the engine it is handed is not
`lease_agent`, it refuses to start. That role cannot write the ledger, the
outbox or the golden tables, so no handler bug can either.

Each job runs in three short transactions:

  1. claim    `SELECT ... FOR UPDATE SKIP LOCKED`, mark running, commit. The
              attempt is counted before any work starts, so a job that kills
              its worker still runs out of attempts.
  2. run      the handler and `complete()` in one transaction, so a job's
              writes and its `done` commit together or not at all.
  3. fail     only if 2 raised: roll 2 back, then record the error with
              backoff (or dead-letter it) in a transaction of its own.

On SIGTERM it finishes the job in hand and stops. While idle it logs a
heartbeat so a stuck worker is visible in `make logs`.

Recovery (C3, `recovery.py`). Claim and run share one connection, which holds
the job's liveness lock from the claim until the job is recorded done, failed
or held, so a worker killed mid-job is visible to the database the moment its
connection drops. Every `drain()` and `serve()` starts by putting such jobs
back, and `serve()` looks again on every heartbeat, so a restarted worker
resumes the month where the dead one stopped: the dead job's writes rolled
back with its transaction, and it runs again from the start. A handler that
raises `JobHeld` (the model provider is down) is requeued for later without
spending an attempt. A lost database connection fails the job with no
backoff, so it is retried as soon as the database answers; while it does not,
`serve()` waits and keeps going instead of exiting.
"""

import argparse
import logging
import os
import signal
import socket
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, List, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from . import recovery
from .handlers import HANDLERS, Handler, handler_for
from .queue import BACKOFF_BASE, MAX_ATTEMPTS, Job, claim, complete, fail, release_stale

log = logging.getLogger("leasedesk.worker")
ROLE = "lease_agent"
HEARTBEAT_SECONDS = 30
POLL_SECONDS = 1.0


class WorkerError(RuntimeError):
    """The worker was started wrongly (for example, as the wrong role)."""


@dataclass(frozen=True)
class Outcome:
    job: Job
    status: str                 # done, failed, dead or held
    result: Optional[dict] = None
    error: Optional[str] = None


def default_worker_id() -> str:
    return "%s:%d" % (socket.gethostname(), os.getpid())


def assert_agent(eng: Engine) -> None:
    with eng.connect() as conn:
        role = conn.execute(text("SELECT current_user")).scalar_one()
    if role != ROLE:
        raise WorkerError("the worker connects as %s only, not %s" % (ROLE, role))


def run_one(
    eng: Engine,
    worker_id: str,
    registry: Mapping[str, Handler] = HANDLERS,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    base: timedelta = BACKOFF_BASE,
) -> Optional[Outcome]:
    """Claim and run one job. None when nothing is ready."""
    with eng.connect() as conn:
        _prepare(conn)
        with conn.begin():
            job = claim(conn, worker_id)
            if job is not None:
                recovery.hold_liveness(conn, job.id)     # before the claim commits
        if job is None:
            return None
        try:
            outcome = _run(eng, conn, job, registry, max_attempts, base)
        finally:
            _let_go(conn, job.id)
    _publish_breakers(eng)
    return outcome


def _run(eng: Engine, conn, job: Job, registry: Mapping[str, Handler],
         max_attempts: int, base: timedelta) -> Outcome:
    try:
        with conn.begin():
            result = handler_for(job.kind, registry)(conn, job.payload) or {}
            complete(conn, job.id, result)
    except recovery.JobHeld as held:
        with eng.begin() as own:
            recovery.hold(own, job.id, held.reason, held.delay)
        log.warning("job #%d %s held for %s: %s", job.id, job.kind, held.delay, held.reason)
        return Outcome(job, "held", error=held.reason)
    except Exception as exc:  # noqa: BLE001 - any handler failure is the job's, not the worker's
        error = "%s: %s" % (type(exc).__name__, exc)
        # A dropped connection is the database's failure, not the job's: retry
        # as soon as it answers instead of backing off. (If it does not answer,
        # fail() raises too; the job stays running with no live worker, and
        # recovery puts it back.)
        retry_base = timedelta(0) if _disconnected(exc) else base
        with eng.begin() as own:
            status = fail(own, job.id, error, max_attempts=max_attempts, base=retry_base)
        log.warning("job #%d %s %s (attempt %d): %s", job.id, job.kind, status, job.attempts, error)
        return Outcome(job, status, error=error)

    log.info("job #%d %s done: %s", job.id, job.kind, result)
    return Outcome(job, "done", result=result)


def _prepare(conn) -> None:
    try:
        recovery.prepare(conn)
        conn.commit()
    except DBAPIError as exc:
        if _disconnected(exc):
            raise
        conn.rollback()                 # a server without the setting still works


def _let_go(conn, job_id: int) -> None:
    """Drop the liveness lock. On a dead connection it is already gone."""
    try:
        recovery.release_liveness(conn, job_id)
        conn.commit()
    except Exception:  # noqa: BLE001 - a broken connection: drop it, the lock went with it
        try:
            conn.invalidate()
        except Exception:  # noqa: BLE001
            pass


def _disconnected(exc: BaseException) -> bool:
    return isinstance(exc, DBAPIError) and bool(exc.connection_invalidated)


def _publish_breakers(eng: Engine) -> None:
    from ..work.breaker import publish_if_changed

    try:
        publish_if_changed(eng)
    except DBAPIError as exc:         # visibility must never stop work
        log.warning("could not publish breaker state: %s", exc)


def recover(eng: Engine) -> List[int]:
    """Put back the jobs of workers that died mid-run (see recovery.py)."""
    with eng.begin() as conn:
        ids = recovery.recover(conn)
    if ids:
        log.warning("put back %d job(s) whose worker died mid-run: %s", len(ids), ids)
    return ids


def drain(eng: Engine, worker_id: Optional[str] = None,
          registry: Mapping[str, Handler] = HANDLERS, **kwargs) -> List[Outcome]:
    """Run jobs until none is ready. Retries waiting out a backoff are left
    for a later run."""
    assert_agent(eng)
    worker_id = worker_id or default_worker_id()
    recover(eng)
    outcomes = []
    while True:
        outcome = run_one(eng, worker_id, registry, **kwargs)
        if outcome is None:
            return outcomes
        outcomes.append(outcome)


def unfinished(eng: Engine) -> List[tuple]:
    """Jobs waiting out a backoff or dead-lettered: (id, kind, status, last_error).
    `--once` reports them so a month that did not finish never exits 0."""
    with eng.connect() as conn:
        return [tuple(r) for r in conn.execute(text(
            "SELECT id, kind, status, last_error FROM job "
            "WHERE status IN ('failed', 'dead') ORDER BY id"))]


def serve(eng: Engine, should_stop: Callable[[], bool], worker_id: Optional[str] = None,
          registry: Mapping[str, Handler] = HANDLERS) -> None:
    """The long-running loop: work while there is work, heartbeat while idle."""
    assert_agent(eng)
    worker_id = worker_id or default_worker_id()
    with eng.begin() as conn:
        released = release_stale(conn)
    log.info("worker %s connected as %s; released %d stale job(s)", worker_id, ROLE, released)
    recover(eng)

    last_beat = 0.0
    while not should_stop():
        try:
            if run_one(eng, worker_id, registry) is not None:
                continue
            if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
                recover(eng)
                log.info("heartbeat: idle")
                last_beat = time.monotonic()
        except DBAPIError as exc:
            if not _disconnected(exc) and not _unreachable(exc):
                raise
            # The database went away. Keep the process: wait, then look for
            # jobs orphaned by the outage as soon as it answers again.
            log.warning("database unavailable, waiting: %s", str(exc).splitlines()[0])
            last_beat = 0.0
        time.sleep(POLL_SECONDS)
    log.info("stopped")


def _unreachable(exc: DBAPIError) -> bool:
    from sqlalchemy.exc import OperationalError

    return isinstance(exc, OperationalError)


def main(argv=None) -> int:
    from ..db.engine import engine

    parser = argparse.ArgumentParser(description="Run background jobs as lease_agent")
    parser.add_argument("--once", action="store_true", help="drain ready jobs, then exit")
    parser.add_argument("--worker-id", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    eng = engine(ROLE)
    if args.once:
        outcomes = drain(eng, args.worker_id)
        bad = [o for o in outcomes if o.status != "done"]
        log.info("drained %d job(s), %d not done", len(outcomes), len(bad))
        stuck = unfinished(eng)
        for job_id, kind, status, error in stuck:
            log.warning("job #%d %s is %s: %s", job_id, kind, status, error)
        return 1 if bad or stuck else 0

    stopping: List[bool] = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))
    signal.signal(signal.SIGINT, lambda *_: stopping.append(True))
    serve(eng, lambda: bool(stopping), args.worker_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
