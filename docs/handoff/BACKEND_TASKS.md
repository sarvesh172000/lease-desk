# Backend and platform work still open — 24 Oct 2026

State of the repo: everything below builds on branch `claude/a5-platform`
(PR into `main`). Once that PR is merged, branch every task from `main`.

What already works end to end on a fresh database: `make demo-data` runs
January (12 charges checked, 5 held for $25,736.36), the API is ready with a
verified audit chain, approve / uphold / pay-as-billed post through the
gateway, and policies, disputes, obligations, questions, the month summary,
"why", evidence packs, chat pairing, chaos recovery and demo reset all exist
with tests (1,569 passing).

## Who does what

| # | Task | Owner | Size |
|---|---|---|---|
| S1 | SpacetimeDB: approvals turn other screens green live (C5 gate) | **Sarvesh** | M |
| S2 | One Fetch.ai front door, registered on Agentverse (C8) | **Sarvesh** (+ Jenil's account) | M |
| S3 | Azure deployment with a judge login per role (C7) | **Sarvesh** | L |
| S4 | Anthropic effort sweep and model comparison on the eval (C6) | **Sarvesh** | M |
| S5 | LLM response cache never hits for calls with documents | **Sarvesh** (his `app/llm`) | S |
| K1 | Run disputes, obligations and reminders as part of the month | **Kiro** | S |
| K2 | Gateway posts and batches PAYMENT_RELEASE items | **Kiro** | M |
| K3 | Demo data: a Desert manager, so the cross-region refusal can be clicked | **Kiro** | S |
| K4 | Demo reset works in Docker Compose | **Kiro** | S |
| K5 | Performance target and contract tests (C4) | **Kiro** | M |
| C1 | CI: xfail counted as a database skip; SonarCloud gate | **Claude (this session)** | S |
| C2 | `docs/PLAN.md` status refresh | **Claude** | S |
| C3 | Frontend data-layer gaps (batch release, pairing hooks) + integrate the redesign | **Claude** | M |

## Rules for everyone (paste with every task)

- Never edit Sarvesh's areas unless the task is his: `datagen/`, `eval/`,
  `leasedesk/`, `backend/app/{docs,llm,agents,engine}/`,
  `backend/app/ledger/close.py`.
- Frozen names: table names, the four DB roles (`lease_agent`,
  `lease_gateway`, `lease_api`, `lease_reader`), the 8 work states, the 9
  transitions, existing make targets, the repo layout, existing API response
  shapes (add fields only, never rename or remove).
- Postgres is the source of truth. Only the gateway (`system:gateway`) posts to
  the ledger. Every state change goes through `work/transitions.py`
  `transition()` and lands in the hash-chained `audit_event`.
- New tables need a new Alembic migration chained after the current head
  (`alembic heads` must show exactly one head) and matching grants in
  `backend/app/db/roles.sql`, plus updates to `tests/platform/test_roles.py`
  and `test_schema.py`.
- Before pushing: `ruff check .` and
  `LEASEDESK_DB_PORT=5432 python -m pytest -q -p ci.require_db` from the repo
  root (Postgres 16 running; `make up` gives one on :5433).
- No secrets in git. No new PR without telling Jenil.

---

## S1 — SpacetimeDB live state (Sarvesh)

**Today:** `spacetime/` is a feed (`agent_step`, `desk_status`) written only by
`fetch/live.py` while the ASI:One agent works. The web app does not subscribe,
and approvals made in the app or API are not published.

**Gate (PLAN C5):** approve an exception in one browser window; a second
window's queue row and dashboard tiles turn green with no refresh.

**Prompt:**
> Make SpacetimeDB a live mirror of work-item state for Lease Desk.
> 1. Backend: after every successful `transition()` commit and every gateway
>    posting, publish `{exception_id/item_id, state, status, amount fields,
>    actor, at}` to the `desk_status` table via reducer `upsert_status`
>    (reuse `fetch/live.py`'s client). Do it from an outbox-style table or an
>    after-commit hook so a SpacetimeDB outage never blocks or fails an
>    approval. Off unless `SPACETIME_DB` and `SPACETIME_TOKEN` are set.
> 2. Frontend: a `useLiveStatus()` hook in `frontend/lib/` that subscribes
>    (SpacetimeDB TS SDK, version matching `spacetime/package.json`) and, on a
>    row change, invalidates the TanStack Query keys `exceptions`, `summary`,
>    `exception`, `audit`. No subscription and no error when the env vars are
>    absent (fixtures/offline demo must still work).
> 3. Test: unit test the publisher with a fake client; a Playwright script
>    with two browser contexts proving the second turns green.
> Postgres stays the source of truth; nothing reads SpacetimeDB to decide
> anything.

## S2 — One Fetch.ai front door (Sarvesh, with Jenil)

**Today:** two implementations. `fetch/` (Sarvesh: asi1-model coordinator,
SpacetimeDB feed) and `agents_fetch/` (C8: pairing by one-time code, three
agents, chat cards, cross-region refusal shown in chat and audit,
101 tests). Judges will be confused by two.

**Prompt:**
> Pick one ASI:One entry point and fold the other's best parts into it:
> keep C8's pairing (`/api/pairing/*`, `backend/app/auth/pairing.py`) so chat
> users act as a real person under `can()`, and keep `fetch/`'s asi1 intent
> planning and SpacetimeDB feed. Delete or archive the other folder. Then
> register on Agentverse (steps in `agents_fetch/README.md`: three seeds in a
> password manager, mailbox connect, manifest published), put each agent's
> name + address + the innovationlab/hackathon badges in the README, and
> verify the gate: a Desert manager paired in chat is refused on a Bay item
> and the refusal shows in `GET /api/audit`.

## S3 — Azure deployment (Sarvesh)

**Prompt:**
> Deploy Lease Desk on Azure: Azure Database for PostgreSQL Flexible Server
> (16), the API as an Azure Container App from `backend/Dockerfile`, the
> worker as a second Container App (same image, `python -m app.jobs.worker`),
> the Next.js app on Azure Static Web Apps or a Container App, documents in
> Blob Storage (`backend/app/docs/storage.py` already mentions Azure).
> Run `make migrate seed dev-passwords` then the January run against it.
> Create one judge login per role (controller, regional manager, AP clerk,
> auditor). **Set `LEASEDESK_DEMO_MODE=0`** in the shared deployment (demo
> mode lets anyone switch identity and reset the database). CORS origins =
> the web app URL. Secrets in Key Vault / Container App secrets, never in git.
> Write `docs/DEPLOY.md` with the exact commands.

## S4 — Anthropic depth (Sarvesh)

> In `eval/`, sweep `effort` (low / medium / high) and at least two models on
> the lease-abstraction and checking eval; record accuracy, false holds,
> latency, tokens and cost per clinic in `eval/report.json`; add a chart the
> frontend can show (JSON shape documented).

## S5 — LLM cache with documents (Sarvesh)

> `fence_all()` in `backend/app/llm/` draws a random nonce per call and the
> nonce is part of the cache key, so a structured call with documents never
> hits the cache — "fall back to cache during an outage" cannot work on the
> abstraction path. Derive the nonce deterministically from the content (or
> exclude it from the key). Then remove the `xfail` on
> `backend/tests/platform/test_chaos_llm.py::test_the_response_cache_hits_for_a_call_with_documents_as_is`.

---

## K1 — Disputes, obligations, reminders in the month run (Kiro)

> Repo: Lease Desk (Python 3.13, FastAPI, SQLAlchemy 2, Postgres 16). Today
> `backend/app/jobs/monthly.py` enqueues `ingest`, `abstraction`, `checking`,
> a `recheck` and `policies` for a month. The handlers `disputes`,
> `obligations` (`backend/app/jobs/obligations.py`) and `reminders`
> (`backend/app/jobs/reminders.py`) are registered in
> `backend/app/jobs/handlers.py` but nothing enqueues them, so a demo run
> shows "0 disputes drafted" even after a hold is upheld.
> Enqueue `disputes` and `obligations` after `checking`/`recheck` in
> `run_month` with idempotency keys like the existing ones
> (`job_key(entity_id, month, step)`), and enqueue `reminders` for the
> business date (the clock is in `backend/app/jobs/clock.py`). Disputes must
> only draft for holds a person upheld; check the handler's own rules before
> changing anything. Update the tests that assert the job list
> (`grep -rn "policies" backend/tests/platform | grep enqueue`), add one test
> proving `make demo-data` ends with drafted disputes and obligations, and
> keep `make chaos` passing (it compares job counts).

## K2 — PAYMENT_RELEASE posting and batching (Kiro)

> The resolver (`backend/app/work/resolver.py`, chunk B1) creates
> PAYMENT_RELEASE work items, but `backend/app/work/gateway.py` neither posts
> them nor includes them in the AP batch (`POST /api/batches/{period}/release`,
> `backend/app/api/batches.py`). Make an APPROVED PAYMENT_RELEASE post through
> the gateway exactly like an approved CHARGE_CHECK (idempotency key, balanced
> entry, outbox row for the batch), and only the gateway may do it (the DB
> trigger in `backend/app/db/sql/005_safety.sql` already enforces who may move
> to POSTED). Tests next to `backend/tests/platform/test_gateway*.py`.

## K3 — Demo data for the cross-region refusal (Kiro)

> The demo seed (the 5-lease January company) only loads one regional
> manager, `PER-RM-BAY` (`backend/app/records/golden.py` `load_actors`, from
> `company.region`). The demo's trust beat and the Fetch.ai gate need a Desert
> manager who is refused on a Bay Area item. The persona already exists in
> `backend/app/personas/people.py` (`PER-RM-DESERT`, Theo Lindqvist,
> `REG-DESERT`) and in the scaled company in `datagen/company.py` (Sarvesh's,
> do not edit). In the platform seed, also load region `REG-DESERT` and actor
> `PER-RM-DESERT` (no clinics, nothing else moves), give them a dev password
> in `make dev-passwords`, so `GET /api/auth/demo-actors` lists them and
> `POST /api/auth/demo-switch` works. `python -m eval.run` and the golden
> record tests must still pass. Verify by hand: switch to PER-RM-DESERT,
> `POST /api/exceptions/{id}/approve` on a Bay item → 403, and the refusal
> appears in `/api/audit` with `allowed=false`.

## K4 — Demo reset in Docker Compose (Kiro)

> `POST /api/demo/reset` restores a `pg_dump` snapshot with `pg_restore`, but
> `backend/Dockerfile` has no PostgreSQL 16 client, so the button fails in
> Compose. Install `postgresql-client-16` in the image, make sure the
> snapshot path (`make demo-snapshot`) is reachable from the api container
> (volume in `docker-compose.yml`), and document it in the README.
> Test: `docker compose up`, `make demo-data demo-snapshot`, press reset.

## K5 — Performance and contract tests (Kiro)

> PLAN C4 gate: a cold month (fresh DB → January posted) in under 3 minutes,
> a warm re-run in under 20 seconds; e2e and contract tests green. Add
> `make perf` that times both on a scratch database and fails over budget,
> and contract tests that call every route in `backend/app/api/` and validate
> the response against the TypeScript shapes in `frontend/lib/types.ts`
> (e.g. generate JSON Schema from the Pydantic response models and compare
> field names/types). Do not change any response shape.
