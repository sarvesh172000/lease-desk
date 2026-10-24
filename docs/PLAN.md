# Lease Desk — Cal Hacks 13.0 Execution Plan

**Budget: 70 of 500 hours (14%) · 36 wall-clock hours · Oct 23–25 2026**

This is Jenil's three-phase plan compressed to the weekend. Every table name,
role name, state name, make target and repo path below is his, unchanged —
those were declared fixed and they stay fixed. What changes is *how much* of
each phase lands and *in what order*.

- **Person A — Sarvesh:** data, documents, LLM layer, engines, eval
- **Person B — Jenil:** work layer, gateway, ledger, infra, frontend

Supersedes [`BUILD_PLAN.md`](BUILD_PLAN.md). The full-scope phases remain as the
roadmap: [Phase 1](ROADMAP_PHASE_1.md) · [Phase 2](ROADMAP_PHASE_2.md) ·
[Phase 3](ROADMAP_PHASE_3.md).

## Goal

Jenil's Phase 1 goal, held verbatim: *build the platform that every later
feature stands on, and prove it with one thin slice running end to end.* The
compression is that the thin slice comes **first** and the platform hardens
around it, rather than after 110 hours of platform. His own phrasing permits
this — the slice is the proof, so it is built as soon as there is anything to
prove.

When the weekend is done: five California clinics run January 2026 from raw
lease PDFs to posted journal entries; a planted amendment that nobody told
accounting about is caught, traced to the email that proves it, remeasured under
ASC 842 and approved by a human; every event is hash-chained; the agent process
physically cannot write to the ledger; and the whole thing is scored against an
answer key.

## What is already banked

The repo carries working, tested code that covers parts of Jenil's Phase 1
groups 9 and 10 and part of Phase 2 group 8:

| Module | Covers | State |
| --- | --- | --- |
| `leasedesk/schedule.py` | Phase 1 group 10 — charge engine | ASC 842 operating lease, amortizes to zero, tested |
| `leasedesk/remeasure.py` | Phase 2 group 8 — remeasurement | Balanced entries, tested |
| `leasedesk/reconcile.py` | Phase 1 group 10 — checker | Variance detection, tested |
| `leasedesk/extract.py` | Phase 1 group 9 — abstraction agent | Structured output, needs citations |
| `leasedesk/models.py` | Rulebook shape | `lease_version` / `lease_term` need adding |
| `tests/` | — | 16 passing, no API key needed |

Roughly 10 of Jenil's hours are already spent. Groups 9 and 10 below are
*extensions*, not builds.

## Scope

**In scope** — Phase 1 groups 1–12 at reduced depth, plus five items pulled
forward from Phase 2 because the demo moment needs them:

- Monorepo, Compose, Postgres schema, the four DB roles
- Event-sourced `audit_event` with hash chain, `transition()`, `can()`,
  separation of duties
- Gateway as the only ledger writer, idempotency, balanced-journal trigger
- Document pipeline with page images and bounding-box citations
- LLM layer with versioned prompts and a response cache
- Data generator: 1 entity, 5 clinics, 2 landlords, Jan 2026, 6 planted errors
- Abstraction agent with citations; charge engine; checker; monthly run
- Web app: queue, item detail with side-by-side evidence, rulebook, audit timeline
- Eval against the answer key
- **Pulled from Phase 2:** modification agent (the amendment), ASC 842
  subledger, source trust ranking, confidence and routing, injection defense

**Cut, with reasons** — these are the hours that do not exist:

| Cut | Phase 2/3 hours | Why |
| --- | --- | --- |
| CAM engine and shared pools | 20 | The parking-lot double bill dies with it. See *The moment* below |
| Policy engine and backtests | 24 | Needs 2025 history plus a controller loop |
| Bitemporal rulebook | 14 | Single-version rulebook is enough for one amendment |
| CPI escalation, BLS data | 8 | Fixed-step escalation demos identically |
| Disputes, correspondence, Mailpit | 12 | No outbound mail this weekend |
| Obligations and critical dates | 8 | No demo beat |
| Human personas | 10 | Unattended year-long runs are out of scope |
| Full EDGAR corpus (10 leases) | 14 | **One** real lease survives — see group 8 |
| Held-out company | part of 26 | Second seed only if H30 arrives early |
| Fetch.ai / ASI:One | 22 | A third of one person's weekend for one track |
| Azure deployment | 14 | Venue wifi is the top demo failure. Local only |
| Scenario studio, chaos, Playwright, Locust, axe | 50 | Luxuries at this scale |
| Job queue, worker, business clock | 6 | A synchronous `run_month()` is indistinguishable at 5 clinics |
| CI / GitHub Actions | 6 | `make test` run by hand |
| Transactional outbox | part of 10 | Nothing to send |

## The moment

Jenil's Phase 3 guided demo opens with the parking-lot repaving billed in full
to three clinics in one center. **That moment requires the CAM engine, which is
cut**, so it cannot be the opener this weekend.

The opener is therefore the hidden amendment, as the original concept intended:
*Store 14's rent stopped matching in July; the system finds the amendment in an
email thread, remeasures, and asks the controller to sign off.* The engine for
it already works.

Everything in this plan that is not platform exists to make that one moment
land with evidence behind it.

## Fixed decisions, unchanged from Phase 1

- **Company:** Northbay Physical Therapy. This weekend: 1 legal entity
  (California), 1 region, **5 clinics**, 2 landlords, 2 centers.
- **Seat filled:** lease accountant. The system drafts; it never pays and never
  signs off.
- **Accounting scope:** operating leases under ASC 842 only.
- **Truth model:** records are the truth about the business, events are the
  truth about the work, nothing writes to records except the gateway.
- **Model:** `claude-opus-5-5`, temperature 0, structured output via tool
  schemas. (Phase 1 said "current Claude Sonnet"; Opus is the current default
  and the reasoning quality matters on messy documents.)

## Stage plan

Seven stages, each ending in a gate. **A gate is binary — if it is not met, the
next stage does not start; the cut list opens instead.**

---

### Stage 1 — Foundation (H0–H4, 8 h)

**Gate: `make up migrate seed` works from a fresh clone, and the four DB roles
exist.**

| Who | Group | Task |
| --- | --- | --- |
| B | 1 | Monorepo in the fixed layout, Compose: `db`, `api`, `web`, `fava`. Makefile: `up`, `migrate`, `seed`, `run-month`, `replay`, `eval`, `test`, `export-ledger` |
| B | 2 | Records + golden + rulebook + work + ledger tables. Triggers: reject UPDATE/DELETE on `audit_event`, hash on insert, deferred unbalanced-journal constraint |
| B | 2 | `db/roles.sql` — `lease_agent`, `lease_gateway`, `lease_api`, `lease_reader` with exactly the grants in the Phase 1 architecture block |
| A | 6 | Storage adapter: `put(bytes) -> sha256`, `get(sha256)`, local disk |
| A | 7 | `llm/client.py`, `llm/prompts/` as versioned files, response cache keyed on (model, prompt version, inputs) |
| A | 7 | Untrusted-content wrapper — every document fenced as data with an ignore-instructions preamble |

Port the existing `leasedesk/` engine modules into `backend/app/engine/` and
`backend/app/agents/` unchanged. Do not rewrite them.

---

### Stage 2 — The thin slice (H4–H12, 16 h)

**Gate: one lease, one January invoice, one variance, visible in a browser.
Screenshot it. This is the floor you can always demo from.**

| Who | Group | Task |
| --- | --- | --- |
| A | 8 | `datagen/company.py` + `leases.py` + `render_lease.py` — 5 clinics, 2 landlords, 8–12 page lease PDFs with a real rent table |
| A | 8 | `datagen/month.py` — January 2026 invoices as PDFs, AP and bank exports as CSV |
| A | 6 | Pipeline: per-page text, word bounding boxes, 150 dpi page PNGs, `page_text` with tsvector |
| A | 9 | Abstraction agent extension: one call per lease, tool schema requiring value + page + verbatim quote per field |
| B | 3 | `events.py` — `append_event()` with the hash chain, `verify_chain()` |
| B | 3 | `transitions.py` — the eight states and nine transitions, `transition()` doing lookup, `can()`, snapshot, patch, event, projection in one transaction |
| B | 11 | Web shell: login with seeded users, queue as a filterable table, item detail skeleton |

**Both at H12:** stop and run the slice end to end in front of each other.

---

### Stage 3 — The guarantees (H12–H18, 12 h)

**Gate: the agent role is denied at the database, and the chain verifies.**

| Who | Group | Task |
| --- | --- | --- |
| B | 3 | `roles.py` — ROLES matrix, `can()` with region and entity scope, separation of duties (no actor approves what they proposed) |
| B | 4 | `gateway.post_journal(work_item, lines, idempotency_key)` — APPROVED only, balanced only, open period only. Repeat key returns the original |
| B | 4 | Chart of accounts, `ledger/trial_balance.py`, `ledger/export_beancount.py`, `make export-ledger` opening in Fava |
| A | 9 | `docs/citations.py` — quote + page to bounding box by normalized fuzzy matching, match score feeding confidence |
| A | 10 | `agents/checker.py` — compare each charge to expected, match within $1 proposes approve, mismatch proposes hold with evidence. The LLM writes only the explanation paragraph from structured facts |

**Three tests that are themselves demo beats:**

1. Connect as `lease_agent`, `INSERT INTO journal_entry` → permission denied
2. Edit an `audit_event` row with triggers off, run `verify_chain()` → names the
   broken sequence number
3. An actor approves their own proposal → 403 and a denied event in the timeline

---

### Stage 4 — The moment (H18–H24, 12 h)

**Gate: the amendment is found, remeasured, approved, and the status goes
green.**

| Who | Group | Task |
| --- | --- | --- |
| A | P2-3 | 8–12 email threads as `.eml` on disk: the real amendment from the authorized representative, one unauthorized property-manager claim, noise, one injection attempt |
| A | P2-5 | `agents/modification.py` — on divergence, search page text and emails for the cause, propose a new `lease_version` with citations |
| A | P2-9 | Source trust ranking as a table, exactly the six ranks in Phase 2. Lower-ranked contradicting higher-ranked → hold and ask, never pick |
| A | P2-9 | Confidence from extraction score, read quality, source agreement and trust gap, with the reasons listed |
| A | P2-8 | Wire `remeasure.py` into the subledger: remeasure at the modification date, adjust ROU by the same amount, propose for controller approval |
| B | 11 | Item detail as a case file: invoice page left with the billed line boxed, lease page right with the cited clause boxed, calculation centre, reason under it |
| B | 11 | Before/after schedules, proposed entries with the debits = credits assertion shown, Approve button from `GET /items/{id}/allowed-actions` |
| B | 11 | Audit timeline for any subject with a "chain verified" badge |

---

### Stage 5 — Proof (H24–H30, 12 h)

**Gate: `make eval` reports 6 of 6 caught, 0 false holds, chain intact.**

| Who | Group | Task |
| --- | --- | --- |
| A | 8 | `datagen/errors.py` — the six Phase 1 errors as code: escalation applied early, compounded vs simple, estimate above lease, duplicate rent invoice, rent for a vacated suite, one correct-but-odd charge. Plus the amendment |
| A | 8 | `data/answer_key.json`, written by the generator, importable only from `eval/`. A test fails if anything else imports it |
| A | 12 | `eval/run.py` — caught, missed, false holds, dollars flagged, extraction accuracy per field, denied attempts, chain integrity. Writes `eval/report.json` |
| A | P2-1 | **One real EDGAR lease.** Pull a single lease exhibit from SEC full-text search, hand-label 14 fields, run extraction against it, report separately |
| A | P2-15 | Adversarial: the injection email, a forged authorized-representative address. Each must produce zero unauthorized state change |
| B | 11 | Rulebook per clinic: fields, values, confidence, click to the cited page with the box highlighted |
| B | 3 | `make replay` rebuilds projections from `audit_event`; a test asserts rebuilt state equals live state |

The EDGAR lease is one hour and buys the strongest sentence available: *this is
not a lease we generated, it is a real one filed with the SEC, and the
extraction holds.*

---

### Stage 6 — Submission (H30–H34, 8 h)

**Gate: submitted. Not drafted.**

| Who | Task |
| --- | --- |
| B | Demo snapshot and `make demo-reset` restoring in under 30 seconds |
| B | Guided stepper, 3-minute path: the moment, the run, limits, proof |
| A | README: setup, architecture, what is real vs simulated, how we know, assumptions, known gaps |
| A | Microsoft-style write-up from `eval/report.json` — errors caught, dollars, false holds, straight-through rate, cost per clinic |
| Both | Demo video, 2 minutes, opening on the dollar figure |
| Both | Devpost, naming Hyphenate, Anthropic and every sponsor whose work is actually used |
| Both | Repo public, `git log -p \| grep -i "sk-ant"` clean, keys rotated |

---

### Stage 7 — Rehearsal (H34–H36, 4 h)

**Gate: both of you can run it alone, cold, from reset.**

- Five full rehearsals from `make demo-reset`, each presenting alone twice
- One rehearsal with wifi off
- The three judge questions out loud
- Laptop: never sleep, notifications off, one browser window, terminal
  pre-opened

---

## Effort

| Stage | Hours | A (Sarvesh) | B (Jenil) |
| --- | --- | --- | --- |
| 1. Foundation | 8 | 3 | 5 |
| 2. Thin slice | 16 | 9 | 7 |
| 3. Guarantees | 12 | 5 | 7 |
| 4. The moment | 12 | 7 | 5 |
| 5. Proof | 12 | 8 | 4 |
| 6. Submission | 8 | 4 | 4 |
| 7. Rehearsal | 4 | 2 | 2 |
| **Total** | **72** | **38** | **34** |

That is the entire budget with no slack, which is why the gates are binary and
the cut list below is ordered in advance.

## Cut list, in order

Cut from the top the moment a gate slips. Cut early, never halfway through.

1. EDGAR real lease
2. Beancount / Fava export
3. `make replay` equality test (keep `verify_chain()`)
4. Rulebook screen (evidence lives on the item detail anyway)
5. Bounding boxes → highlight the whole paragraph instead
6. Postgres → SQLite, and the DB-role demo beat dies with it
7. Adversarial set → keep the fenced-data wrapper, drop the tests

**Never cut:** the thin slice, the hash chain, the amendment moment, the
approve gate, `eval/report.json`, the video.

## Acceptance criteria

Straight from Jenil's Phase 1, minus what is cut:

- Fresh clone to running app with `make up migrate seed run-month M=2026-01`
- 5 leases abstracted, every field boxed on its page, confirmed by a manager
- January catches all 6 planted errors and does not hold the correct-but-odd one
- The amendment is found from email, remeasured, approved by the controller
- `lease_agent` cannot insert into `journal_entry`
- `verify_chain()` names a tampered row
- A regional manager cannot approve their own answer, and the denial is logged
- `make eval`: 6 of 6, 0 false holds, chain intact

## Risks

- **Stage 2 overruns and the slice is not up by H12.** The most likely failure.
  Mitigate by having A build the generator against the *existing* engine rather
  than a new one, and B build the UI against fixtures from hour zero.
- **Postgres roles eat hours in local setup.** Keep every grant in one
  `roles.sql`. If it is not working by H14, take cut 6 and move on.
- **The two of you block each other.** A never opens `backend/app/work/` or
  `frontend/`. B never opens `datagen/`, `engine/` or `agents/`. Agree the JSON
  shapes at H0 and neither waits.
- **Sleep.** From H18, four hours each, staggered. Two exhausted people make
  worse calls than one rested one.
