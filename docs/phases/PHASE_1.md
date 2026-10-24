# Phase 1 - Platform Core and the First Thin Slice

> **Status — this phase is Block A, chunks A1–A8.** See [`../PLAN.md`](../PLAN.md).
>
> | Group | h | Chunk | Owner | Status |
> |---|---|---|---|---|
> | 1. Repo, tooling, CI | 8 | A5 | B | Partial — repo and tests exist; no Compose, no CI |
> | 2. Data platform and DB roles | 12 | A5 | B | — |
> | 3. Event-sourced work layer | 14 | A6 | B | — |
> | 4. Gateway, outbox, ledger | 10 | A7 | B | — |
> | 5. Jobs and business clock | 6 | A7 | B | — |
> | 6. Document store and pipeline v1 | 8 | A1 | A | **Done** — `storage.py`, `pipeline.py`, `citations.py` |
> | 7. LLM layer | 8 | A1 | A | **Done** — `llm/{client,registry,cache,usage,untrusted}.py` |
> | 8. Data generator v1 and answer key | 12 | A2 | A | **Partial** — 2025 history and `answer_key.json` left |
> | 9. Abstraction agent v1 | 10 | A3 | A | **Done** — 13 cited fields |
> | 10. Charge engine and monthly run | 6 | A4 | A | **Done** — 5/5 caught, 0 false holds |
> | 11. Web app shell | 12 | A8 | B | — |
> | 12. Eval v1 and regression gate | 4 | A4 | A | **Next** |

**Budget: 110 of 500 hours (22%)**

## Goal
Build the platform that every later feature stands on, and prove it with one thin slice running end to end. The platform follows Hyphenate's blueprint but goes a level deeper: the system of work is event-sourced, so the audit trail is not a side log but the source of truth that work item state is rebuilt from. Every event is hash-chained, so tampering is detectable. Limits are enforced three times over: in `can()`, in the gateway, and in Postgres itself through separate database roles, so even a buggy agent process physically cannot write to the ledger. On top of that sits a content-addressed document pipeline with page-level citations, an LLM layer with versioned prompts, caching and cost tracking, a double-entry ledger that refuses unbalanced entries, and a job queue that runs agents in the background. When this phase is done, a five-clinic January runs from raw PDFs to posted journal entries, every planted error is caught with evidence side by side, a human approves through a role-aware UI, and the whole history can be replayed from events into an identical state.

## Scope
- In scope:
  - Monorepo, Docker Compose, CI on every push, seeded dev and test environments
  - Postgres schema for records, rulebook, work, ledger and audit, with migrations
  - Database roles and grants (agent, gateway, api, reader) as a second line of defense
  - Event-sourced work layer: `audit_event` stream, projections, state machine, `can()`, separation of duties, region scoping
  - Gateway with idempotency keys and a transactional outbox
  - Double-entry ledger with balance and period-lock enforcement, trial balance, Beancount export for Fava
  - Postgres-backed job queue, worker process and a business clock skeleton
  - Content-addressed document store and pipeline v1 (text, word boxes, page images)
  - LLM layer: client, prompt registry, response cache, token and cost log, agent run traces
  - Data generator v1 with error catalog and answer key (5 clinics, 1 legal entity, 2 landlords, 1 month)
  - Lease abstraction agent v1 with bounding-box citations and history cross-check
  - Rent and CAM-estimate engine v1, checker, monthly run
  - Web app shell with real login, role-aware actions, queue, evidence viewer, rulebook, audit timeline
  - Eval v1 and a regression eval in CI
- Out of scope (deferred to a later phase):
  - Full 30-clinic company, 3 legal entities, EDGAR leases, scans, emails, multiple invoice formats (Phase 2)
  - CAM reconciliation, CPI escalation, ASC 842, period close, bitemporal rulebook (Phase 2)
  - Resolver, confidence, routing, policy engine, disputes, critical dates, human personas (Phase 2)
  - Product polish, guided demo, scenario studio, cloud deployment, Microsoft and Fetch.ai layers (Phase 3)

## Prerequisites & Dependencies
Starting conditions:
- Two people with coding agents. **Person A (Srinidhi)** owns data, documents, LLM layer, engines and eval. **Person B** owns the work layer, gateway, ledger, infra and frontend. Both review each other's merges. Swap ownership if Person B's strengths differ.
- Budget is 500 build hours across both people and their agents. Hours below are effort, not wall clock.
- Anthropic API key. Azure subscription is optional now and used in Phase 3.
- Docker, Python 3.12, Node 20+, a shared GitHub repo with branch protection on `main`.

Fixed decisions for the whole project:
- **Company:** Northbay Physical Therapy, a fictional group of 30 clinics across California, Nevada and Arizona, organized as three legal entities (one per state) and three regions (Bay Area, Southern California, Desert). Phase 1 uses 5 California clinics.
- **Seat filled:** lease accountant. The system drafts the monthly rent and CAM run and the lease journal entries. It never pays and never signs off.
- **People it works with:** AP clerk (releases payment batches), three regional managers (own landlord relationships in their region), controller (owns the books, approves accounting judgments and policies), external auditor (read-only).
- **Accounting scope:** operating leases under ASC 842 only.
- **Truth model:** records are the truth about the business, events are the truth about the work, and nothing writes to records except the gateway.

## Tech, Tools & Components
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, psycopg 3, argon2-cffi for password hashing, signed cookie sessions
- **Database:** Postgres 16 with the `pgcrypto` extension (for the hash chain). Triggers for append-only events, balanced journals and period locks
- **Jobs:** a `job` table polled by a worker using `SELECT ... FOR UPDATE SKIP LOCKED`, so no extra broker is needed
- **Documents:** PyMuPDF for text, word bounding boxes and page images. pdfplumber as a table fallback. Files stored by SHA-256 under a storage adapter (local disk now, S3-compatible MinIO in Compose, Azure Blob in Phase 3)
- **LLM:** Anthropic Python SDK with the current Claude Sonnet model, temperature 0, structured output via tool schemas, prompts stored as versioned files
- **Ledger view:** Beancount v3 export plus Fava, so a judge can open the books in an independent, well-known ledger tool
- **Data generation:** ReportLab, Faker, a fixed random seed
- **Frontend:** Next.js (App Router), Tailwind CSS, shadcn/ui, TanStack Query and TanStack Table, react-pdf for page rendering with box highlights
- **Testing:** pytest, Hypothesis for property tests on the ledger and state machine, Playwright smoke test
- **CI:** GitHub Actions running lint, tests, migrations on a fresh database and the regression eval

### Architecture

```
SOURCES (simulated systems of record)
  lease PDFs | landlord invoices | AP export | bank export | org chart
     |
     v
INGESTION   content-addressed documents (sha256) + raw rows + sync cursors
     |      stable ids = md5(source | source_id), re-sync never duplicates
     v
RECORDS     golden tables: entity, clinic, center, landlord, lease,
            landlord_charge, payment   +   lease rulebook with citations
     |
     v
SYSTEM OF WORK (event-sourced)
  audit_event  append-only, hash-chained, the source of truth for work
     |  projected in the same transaction into
  work_item | question | lease_version confirmations | agent_run | tool_call
     ^
     |  tools are CRUD on work, every call goes through transition()
AGENTS      abstraction | checker | (Phase 2: cam, modification, resolver, policy ...)
     |
     v
GATEWAY     can() + separation of duties + materiality + period lock
            + idempotency key + transactional outbox
     |      the only writer back to records
     v
WRITES      journal (balanced by trigger) | AP payment batch | outbox mail

DB ROLES    lease_agent: read records, write events and work only
            lease_gateway: the only role with INSERT on journal_* and outbox
            lease_api: serves the UI, writes events through transition()
            lease_reader: auditor, read-only on everything
```

Repo layout, fixed for all three phases:

```
lease-desk/
  docker-compose.yml   Makefile   .github/workflows/ci.yml
  backend/
    app/
      main.py
      auth/                 login, sessions, actor resolution
      db/models.py, db/migrations/, db/roles.sql
      records/ingest.py     documents, raw rows, cursors
      records/golden.py     standardize into golden tables
      work/events.py        append_event(), hash chain, replay
      work/projections.py   event -> work_item and friends
      work/roles.py         ROLES matrix and can()
      work/transitions.py   TRANSITIONS and transition()
      work/gateway.py       post_journal(), release_batch(), send_outbox()
      ledger/               chart of accounts, posting, trial balance, beancount export
      jobs/                 queue, worker, scheduler, clock
      docs/                 storage adapter, pipeline, citations
      llm/                  client, prompts/, cache, usage
      engine/charges.py
      agents/abstraction.py   agents/checker.py
    tests/
  datagen/   eval/   frontend/   data/ (generated, gitignored)
```

## Task Breakdown

### 1. Repo, tooling and CI (8 h, Person B)
- [ ] Create the monorepo with the layout above, `.env.example`, pre-commit with ruff and prettier
- [ ] Compose services: `db`, `minio`, `api`, `worker`, `web`, `fava`
- [ ] Makefile targets: `up`, `migrate`, `seed`, `run-month M=`, `replay`, `eval`, `test`, `export-ledger`
- [ ] GitHub Actions: spin up Postgres, run migrations from empty, run pytest, run the regression eval against cached LLM responses, fail the build if eval drops below the last recorded baseline

### 2. Data platform and database roles (12 h, Person B, reviewed by A)
- [ ] Records tables: `source_document` (id, sha256, source, kind, mime, pages, storage_key, received_at), `raw_row` (id, source, source_id, payload jsonb), `sync_cursor` (source, cursor, at)
- [ ] Golden tables: `entity`, `region`, `clinic` (entity_id, region_id, center_id, suite, rsf), `center` (landlord_id, total_rsf), `landlord`, `lease` (clinic_id, landlord_id, status), `landlord_charge` (period, charge_type, amount, document_id, page, raw_ref), `payment`
- [ ] Rulebook tables: `lease_version` (lease_id, version, effective_from, confirmed_by, confirmed_at), `lease_term` (lease_version_id, field, value jsonb, document_id, page, bbox, quote, confidence, extracted_by_run)
- [ ] Work tables: `work_item`, `question`, `policy` (empty until Phase 2), `agent_run`, `tool_call`, `job`
- [ ] Ledger tables: `account` (chart of accounts per entity), `journal_entry` (entity_id, date, period, memo, idempotency_key unique, work_item_id), `journal_line` (account_id, debit, credit, clinic_id), `period` (entity_id, status)
- [ ] `outbox` (kind, payload, idempotency_key unique, status, sent_at)
- [ ] `audit_event` (seq bigserial, at, actor_id, action, subject_type, subject_id, allowed, reason, diff jsonb, evidence jsonb, policy_ref, model_ref, prev_hash, hash)
- [ ] Triggers: reject UPDATE and DELETE on `audit_event`. Compute `hash = sha256(prev_hash || canonical row)` on insert. Deferred constraint that rejects unbalanced journal entries. Reject inserts into a closed period
- [ ] `db/roles.sql`: create the four roles and grant exactly what the architecture section says. The worker connects as `lease_agent`, the gateway module opens its own connection as `lease_gateway`

### 3. Event-sourced work layer (14 h, Person B)
- [ ] `events.py`: `append_event()` writes one hash-chained row. `verify_chain()` walks the stream and reports the first broken link
- [ ] `projections.py`: pure functions from event to projection updates for `work_item`, `question` and `lease_version` confirmations, applied in the same transaction as the event
- [ ] `roles.py`: ROLES maps role to resource kind to allowed actions. `can(actor, action, resource)` checks role, region scope for regional managers, entity scope, and separation of duties (no actor approves an item they proposed or answered)
- [ ] `transitions.py`: states NEW, PROPOSED, NEEDS_INFO, HELD, APPROVED, REJECTED, POSTED, CLOSED. Transitions: propose, ask, answer, hold, resume, approve, reject, post, close. Anything not in the table is impossible, not just disallowed
- [ ] `transition()` does lookup, `can()`, snapshot, patch, event append, projection, all in one transaction. Denied attempts append an event with `allowed = false` and then raise
- [ ] `make replay` truncates projections and rebuilds them from `audit_event`. A test asserts the rebuilt state equals the live state byte for byte
- [ ] Hypothesis property tests: random sequences of actions never reach an illegal state, never let an actor approve their own proposal, and never break the hash chain

### 4. Gateway, outbox and ledger (10 h, Person B)
- [ ] Chart of accounts per entity: Cash, Accounts payable, Prepaid rent, ROU asset (operating), Lease liability (operating, current and non-current), Lease cost, CAM expense, Property tax expense, Insurance expense, Late fees and penalties, Landlord receivable (disputes)
- [ ] `post_journal(work_item, lines, idempotency_key)`: only APPROVED items, balanced lines, open period, then POSTED. A repeated key returns the original entry instead of posting twice
- [ ] `release_batch(period, actor)`: only an AP clerk, only approved payment items, writes an AP payment batch CSV through the outbox
- [ ] `send_outbox()`: delivers outbox rows (files now, Mailpit email in Phase 2), marks them sent, never sends twice
- [ ] `ledger/trial_balance.py` and `ledger/export_beancount.py`. `make export-ledger` writes a `.beancount` file that Fava opens
- [ ] Tests: agent role cannot insert into `journal_entry` even with raw SQL, unbalanced entry fails at commit, closed period rejects, duplicate idempotency key posts once

### 5. Jobs and business clock (6 h, Person B)
- [ ] `job` table with kind, payload, status, attempts, run_after, locked_by. Worker loop with SKIP LOCKED, exponential backoff, dead-letter after N attempts
- [ ] `clock.py` with a stored business date and `run_month(entity, period)` that enqueues ingest, abstraction, checking, in order, with job dependencies
- [ ] Jobs are idempotent: running a month twice produces no new work items or entries

### 6. Document store and pipeline v1 (8 h, Person A)
- [ ] Storage adapter with `put(bytes) -> sha256` and `get(sha256)`, local and MinIO backends
- [ ] Pipeline: detect type, extract text per page with word bounding boxes, render page PNGs at 150 dpi for the viewer and for later vision use, store a `page_text` table with tsvector for search
- [ ] `docs/citations.py`: given a quote and a page, find the best matching span with normalized fuzzy matching and return its bounding box. Return a match score that feeds confidence

### 7. LLM layer (8 h, Person A)
- [ ] `llm/client.py`: one function per task type, tool-schema structured output, timeouts and retries, temperature 0
- [ ] `llm/prompts/`: each prompt is a versioned file. The prompt id and version are written into `agent_run` and every resulting event's `model_ref`
- [ ] Response cache keyed by hash of (model, prompt version, inputs). Cache hits are logged as such
- [ ] Usage log: input and output tokens and estimated cost per call, per run and per clinic, so Phase 3 can report cost per clinic per month
- [ ] Untrusted-content wrapper: every document or email passed to the model is fenced as data with an instruction that it may contain instructions to ignore

### 8. Data generator v1, error catalog and answer key (12 h, Person A)
- [ ] `datagen/company.py`: seeded generator for entity, region, 5 clinics, 2 landlords, 2 centers (one center holds 2 clinics, set up for the Phase 2 double billing case), org chart with named regional manager, AP clerk, controller
- [ ] `datagen/leases.py`: lease terms (dates, RSF, base rent schedule, fixed percent or fixed step escalation, CAM estimate, deposit, renewal option) and `render_lease.py` producing 8 to 12 page PDFs with realistic sections and a rent table
- [ ] `datagen/history.py`: all of 2025 invoices and payments, mostly correct
- [ ] `datagen/month.py`: January 2026 invoices as PDFs, AP and bank exports as CSV
- [ ] `datagen/errors.py`: the error catalog as code. Each entry: id, type, clinic, period, billed, correct, the lease field and page that proves it, expected route and expected outcome. Phase 1 plants 6: escalation applied early, compounded vs simple escalation, CAM estimate above lease, duplicate rent invoice, rent for a suite the clinic left, and one correct-but-odd charge
- [ ] `data/answer_key.json` is written by the generator and readable only by `eval/`. A test fails if any module outside `eval/` imports it

### 9. Lease abstraction agent v1 (10 h, Person A)
- [ ] Field schema: commencement, expiration, RSF, base rent schedule, escalation type, rate and dates, CAM estimate, security deposit, renewal options (count, length, notice days)
- [ ] One call per lease with page-numbered text. The tool schema requires value, page and verbatim quote for every field
- [ ] Citation check through `docs/citations.py`. Missing or weak matches lower confidence and are flagged
- [ ] History cross-check: replay the extracted rent schedule over 2025 and compare to actual payments. Disagreement opens a LEASE_ABSTRACTION work item with both sources, never a silent pick
- [ ] Draft becomes `lease_version` 1. A regional manager confirms it through `transition()`. Unconfirmed leases are never used by the checker

### 10. Charge engine v1 and the monthly run (6 h, Person A, wired by B)
- [ ] `engine/charges.py`: deterministic, no LLM. Expected base rent and CAM estimate for a clinic and period, returning the amount and the `lease_term` ids used
- [ ] `agents/checker.py`: for each landlord charge, compare to expected. Match within $1 proposes approve. Any mismatch proposes hold with evidence (invoice document, page and box, lease terms, calculation) and a reason. The LLM only writes the one-paragraph explanation from structured facts
- [ ] Approved rent items produce the cash and AP lines. Lease accounting entries arrive in Phase 2, so Phase 1 posts rent as Dr Lease cost, Cr AP, clearly marked as a placeholder entry type

### 11. Web app shell (12 h, Person B)
- [ ] Login with seeded users per role. A demo-only role switcher exists behind a `DEMO_MODE` flag
- [ ] Queue: TanStack Table with filters by state, clinic, region, period, and counts at the top
- [ ] Item detail: invoice page on the left with the billed line boxed, lease page on the right with the cited clause boxed, calculation in the middle, reason under it. Action buttons render from a `GET /items/{id}/allowed-actions` endpoint that calls `can()`
- [ ] Rulebook per clinic: fields, values, confidence, and a click that opens the cited page with the box highlighted
- [ ] Audit timeline for any subject, plus a "chain verified" badge from `verify_chain()`

### 12. Eval v1 and regression gate (4 h, Person A)
- [ ] `eval/run.py`: compare final states with the answer key. Report caught, missed, false holds, dollars flagged, extraction accuracy per field, denied attempts, chain integrity
- [ ] Write `eval/report.json` and append a line to `eval/history.csv`. CI compares to the stored baseline

## Deliverables / Definition of Done
- Fresh clone to running app with `make up migrate seed run-month M=2026-01` and nothing else
- 5 leases abstracted with every field boxed on its page, confirmed by a regional manager
- January run catches all 5 errors and does not hold the correct-but-odd charge
- Regional manager approves, AP clerk releases the batch, gateway posts balanced entries, Fava shows them
- `make replay` reproduces identical state, `verify_chain()` passes, all role and property tests pass
- CI is green and enforces the eval baseline

## Acceptance Criteria / How to Verify
- Connect to Postgres as `lease_agent` and try `INSERT INTO journal_entry ...`: permission denied
- Edit any `audit_event` row as superuser with triggers disabled, then run `verify_chain()`: it names the broken sequence number
- As the regional manager for Bay Area, call approve on a Desert item through the API: 403, and a denied event appears in the timeline
- Run January twice: zero new items, entries or outbox rows on the second run
- Open the duplicate invoice item: both invoices boxed side by side, the lease rent clause boxed, reason names the duplicate
- Eval: 5 of 5 caught, 0 false holds, chain intact, 100% of denied attempts logged

## Risks & Mitigations
- **Event sourcing adds friction early.** Projections out of sync with events would be worse than no event sourcing. Mitigate by keeping projections as small pure functions, applying them in the same transaction, and running the replay-equality test in CI from the first day.
- **Database roles break local development.** Wrong grants cause confusing failures. Mitigate by keeping all grants in one `roles.sql`, adding a `make check-grants` test that asserts each role's exact permissions, and documenting which module uses which connection.
- **Citation boxes misaligned with what the model quoted.** Mitigate with normalized fuzzy matching, a match score exposed in confidence, and a fallback to highlighting the best paragraph when no tight span matches.

## Estimated Effort

| Task group | Hours | Share of phase | Share of project |
|---|---|---|---|
| 1. Repo, tooling, CI | 8 | 7% | 1.6% |
| 2. Data platform and DB roles | 12 | 11% | 2.4% |
| 3. Event-sourced work layer | 14 | 13% | 2.8% |
| 4. Gateway, outbox, ledger | 10 | 9% | 2.0% |
| 5. Jobs and clock | 6 | 5% | 1.2% |
| 6. Document pipeline v1 | 8 | 7% | 1.6% |
| 7. LLM layer | 8 | 7% | 1.6% |
| 8. Data generator v1 and answer key | 12 | 11% | 2.4% |
| 9. Abstraction agent v1 | 10 | 9% | 2.0% |
| 10. Charge engine and monthly run | 6 | 5% | 1.2% |
| 11. Web app shell | 12 | 11% | 2.4% |
| 12. Eval v1 and regression gate | 4 | 4% | 0.8% |
| **Phase 1 total** | **110** | **100%** | **22%** |

Split by person: roughly 48 hours Person A (groups 6 to 10 and 12), roughly 62 hours Person B (groups 1 to 5 and 11). Person A uses the gap to start the EDGAR search and labels early, which pulls Phase 2 group 1 forward without making Phase 1 depend on it.

## Handoff to Next Phase
A platform where the hard guarantees already hold: records sync idempotently, every change is a hash-chained event, state can be rebuilt from history, the agent process cannot touch the ledger even if it tried, the gateway is the only writer, documents carry page-level citations, every LLM call is versioned, cached and costed, and an eval gate protects quality in CI. Phase 2 adds the company, the mess and the intelligence on top of this without changing its shape. Table names, role names, state names, make targets and the repo layout above are fixed from here on.
