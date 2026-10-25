#!/bin/sh
# One-time setup of a hosted demo database (docs/DEPLOY.md), what `make
# demo-data` does on a laptop: create the database, migrate (schema, triggers
# and the four roles, as the owner), seed January, set the dev passwords, run
# January, confirm the five leases as the Bay Area manager and run it again,
# then July (CLINIC-01's amendment takes effect), and set the business clock.
#
# Every step is idempotent, so running it again changes nothing. The generator
# is deterministic, so what it seeds matches the documents baked into the image
# (BAKE_DEMO_DATA=1) byte for byte.
set -eu
cd /app/backend
# The generator's scratch output, in the app user's own home (not /tmp).
WORK="$HOME/demo-setup"

run_month() {
  local period="$1"
  python -m app.jobs.monthly --period "$period"
  python -m app.jobs.worker --once
}

python -m app.db.ensure_database
python -m alembic upgrade head

python -m datagen.build --out "$WORK/2026-01" --month 2026-01 > /dev/null
python -m app.records.seed --data "$WORK/2026-01"
python -m app.auth.passwords set-dev-passwords
run_month 2026-01
python -m app.work.confirm_leases --as PER-RM-BAY
run_month 2026-01

python -m datagen.build --out "$WORK/2026-07" --month 2026-07 > /dev/null
python -m app.records.seed --data "$WORK/2026-07"
run_month 2026-07
python -m app.jobs.clock set 2026-07-01

echo "demo database ready"
