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
    status: str                 # done, failed or dead
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
    with eng.begin() as conn:
        job = claim(conn, worker_id)
    if job is None:
        return None

    try:
        with eng.begin() as conn:
            result = handler_for(job.kind, registry)(conn, job.payload) or {}
            complete(conn, job.id, result)
    except Exception as exc:  # noqa: BLE001 - any handler failure is the job's, not the worker's
        error = "%s: %s" % (type(exc).__name__, exc)
        with eng.begin() as conn:
            status = fail(conn, job.id, error, max_attempts=max_attempts, base=base)
        log.warning("job #%d %s %s (attempt %d): %s", job.id, job.kind, status, job.attempts, error)
        return Outcome(job, status, error=error)

    log.info("job #%d %s done: %s", job.id, job.kind, result)
    return Outcome(job, "done", result=result)


def drain(eng: Engine, worker_id: Optional[str] = None,
          registry: Mapping[str, Handler] = HANDLERS, **kwargs) -> List[Outcome]:
    """Run jobs until none is ready. Retries waiting out a backoff are left
    for a later run."""
    assert_agent(eng)
    worker_id = worker_id or default_worker_id()
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

    last_beat = 0.0
    while not should_stop():
        if run_one(eng, worker_id, registry) is not None:
            continue
        if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
            log.info("heartbeat: idle")
            last_beat = time.monotonic()
        time.sleep(POLL_SECONDS)
    log.info("stopped")


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
