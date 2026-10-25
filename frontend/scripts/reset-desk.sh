#!/bin/zsh
# A fresh demo desk, the way the judge will see it: drop, seed, confirm the lease
# versions after the abstraction jobs land, run both months, set the clock,
# record the three refused attempts.
set -e
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a
docker compose exec -T db psql -U leasedesk -d postgres -c "DROP DATABASE IF EXISTS leasedesk WITH (FORCE);" -c "CREATE DATABASE leasedesk OWNER leasedesk;" > /dev/null
make demo-data > /dev/null 2>&1
# the docker worker may still be reading leases when demo-data's confirm step runs; confirm again once it has
sleep 5
PYTHONPATH=backend .venv/bin/python -m app.work.confirm_leases --as PER-RM-BAY
make run-month M=2026-01 > /dev/null 2>&1
make run-month M=2026-07 > /dev/null 2>&1
PYTHONPATH=backend .venv/bin/python -m app.jobs.clock set 2026-07-01
make prove-limits 2>&1 | grep -E "refused by|verify_chain"
# the leases' deadlines as of the business date, last, so no earlier id moves
PYTHONPATH=backend .venv/bin/python -m app.jobs.obligations --disputes > /dev/null
echo "desk ready"
