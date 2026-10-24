# THE PLAN

**Jenil's three-phase plan, 500 hours, in full.** This file is the index and the
status board; the phase files hold the task detail.

**Sarvesh = Person A** — data, documents, LLM layer, engines, eval
**Jenil = Person B** — work layer, gateway, ledger, infra, frontend

| | |
|---|---|
| [Phase 1](phases/PHASE_1.md) | 110 h · Platform core and the first thin slice |
| [Phase 2](phases/PHASE_2.md) | 250 h · The company, the mess and the full autonomous loop |
| [Phase 3](phases/PHASE_3.md) | 140 h · Polish, hardening and multi-track delivery |

Names are fixed from Phase 1 and do not change: tables, the four DB roles, the
eight work states, make targets, repo layout.

---

## Where we are

| | |
|---|---|
| **Done** | ~44 of 110 Phase 1 hours, plus five Phase 2 groups started early |
| **Tests** | 174 passing, all offline, no API key needed |
| **Demo path** | Runs end to end in code: variance → search → amendment → $443,255.70 balanced entries |
| **Not built** | Everything Person B owns. No database, no gateway, no API, no UI. |

### Next

- **Sarvesh →** Phase 1 group 12 (eval + answer key), then finish group 8 (2025 history)
- **Jenil →** Phase 1 groups 1–5: Compose, Postgres schema, DB roles, event layer, gateway

**Jenil is the critical path.** Nothing Person A has built is reachable from a
browser until the work layer and web shell exist.

---

## Phase 1 — Platform core (110 h)

| # | Group | h | Owner | Status |
|---|---|---|---|---|
| 1 | Repo, tooling, CI | 8 | B | Partial |
| 2 | Data platform and DB roles | 12 | B | — |
| 3 | Event-sourced work layer | 14 | B | — |
| 4 | Gateway, outbox, ledger | 10 | B | — |
| 5 | Jobs and business clock | 6 | B | — |
| 6 | Document store and pipeline v1 | 8 | A | **Done** |
| 7 | LLM layer | 8 | A | **Done** |
| 8 | Data generator v1 and answer key | 12 | A | **Mostly** — 2025 history, `answer_key.json` left |
| 9 | Abstraction agent v1 | 10 | A | **Done** |
| 10 | Charge engine and monthly run | 6 | A | **Done** |
| 11 | Web app shell | 12 | B | — |
| 12 | Eval v1 and regression gate | 4 | A | **Next** |

## Phase 2 — The company and the mess (250 h)

| # | Group | h | Owner | Status |
|---|---|---|---|---|
| 1 | Real lease corpus from EDGAR | 14 | A | — |
| 2 | Company generator v2 and held-out company | 26 | A | — |
| 3 | Messy inputs | 16 | A | **Partial** — emails done; scans, tracker, 3 invoice formats left |
| 4 | Document understanding at full mess | 20 | A | — |
| 5 | Bitemporal rulebook and lease changes | 14 | B/A | **Partial** — modification agent done |
| 6 | CAM engine and shared pools | 20 | A | — |
| 7 | Rent engine v2 with CPI | 8 | A | — |
| 8 | ASC 842 subledger and period close | 26 | A | **Partial** — remeasurement done |
| 9 | Resolver | 20 | B/A | **Partial** — trust ranking + confidence done |
| 10 | Policy engine | 24 | B | — |
| 11 | Disputes and correspondence | 12 | B | — |
| 12 | Obligations and critical dates | 8 | B | — |
| 13 | Human personas | 10 | A | — |
| 14 | Why, auditor, evidence packs | 10 | B | — |
| 15 | Safety and defense in depth | 8 | B | **Partial** — fencing + 4 adversarial tests |
| 16 | Eval v2, held-out, counterfactual replay | 14 | A | — |

## Phase 3 — Polish and delivery (140 h + 26 h added)

| # | Group | h | Owner | Status |
|---|---|---|---|---|
| 1 | Product design and UI polish | 22 | B | — |
| 2 | Guided demo, summaries, snapshots | 12 | B | — |
| 3 | Scenario studio | 12 | B | — |
| 4 | Reliability and chaos testing | 14 | A+B | — |
| 5 | Performance and cost | 8 | A | — |
| 6 | Testing and QA | 12 | A+B | — |
| 7 | Cloud deployment and ops (Azure) | 14 | B | — |
| 8 | **Microsoft** deliverables | 10 | A | — |
| 9 | **Fetch.ai** / ASI:One front door | 22 | B | — |
| 10 | Submission package and rehearsals | 14 | A+B | — |
| **11** | **SpacetimeDB** live layer *(added)* | **14** | **B** | — |
| **12** | **Anthropic** depth *(added)* | **12** | **A** | — |

Groups 11 and 12 are new, specified in [`SPONSORS.md`](SPONSORS.md). Total
becomes **526 hours**.

---

## Sponsor targets

Five, all specified in [`SPONSORS.md`](SPONSORS.md):

| Sponsor | Where it lands | Owner |
|---|---|---|
| **Hyphenate** | Positioning — no public API. The whole product is the pitch | Both |
| **Anthropic** | Phase 3 group 12 — effort tuning, caching, cost per clinic, the determinism story | A |
| **SpacetimeDB** | Phase 3 group 11 — audit trail as database state, live multi-viewer sync | B |
| **Microsoft** | Phase 3 groups 7 + 8 — Azure deployment and the production path | B then A |
| **Fetch.ai** | Phase 3 group 9 — ASI:One front door, three registered agents | B |

---

## What already exists

Built and tested, mapped to Jenil's groups:

| Module | Group | What it does |
|---|---|---|
| `app/docs/storage.py` | P1-6 | Content-addressed store, sha256 keys |
| `app/docs/pipeline.py` | P1-6 | Page text, word boxes, 150 dpi images |
| `app/docs/citations.py` | P1-6 | Quote → box, fuzzy, match score |
| `app/llm/*` | P1-7 | Client, versioned prompts, cache, usage, untrusted fencing |
| `datagen/company,leases,render_lease` | P1-8 | 5 clinics, 2 landlords, 8-page lease PDFs |
| `datagen/month,render_invoice` | P1-8 | January invoices, AP and bank exports |
| `datagen/errors.py` | P1-8 | Six planted errors with proofs |
| `datagen/emails.py` | P2-3 | 10 threads: amendment, forged sender, injection, noise |
| `app/agents/abstraction.py` | P1-9 | 13 cited fields, verified against the page |
| `app/engine/charges.py` | P1-10 | What the lease supports, deterministic |
| `app/agents/checker.py` | P1-10 | Three rules — 5/5 caught, 0 false holds |
| `app/agents/trust.py` | P2-9 | Six-rank source ranking |
| `app/agents/modification.py` | P2-5 | Finds the cause, proposes a version |
| `app/engine/remeasurement.py` | P2-8 | Revised terms → balanced entries |

---

## Working agreements

- **Separate files.** Sarvesh never opens `backend/app/work/` or `frontend/`.
  Jenil never opens `datagen/`, `engine/` or `agents/`.
- **Commit every 30 minutes.** `main` is always demo-ready.
- **Python is `./.venv/bin/python`** (3.13). Run tests with plain `pytest`.
- **The contract** is in [`DESIGN.md`](DESIGN.md) §16. Build screens against the
  fixtures; do not wait for the API.
- **Say "I'm stuck" at 30 minutes**, not at three hours.

## Standing risks

- **Person B has not started.** Four phases of backend are worth nothing a
  judge can see. If the gap widens, Person A stops and pairs on the UI.
- **Everything runs against a fake model client.** The system is proven against
  what a model returns, not that Claude returns it. One real API run settles it.
- **Scope is 526 hours.** It is reachable at agent throughput, and only at
  agent throughput. The cut order in each phase file still applies if it slips.
