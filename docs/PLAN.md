# THE PLAN

Jenil's 500-hour plan, broken into **27 chunks across 3 blocks**. Same work,
same task-group numbering — just small enough that each one can be finished and
made solid before the next starts.

**Sarvesh = Person A** · data, documents, LLM, engines, eval
**Jenil = Person B** · work layer, gateway, ledger, infra, frontend

Task detail lives in the phase files: [Phase 1](phases/PHASE_1.md) ·
[Phase 2](phases/PHASE_2.md) · [Phase 3](phases/PHASE_3.md). Names fixed in
Phase 1 — tables, the four DB roles, the eight work states, make targets, repo
layout — do not change.

---

## The bar for "done"

A chunk is not done when the code exists. It is done when **all four** hold:

1. **Its gate passes** — the one-line check in its row below.
2. **Tests cover it**, and the whole suite is green.
3. **It survives a bad input** — an empty corpus, a missing field, a wrong
   number, a hostile document.
4. **It is committed and pushed.**

Half-finished chunks are what sink a plan this size. Finish one, make it solid,
then move.

---

## Where we are

| | |
|---|---|
| **Complete** | **A1–A4 (all of Person A's Block A)** · 48 of 526 hours |
| **Partial** | B1, B3, B5, B10 (started early for the demo moment) |
| **Tests** | 254 passing, offline, no API key · `python -m eval.run` passes |
| **Next (Sarvesh)** | **B2** — error catalog v2 (~60 errors) and the 2026 year |
| **Next (Jenil)** | **A5** — Compose, Postgres schema, the four DB roles |

**Jenil is the critical path.** A1–A4 are backend no judge can see until A5–A8
land.

---

## Block A — Foundations (110 h, Jenil's Phase 1)

| # | Chunk | h | Owner | Covers | Gate | Status |
|---|---|---|---|---|---|---|
| **A1** | Document & LLM substrate | 16 | A | P1 g6, g7 | A PDF goes in, page text and word boxes come out; a prompt call is versioned, cached and fenced | **DONE** |
| **A2** | The generated world | 12 | A | P1 g8 | `make seed` produces 5 leases, a billing month and the answer key, byte-reproducibly | **DONE** |
| **A3** | Reading leases | 10 | A | P1 g9 | 13 fields extracted, every one cited to a box, invented quotes rejected | **DONE** |
| **A4** | Checking charges | 10 | A | P1 g10, g12 | `make eval` reports 5/5 caught, 0 false holds, from a fresh clone | **DONE** |
| **A5** | Platform & database | 20 | B | P1 g1, g2 | `make up migrate seed` from a fresh clone; `lease_agent` denied on `journal_entry` | — |
| **A6** | Work layer & permissions | 14 | B | P1 g3 | `verify_chain()` names a tampered row; nobody approves their own proposal | — |
| **A7** | Gateway & ledger | 16 | B | P1 g4, g5 | Only the gateway posts; unbalanced entries rejected; Fava opens the books | — |
| **A8** | The thin slice | 12 | B | P1 g11 | One variance visible in a browser, with its evidence, end to end | — |

**Block A gate:** a January run goes from lease PDFs to posted entries, a human
approves in the UI, and the eval scores it. *This is the floor everything else
stands on.*

---

## Block B — The autonomous loop (250 h, Jenil's Phase 2)

| # | Chunk | h | Owner | Covers | Gate | Status |
|---|---|---|---|---|---|---|
| **B1** | Lease changes & resolver | 34 | A+B | P2 g5, g9 | A variance finds its cause, ranks sources, routes to the right person | **Partial** — modification + trust done |
| **B2** | Company at scale | 26 | A | P2 g2 | 30 clinics, 3 entities, 2025 history, held-out company from another seed | **Partial** — structure + held-out done; error catalog v2 and full 2026 left |
| **B3** | The mess | 36 | A | P2 g3, g4 | Scans, 3 invoice formats, the previous accountant's spreadsheet, all parsed | **Partial** — emails done |
| **B4** | CAM & CPI | 28 | A | P2 g6, g7 | The parking-lot line billed to two suites is caught; CPI escalations tie to BLS | — |
| **B5** | ASC 842 & close | 26 | A | P2 g8 | Subledger ties to GL to the cent; the month closes and locks | **Partial** — remeasurement done |
| **B6** | Policies | 24 | B | P2 g10 | A policy is learned, backtested, approved, and cited on a later decision | — |
| **B7** | Disputes & obligations | 20 | B | P2 g11, g12 | A dispute letter goes out, a credit memo clears it, a renewal date fires | — |
| **B8** | Proof | 28 | A | P2 g1, g16 | Real EDGAR leases scored separately; held-out company scored next to dev | — |
| **B9** | Personas & explainability | 20 | A+B | P2 g13, g14 | A year runs unattended; "why was this held?" answers with rows | — |
| **B10** | Safety | 8 | B | P2 g15 | Every adversarial case produces zero unauthorized state change | **Partial** — fencing + 4 tests |

**Block B gate:** all of 2026 runs month by month with no human at the keyboard,
every month closes, and the held-out company scores ≥90% caught with <3% false
holds.

---

## Block C — Ship (166 h, Jenil's Phase 3 + two sponsor groups)

| # | Chunk | h | Owner | Covers | Gate | Status |
|---|---|---|---|---|---|---|
| **C1** | Product polish | 22 | B | P3 g1 | Every screen readable on a projector at 1280 wide, Today screen per role | — |
| **C2** | Demo & studio | 24 | B | P3 g2, g3 | `make demo-reset` in under 30 s; 10 judge scenarios behave | — |
| **C3** | Reliability & chaos | 14 | A+B | P3 g4 | Kill the worker mid-run: it finishes with identical results | — |
| **C4** | Performance & QA | 20 | A+B | P3 g5, g6 | Cold month under 3 min, warm under 20 s; e2e and contract tests green | — |
| **C5** | **SpacetimeDB** | 14 | B | P3 g11 *(new)* | Approve in one window, another turns green with no refresh | — |
| **C6** | **Anthropic** depth | 12 | A | P3 g12 *(new)* | Effort sweep and model comparison measured on the eval; cost per clinic charted | — |
| **C7** | **Azure & Microsoft** | 24 | B+A | P3 g7, g8 | Deployed with a judge account per role; every number traces to `eval/report.json` | — |
| **C8** | **Fetch.ai** / ASI:One | 22 | B | P3 g9 | Three agents registered; a cross-region answer is denied and the denial is logged | — |
| **C9** | Ship | 14 | A+B | P3 g10 | Submitted, with five rehearsals done and one offline | — |

**Block C gate:** submitted on every target track, with a rehearsed demo that
runs offline.

---

## Sponsors

Five targets, each with a home. Full strategy in [`SPONSORS.md`](SPONSORS.md).

| Sponsor | Chunk | Owner |
|---|---|---|
| **Hyphenate** | Positioning — the whole product; no API to integrate | Both |
| **SpacetimeDB** | C5 | B |
| **Anthropic** | C6 (foundation already in A1) | A |
| **Microsoft** | C7 | B then A |
| **Fetch.ai** | C8 | B |

Confirm prize criteria at the booths in hour one, even though the work is in
Block C. [`SPONSORS.md`](SPONSORS.md) has the booth plan.

---

## Order

Block A before B before C, with two standing exceptions:

- **B1, B3, B5 and B10 were started early** because the demo moment needed the
  amendment, the mailbox, trust ranking and the remeasurement.
- **Sponsor conversations happen in hour one**, even though C5–C8 come last.

Within a block, Person A and Person B chunks run in parallel. A chunk that
depends on the other person's work says so in its gate.

---

## What already exists

| Module | Chunk | What it does |
|---|---|---|
| `app/docs/storage.py` | A1 | Content-addressed store, sha256 keys |
| `app/docs/pipeline.py` | A1 | Page text, word boxes, 150 dpi images |
| `app/docs/citations.py` | A1 | Quote → box, fuzzy, match score |
| `app/llm/*` | A1 | Client, versioned prompts, cache, usage, untrusted fencing |
| `datagen/company,leases,render_lease` | A2 | 5 clinics, 2 landlords, 8-page lease PDFs |
| `datagen/month,render_invoice` | A2 | January invoices, AP and bank exports |
| `datagen/errors.py` | A2 | Six planted errors with proofs |
| `app/agents/abstraction.py` | A3 | 13 cited fields, verified against the page |
| `app/engine/charges.py` | A4 | What the lease supports, deterministic |
| `app/agents/checker.py` | A4 | Three rules — 5/5 caught, 0 false holds |
| `datagen/emails.py` | B3 | 10 threads: amendment, forged sender, injection, noise |
| `app/agents/trust.py` | B1 | Six-rank source ranking |
| `app/agents/modification.py` | B1 | Finds the cause, proposes a version |
| `app/engine/remeasurement.py` | B5 | Revised terms → balanced entries |

---

## Working agreements

- **Separate files.** Sarvesh never opens `backend/app/work/` or `frontend/`.
  Jenil never opens `datagen/`, `engine/` or `agents/`.
- **One chunk at a time.** Finish it to the four-point bar before starting the next.
- **Commit every 30 minutes.** `main` is always demo-ready.
- **Python is `./.venv/bin/python`** (3.13). Tests: plain `pytest` from the root.
- **The API contract** is [`DESIGN.md`](DESIGN.md) §16. Build screens against
  the fixtures; never wait for the API.

## Standing risks

- **Person B has not started.** Four chunks of backend are worth nothing a judge
  can see. If the gap widens, Person A stops and pairs on A5–A8.
- **Everything runs against a fake model client.** Proven against what a model
  returns, not that Claude returns it. One real API run settles it — do it
  before B2.
- **526 hours is reachable only at agent throughput.** Measured so far: ~26
  hours of chunks in ~4 hours wall clock. If that rate drops, cut from the back
  of Block B, not from Block A.
