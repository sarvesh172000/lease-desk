# THE PLAN

**This is the only plan. If it is not in this file, we are not building it this weekend.**

Cal Hacks 13.0 · 36 hours · **Sarvesh = Person A** (data, documents, LLM, engines, eval) · **Jenil = Person B** (work layer, gateway, ledger, infra, frontend)

Built on Jenil's phase structure. Table names, role names, state names, make
targets and repo layout are his and do not change. Full-scope phases live in
[`roadmap/`](roadmap/) — that is **after** the hackathon, not now.

---

## Where we are

| | |
|---|---|
| **Stage** | 2 of 7 |
| **Tests** | 104 passing, all offline, no API key needed |
| **Built** | Storage, LLM layer, data generator, document pipeline |
| **Not built** | Everything Person B owns. No database, no API, no UI yet. |
| **Demo data** | 5 leases, 6 invoices, $112,759.69 billed, $25,736.36 of it wrong |

### Next task for each of us

- **Sarvesh →** abstraction agent with citations (Stage 2, last A task)
- **Jenil →** Stage 1: repo scaffolding, Postgres schema, the four DB roles

**Jenil is the critical path.** Nothing Person A has built is reachable from a
browser until the work layer and web shell exist.

---

## Status key

`DONE` · `NEXT` — start this now · `TODO` · `CUT` — decided against

---

## Stage 1 — Foundation (H0–H4)

**Gate: `make up migrate seed` works from a fresh clone and the four DB roles exist.**

| Who | Task | Status |
|---|---|---|
| B | Monorepo, Compose (`db`, `api`, `web`, `fava`), Makefile targets | **NEXT** |
| B | Postgres schema: records, golden, rulebook, work, ledger, audit | **NEXT** |
| B | `db/roles.sql` — `lease_agent`, `lease_gateway`, `lease_api`, `lease_reader` | **NEXT** |
| B | Triggers: append-only `audit_event`, hash on insert, unbalanced-journal constraint | TODO |
| A | `docs/storage.py` — content-addressed store, sha256 keys | **DONE** |
| A | `llm/client.py`, `registry.py`, `cache.py`, `usage.py` | **DONE** |
| A | `llm/untrusted.py` — documents fenced as data | **DONE** |
| A | Port `leasedesk/` into `backend/app/engine/` and `agents/` | TODO |

---

## Stage 2 — The thin slice (H4–H12)

**Gate: one lease, one January invoice, one variance, visible in a browser. Screenshot it.**

| Who | Task | Status |
|---|---|---|
| A | `datagen/company.py` — 5 clinics, 2 landlords, 2 centers | **DONE** |
| A | `datagen/leases.py` + `render_lease.py` — 8-page lease PDFs | **DONE** |
| A | `datagen/month.py` + `render_invoice.py` — January invoices, AP and bank exports | **DONE** |
| A | `docs/pipeline.py` — page text, word boxes, 150 dpi page images | **DONE** |
| A | Abstraction agent: value + page + verbatim quote per field | **NEXT** |
| B | `work/events.py` — `append_event()`, hash chain, `verify_chain()` | TODO |
| B | `work/transitions.py` — 8 states, 9 transitions, one transaction | TODO |
| B | Web shell: login, queue table, item detail skeleton | TODO |

---

## Stage 3 — The guarantees (H12–H18)

**Gate: the agent role is denied at the database, and the chain verifies.**

| Who | Task | Status |
|---|---|---|
| B | `work/roles.py` — ROLES matrix, `can()`, separation of duties | TODO |
| B | `work/gateway.py` — `post_journal()`, idempotency, APPROVED-only | TODO |
| B | Chart of accounts, trial balance, Beancount export for Fava | TODO |
| A | `docs/citations.py` — quote to bounding box, fuzzy, match score | TODO |
| A | `agents/checker.py` — **three rules, see below** | TODO |

### The checker needs three rules, not one

Running the existing engine over January proved an amount comparison catches
only 2 of the 5 errors. Pinned as tests in `backend/tests/test_month.py`.

| Rule | Catches | Why amount comparison misses it |
|---|---|---|
| Amount vs. the lease | E4, E5 | — |
| **Cardinality** per lease + period | E2 | Rent billed twice, *both copies correct*, so each one matches |
| **Premises** vs. the demised suite | E3 | Reports CLINIC-02 *underpaying* $4,880 when it was overbilled $4,820 |
| Operating expense vs. lease psf | E1 | A rent schedule says nothing about CAM |

And E6 must **not** be held: CLINIC-04's $400 step looks like an unexplained
3% jump and is exactly what the lease says. A false hold fails the eval.

---

## Stage 4 — The moment (H18–H24)

**Gate: the amendment is found, remeasured, approved, status goes green.**

| Who | Task | Status |
|---|---|---|
| A | 8–12 `.eml` threads: the real amendment, one unauthorized claim, noise, one injection | TODO |
| A | `agents/modification.py` — find the cause, propose a new `lease_version` | TODO |
| A | Source trust ranking (6 ranks) — already written into `amendment_search/v1.md` | **DONE** |
| A | Confidence from extraction score, read quality, source agreement, trust gap | TODO |
| A | Wire `remeasure.py` into the subledger, propose for controller approval | TODO |
| B | Item detail as a case file: invoice left, lease right, both boxed | TODO |
| B | Before/after schedules, entries with debits = credits shown, Approve button | TODO |
| B | Audit timeline with a "chain verified" badge | TODO |

---

## Stage 5 — Proof (H24–H30)

**Gate: `make eval` reports 6 of 6 caught, 0 false holds, chain intact.**

| Who | Task | Status |
|---|---|---|
| A | `datagen/errors.py` — the six planted errors as code | **DONE** (early) |
| A | `data/answer_key.json`, importable only from `eval/` | TODO |
| A | `eval/run.py` — caught, missed, false holds, dollars, extraction accuracy | TODO |
| A | One real EDGAR lease, hand-labelled, extraction scored separately | TODO |
| A | Adversarial: the injection email, a forged authorized-rep address | TODO |
| B | Rulebook per clinic, click through to the cited page | TODO |
| B | `make replay` rebuilds projections from `audit_event` | TODO |

---

## Stage 6 — Submission (H30–H34)

**Gate: submitted. Not drafted.**

| Who | Task | Status |
|---|---|---|
| B | Demo snapshot, `make demo-reset` under 30 seconds | TODO |
| B | Guided stepper, 3-minute path | TODO |
| A | README: setup, what is real vs simulated, assumptions, known gaps | TODO |
| A | Numbers write-up from `eval/report.json` | TODO |
| Both | Demo video, 2 minutes, opening on the dollar figure | TODO |
| Both | Devpost, naming every sponsor actually used | TODO |
| Both | Repo public, `git log -p \| grep -i "sk-ant"` clean | TODO |

---

## Stage 7 — Rehearsal (H34–H36)

**Gate: both of us can run it alone, cold, from reset.**

| Task | Status |
|---|---|
| Five rehearsals from `make demo-reset`, each presenting alone twice | TODO |
| One rehearsal with wifi off | TODO |
| The three judge questions out loud | TODO |
| Laptop: never sleep, notifications off, one browser window | TODO |

---

## The demo moment

**The hidden amendment.** CLINIC-01's rent stops matching in July; the system
finds the amendment in an email thread, remeasures under ASC 842, and asks the
controller to sign off.

Jenil's Phase 3 opens on the parking-lot double bill instead. **That needs the
CAM engine, which is cut**, so it cannot be the opener this weekend. The data
generator already sets it up — Serramonte Medical Plaza holds two Northbay
suites — so it is the first thing to build after the hackathon.

`CLINIC-01` reproduces the rehearsed Store 14 numbers exactly ($18,500 rising
3% to $19,626.65), so the **$443,255.70** remeasurement figure in the demo
script stays valid.

---

## Cut list

Cut from the top the moment a gate slips. Cut early, never halfway through.

1. EDGAR real lease
2. Beancount / Fava export
3. `make replay` equality test (keep `verify_chain()`)
4. Rulebook screen — evidence lives on the item detail anyway
5. Bounding boxes → highlight the whole paragraph instead
6. Postgres → SQLite, and the DB-role demo beat dies with it
7. Adversarial set → keep the fenced-data wrapper, drop the tests

**Never cut:** the thin slice · the hash chain · the amendment moment · the
approve gate · `eval/report.json` · the video.

### Already cut, with reasons

CAM engine and shared pools · policy engine and backtests · bitemporal rulebook
· CPI escalation · disputes and correspondence · obligations and critical dates
· human personas · full EDGAR corpus · held-out company · Fetch.ai / ASI:One ·
Azure deployment · scenario studio · chaos testing · Playwright / Locust / axe ·
job queue and business clock · CI · transactional outbox.

All of it is in [`roadmap/`](roadmap/), which is the answer to "what would you
build next."

---

## Acceptance criteria

| Criterion | Status |
|---|---|
| Fresh clone to running app with `make up migrate seed run-month M=2026-01` | TODO |
| 5 leases abstracted, every field boxed on its page | TODO |
| January catches all 5 errors and does **not** hold the correct-but-odd one | TODO |
| The amendment is found from email, remeasured, approved by the controller | TODO |
| `lease_agent` cannot insert into `journal_entry` | TODO |
| `verify_chain()` names a tampered row | TODO |
| An approver cannot approve their own answer, and the denial is logged | TODO |
| `make eval`: 6 of 6, 0 false holds, chain intact | TODO |
| Lease and invoice PDFs are byte-reproducible | **DONE** |
| Generated leases build schedules that amortize to zero | **DONE** |

---

## Working agreements

- **Separate files, always.** Sarvesh never opens `backend/app/work/` or
  `frontend/`. Jenil never opens `datagen/`, `engine/` or `agents/`.
- **Commit every 30 minutes.** Hackathon laptops die.
- **Branch per stage**, merge at each gate. `main` is always demo-ready.
- **Say "I'm stuck" at 30 minutes**, not at three hours.
- **Sleep in shifts from H18.** Four hours each, staggered.
- **Python is `./.venv/bin/python`** (3.13). ReportLab needs 3.10+ and the
  system interpreter is 3.9.
- Run the suite with plain `pytest` from the repo root.

---

## Risks

- **Stage 2's gate is not met until Jenil's half lands.** Person A is a stage
  ahead and Person B has not started. The thin slice is the floor everything
  else stands on — if H12 arrives with no browser view, stop adding backend and
  pair on the UI.
- **Postgres roles eat hours in local setup.** All grants in one `roles.sql`.
  Not working by H14 → take cut 6 and move on.
- **Sleep.** Two exhausted people make worse calls than one rested one.
