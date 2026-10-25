#!/bin/zsh
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a
PYTHONPATH=backend .venv/bin/python -c "
from app.db.engine import engine; from app.jobs.queue import enqueue
with engine('lease_agent').begin() as c: enqueue(c, 'disputes', {})" && PYTHONPATH=backend .venv/bin/python -m app.jobs.worker --once 2>&1 | tail -1
