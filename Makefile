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

up:                ## start db, minio, api and worker, and wait until healthy
	docker compose up -d --build --wait db minio api worker

up-all:            ## also start web (A8) and fava (A7)
	docker compose --profile web --profile ledger up -d --build

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

api:               ## the API on the host, with reload, against the Compose database
	cd backend && $(PY) -m uvicorn app.main:app --reload --port 8000

# Frozen names whose work lands in later chunks. They fail loudly rather than
# pretend to succeed.
run-month:
	@echo "run-month M=$(M): the job queue and monthly run land in A7" && exit 1

replay:
	@echo "replay: projections rebuilt from audit_event land in A6" && exit 1

export-ledger:
	@echo "export-ledger: the Beancount export lands in A7" && exit 1
