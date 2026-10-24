"""The background worker. Connects as `lease_agent`, and only as that.

    python -m app.jobs.worker

A stub until A7, when it gains the job loop (`SELECT ... FOR UPDATE SKIP
LOCKED`, backoff, dead-lettering). It already proves the one thing Compose
needs from it: it starts, reaches the database as the agent role, and keeps a
heartbeat in the log.
"""

import logging
import signal
import time

from sqlalchemy import text

from ..db.engine import engine

log = logging.getLogger("leasedesk.worker")
HEARTBEAT_SECONDS = 30


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    stopping = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))

    with engine("lease_agent").connect() as conn:
        role = conn.execute(text("SELECT current_user")).scalar_one()
    log.info("connected as %s; job loop arrives in A7", role)

    while not stopping:
        log.info("heartbeat")
        for _ in range(HEARTBEAT_SECONDS):
            if stopping:
                break
            time.sleep(1)
    log.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
