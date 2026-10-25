#!/bin/zsh
# Run one of the worker's sweeps by hand on a desk whose worker has not: `obligations` (deadlines
# the leases set) or `disputes` (letters for upheld holds). Enqueues the job as the agent role and
# drains it once. Against a hosted desk, run it where the backend's .env and DB are reachable.
#
#   frontend/scripts/sweep.sh obligations
#   frontend/scripts/sweep.sh disputes
kind="${1:?usage: sweep.sh obligations|disputes}"
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a
PYTHONPATH=backend .venv/bin/python -c "
from app.db.engine import engine; from app.jobs.queue import enqueue
with engine('lease_agent').begin() as c: enqueue(c, '$kind', {})" && PYTHONPATH=backend .venv/bin/python -m app.jobs.worker --once 2>&1 | tail -1
