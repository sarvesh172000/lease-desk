# Lease Desk. Target names are frozen (docs/phases/PHASE_1.md, group 1).
#
#   make up migrate seed      a fresh clone to a seeded database
#   make test                 the whole suite (database tests run when `make up` is)
#   make prove-roles          the database refusing every forbidden write

PY := $(shell [ -x .venv/bin/python ] && echo $(CURDIR)/.venv/bin/python || echo python3)
export PYTHONPATH := $(CURDIR)/backend:$(CURDIR)

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

api:               ## the API on the host, with reload, against the Compose database
	cd backend && $(PY) -m uvicorn app.main:app --reload --port 8000

run-month:         ## M=2026-01: enqueue ingest, abstraction, checking; run the worker until drained
	@test -n "$(M)" || { echo "usage: make run-month M=YYYY-MM" >&2; exit 2; }
	$(PY) -m app.jobs.monthly --period $(M)
	$(PY) -m app.jobs.worker --once

# Frozen names whose work lands in later chunks. They fail loudly rather than
# pretend to succeed.

replay:
	@echo "replay: projections rebuilt from audit_event land in A6" && exit 1

# Not part of `seed`: a known password is a dev convenience, never a default.
# Run after `make seed` to sign in as any seeded person with password `demo`
# (agents never log in). Refuses unless LEASEDESK_DEMO_MODE=1.
.PHONY: dev-passwords
dev-passwords:     ## give every seeded person the password `demo` (as lease_gateway)
	$(PY) -m app.auth.passwords set-dev-passwords

# Developer tooling (not part of the frozen list).
.PHONY: lint ci

RUFF := $(shell command -v ruff 2>/dev/null || echo $(PY) -m ruff)

lint:              ## ruff on the platform scope set in ruff.toml (pip install ruff)
	$(RUFF) check

ci: lint           ## what CI runs, locally: lint, the suite with database tests required, the eval
	$(PY) -m pytest -rs -p ci.require_db
	$(MAKE) eval
