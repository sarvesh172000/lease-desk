# Lease Desk. Target names are frozen (docs/phases/PHASE_1.md, group 1).
#
#   make up migrate seed      a fresh clone to a seeded database
#   make test                 the whole suite (database tests run when `make up` is)
#   make prove-roles          the database refusing every forbidden write

# Quoted: CURDIR can contain spaces (a checkout under "Application Support",
# "My Documents", or any path a person actually chose). Unquoted, the shell
# splits it and every target that runs Python dies with "Permission denied".
PY := $(shell [ -x .venv/bin/python ] && echo '"$(CURDIR)/.venv/bin/python"' || echo python3)
export PYTHONPATH := $(CURDIR)/backend:$(CURDIR)
# Same reason: a space in CURDIR would split the ruff invocation below.

-include .env
export

.PHONY: up up-all down logs migrate seed run-month replay eval test check-grants \
        prove-roles export-ledger api

up:                ## start db, api and worker, and wait until healthy
	docker compose up -d --build --wait db api worker

up-all:            ## also start minio, web (A8) and fava (A7)
	docker compose --profile storage --profile web --profile ledger up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api worker

migrate:           ## schema, triggers and the four roles, as the database owner
	cd backend && $(PY) -m alembic upgrade head

seed:              ## generate the company, then ingest (lease_agent) and standardize (lease_gateway)
	$(PY) -m datagen.build
	$(PY) -m app.records.seed

eval:
	$(PY) -m datagen.build > /dev/null
	$(PY) -m eval.run

test:
	$(PY) -m pytest

check-grants:      ## assert every role's exact table privileges
	$(PY) -m pytest backend/tests/platform/test_roles.py -q

prove-roles:
	$(PY) -m app.db.prove_roles

export-ledger:     ## the books as Beancount, read as lease_reader, for Fava (profile ledger)
	$(PY) -m app.ledger.export_beancount --out data/ledger/leasedesk.beancount

replay:            ## rebuild work_item and question from audit_event; fail if they differ
	$(PY) -m app.work.replay

api:               ## the API on the host, with reload, against the Compose database
	cd backend && $(PY) -m uvicorn app.main:app --reload --port 8000

run-month:         ## M=2026-01: enqueue ingest, abstraction, checking (+ a re-check once leases are confirmed); drain
	@test -n "$(M)" || { echo "usage: make run-month M=YYYY-MM" >&2; exit 2; }
	$(PY) -m app.jobs.monthly --period $(M)
	$(PY) -m app.jobs.worker --once

# Added after the frozen list: the gateway's half of the month, run after a
# person approves. Idempotent, so running it again posts nothing.
.PHONY: post
post:              ## M=2026-01: post every APPROVED charge check of the month (as lease_gateway)
	@test -n "$(M)" || { echo "usage: make post M=YYYY-MM" >&2; exit 2; }
	$(PY) -m app.work.gateway --period $(M)

# Not part of `seed`: a known password is a dev convenience, never a default.
# Run after `make seed` to sign in as any seeded person with password `demo`
# (agents never log in). Refuses unless LEASEDESK_DEMO_MODE=1.
.PHONY: dev-passwords
dev-passwords:     ## give every seeded person the password `demo` (as lease_gateway)
	$(PY) -m app.auth.passwords set-dev-passwords

# The judge-ready local stack (A8; not part of the frozen list). Point it at a
# database of its own so it never touches your working one, e.g.
#
#   LEASEDESK_DB_PORT=5432 LEASEDESK_DB_NAME=leasedesk_demo make demo
#
# demo-data creates the database if missing, migrates, seeds, sets the dev
# passwords and runs January; all of it is idempotent, so running it again
# changes nothing. demo then serves the API on :8000 and the web app on :3000
# (live mode against the API) until Ctrl-C, which stops both.
.PHONY: demo demo-data
DEMO_MONTH ?= 2026-01
# The first run drafts the five lease versions and checks nothing against
# unconfirmed terms. With DEMO_CONFIRM=1 (the default) the Bay Area manager
# then confirms them (the same approve the lease page's Confirm button sends,
# demo mode only) and the month runs again, so the demo opens on checked
# charges. DEMO_CONFIRM=0 leaves them for you to confirm on screen.
DEMO_CONFIRM ?= 1

demo-data:         ## database (created if missing), migrate, seed, dev passwords, run DEMO_MONTH
	$(PY) -m app.db.ensure_database
	$(MAKE) migrate seed dev-passwords
	$(MAKE) run-month M=$(DEMO_MONTH)
	@if [ "$(DEMO_CONFIRM)" != "0" ]; then \
	  $(PY) -m app.work.confirm_leases --as PER-RM-BAY && $(MAKE) run-month M=$(DEMO_MONTH); \
	fi

demo: demo-data    ## demo-data, then the API on :8000 and the web app on :3000 until Ctrl-C
	@test -d frontend/node_modules || (cd frontend && npm ci)
	@echo "Lease Desk: http://localhost:3000  (sign in as dana.whitfield@northbaypt.example / demo)"
	@trap 'kill 0' INT TERM EXIT; \
	  (cd backend && $(PY) -m uvicorn app.main:app --port 8000) & \
	  (cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev) & \
	  wait

# Demo snapshots (C2; not part of the frozen list). See ops/snapshots/README.md.
#
#   LEASEDESK_DB_PORT=5432 LEASEDESK_DB_NAME=leasedesk_demo make demo-reset   # host Postgres
#   make demo-reset                                                            # Compose (:5433)
#
# demo-snapshot builds the demo-data state in a scratch database of its own
# (<db>_snapshot, dropped afterwards) and pg_dumps it to DEMO_SNAPSHOT with a
# manifest. demo-reset restores it over LEASEDESK_DB_NAME in one transaction,
# re-applies the role grants, verifies the chain and the row counts against
# the manifest and prints the time; it builds the snapshot first when it is
# missing or stale. A reset REPLACES audit_event: demo database, demo mode only.
.PHONY: demo-snapshot demo-reset
DEMO_SNAPSHOT ?= ops/snapshots/demo.dump
DEMO_SNAPSHOT_DB ?= $(or $(LEASEDESK_DB_NAME),leasedesk)_snapshot

demo-snapshot:     ## build demo-data in a scratch db, pg_dump it to DEMO_SNAPSHOT (+ manifest)
	$(PY) -m app.demo.snapshot fresh-db $(DEMO_SNAPSHOT_DB)
	$(MAKE) demo-data LEASEDESK_DB_NAME=$(DEMO_SNAPSHOT_DB) DEMO_CONFIRM=1
	$(PY) -m app.demo.snapshot dump --database $(DEMO_SNAPSHOT_DB) --out "$(DEMO_SNAPSHOT)"
	$(PY) -m app.demo.snapshot drop-db $(DEMO_SNAPSHOT_DB)

demo-reset:        ## restore DEMO_SNAPSHOT over the demo database in under 30 s (builds it if missing)
	@$(PY) -m app.demo.reset --check --snapshot "$(DEMO_SNAPSHOT)" || $(MAKE) demo-snapshot
	$(PY) -m app.demo.reset --snapshot "$(DEMO_SNAPSHOT)"

# Developer tooling (not part of the frozen list).
.PHONY: lint ci

RUFF := $(shell command -v ruff 2>/dev/null || echo $(PY) -m ruff)  # $(PY) is already quoted

lint:              ## ruff on the platform scope set in ruff.toml (pip install ruff)
	$(RUFF) check

ci: lint           ## what CI runs, locally: lint, the suite with database tests required, the eval
	$(PY) -m pytest -rs -p ci.require_db
	$(MAKE) eval

# B10 (not part of the frozen list): the demo's "Limits" beat, live. The agent
# tries to approve, a manager tries to approve their own answer, and a raw SQL
# INSERT INTO journal_entry as lease_agent: all three refused, printed from the
# audit timeline, then verify_chain(). Uses a throwaway LIMITS_DEMO item that a
# controller rejects and closes; nothing else in the database changes.
.PHONY: prove-limits
prove-limits:      ## three forbidden actions refused and on record (needs LEASEDESK_DEMO_MODE=1)
	$(PY) -m app.work.limits
