# Lease Desk

**Cal Hacks 13.0** · autonomous lease accounting for multi-location businesses

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Lease Desk fills the **lease accountant's** seat, and checks every rent bill
before the **AP clerk** pays it. It reads each lease, builds the ASC 842
schedules, checks every landlord charge against what the lease actually says,
holds only the money that is wrong, and when something doesn't match, goes
looking in the mailbox for why. It never pays and never signs off: a person
approves, under role checks, and every action is written to a hash-chained
audit trail.

**Try it live:** https://lease-desk-ten.vercel.app. Sign in as
`priya.raghunathan@northbaypt.example`, password `demo` (the controller), and
open the July hold on LEASE-01. The web app is on Vercel; the API, worker,
Postgres and the Fetch.ai agents run on Azure.

## The moment

> **$443,255.70 was missing from the balance sheet.** STORE-01's lease was
> amended in June: three more years, lower rent. The amendment went to
> facilities and never reached accounting. In July the landlord billed the new
> rent, and the books kept running the old schedule.

This runs live in the app, from `make demo-data`:

1. **The break.** July's rent is billed **$17,400.00**; the schedule says
   **$19,626.65**. The checker holds the $2,226.65 difference and cites the
   lease clause it rests on.
2. **The search.** *Run investigation* searches the mailbox (10 documents) and
   finds the amendment email from the landlord, trust rank 1: *"Base rent
   reduced to $17,400 per month effective July 1, 2026."*
3. **The proof.** The engine remeasures the lease: liability
   **$559,665.35 → $1,002,921.05 (+$443,255.70)**, ROU asset +$443,255.70.
4. **The entries.** Four adjusting entries, **balanced**, proposed for the
   controller's sign-off. Nothing posts until a person approves.

| Account | Debit | Credit |
|---|---:|---:|
| Lease liability | | 443,255.70 |
| ROU asset | 443,255.70 | |
| ROU asset | 4,624.74 | |
| Rent expense | | 4,624.74 |
| | **447,880.44** | **447,880.44** |

The model's answers behind this are committed (`data/reference/llm_cache`), so
the whole story replays with **no API key and no network**, and
`backend/tests/platform/test_the_moment.py` proves it on every push.

## The split that makes it trustworthy

The model decides **what the lease says**. The code decides **what the lease
costs**. Claude reads lease PDFs and email; every balance, schedule row and
journal entry is plain arithmetic with tests. Everything the model returns
carries the exact sentence it relied on, checked against the page before any
number reaches a schedule, and a list of what it wasn't sure about, which goes
to a person.

## How we know it works

Measured against things we did not write: a generated company with planted
errors and an answer key, a held-out company from a seed never used in
development, and adversarial documents. `python -m eval.run --extraction`,
24 Oct 2026, with Claude (`claude-opus-5-5`):

| Section | Result |
|---|---|
| Checking | **5 / 5 planted errors held, 0 false holds**; $25,736.36 flagged, exactly the expected amount |
| Citations | 5 / 5 holds cite the lease clause that proves them |
| Extraction | **65 / 65 lease fields correct** across the 5 leases, every one cited to its page |
| Investigation | The July variance settled to the amendment, confidence 100% |
| Safety | 4 / 4: 3 / 3 unauthorized sources refused (instructions planted in documents are not followed) |
| Held-out company | 18 clinics from an unseen seed, 4 / 4 invariants hold |
| Tests | 1,100+ in CI, 1,000+ of them against a real Postgres 16 |

**Real vs simulated.** The company, its leases, invoices and mailbox are
generated (deterministically, from a seed), so there is an answer key to score
against. The ASC 842 engine, the database, the permissions, the agents and the
model calls are real. Reference data is real: three SEC EDGAR lease exhibits
with 33 hand-verified labels, and 184 BLS CPI observations for escalations.

## Who can do what

The system runs as four database roles, and the limits are grants, not policy:

| Role | For |
|---|---|
| `lease_agent` | The worker and agents: reads records, writes ingestion, drafts and work. Cannot touch the ledger, outbox or golden tables |
| `lease_gateway` | The only writer back to records: golden tables, the journal, the outbox, period status |
| `lease_api` | Serves the UI: writes events and work items, never the ledger |
| `lease_reader` | The auditor: read-only on everything |

Nobody, the owner included, can rewrite or delete `audit_event`. A regional
manager cannot approve another region's item, and nobody approves their own
proposal; refusals are recorded in the audit trail too.

## Sponsor technology

| | Where | What it does |
|---|---|---|
| **Anthropic Claude** | `backend/app/agents`, `backend/app/llm` | Reads lease PDFs (structured outputs, per-claim citations), searches the mailbox for what explains a variance. Untrusted documents are fenced; answers are cached and replayable |
| **Fetch.ai / ASI:One** | [`agents_fetch/`](agents_fetch/README.md) | Four uAgents on Agentverse. The whole workflow inside an ASI:One chat, as yourself (one-time pairing code), under the same permissions as the web app |
| **SpacetimeDB** | [`spacetime/`](spacetime/README.md), `backend/app/work/live.py` | Every committed approval is mirrored live (`desk_status`), so other screens update with no refresh; agents publish each step (`agent_step`). Postgres stays the system of record |
| **Hyphenate** | the product | Lease accounting is the module an autonomous office of the CFO is missing, and the one whose source of truth is in somebody's inbox |

### Fetch.ai agents

| Agent | Name | Address |
|---|---|---|
| Front desk | `Northbay Lease Desk` | `agent1qg2tetdj6qf5wnf744mvvtz66rzfrmvqkx5dcejzpg78q3prt9aa58j2g0g` |
| Rulebook | `lease_desk_rulebook` | `agent1qtqqwygy3z7uc2ypu4qsc2dklqmuadvgy23mwpl54wqccl02sp3ag4pn3ud` |
| Investigation | `lease_desk_investigation` | `agent1q2mr89mwmdn0l8wj5t5uyzpd09fhfq8mvs037zf44wsvlt0znamqqkmg0l9` |
| Approvals | `lease_desk_approvals` | `agent1qgfyhfmc2ngygsck8f3xllf9mqr7plc8dv82czjjn9f3gh4psjcrjczh4dg` |

Setup, pairing and what to say: [`agents_fetch/README.md`](agents_fetch/README.md).

## Run the demo

**Prerequisites:** Python 3.11+ (macOS ships 3.9, which ReportLab will not run
on), Node 20+, and Docker with Compose v2.

```bash
git clone https://github.com/sarvesh172000/lease-desk.git && cd lease-desk
python3.13 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
docker compose up -d db                # Postgres 16 on host port 5433
make demo                              # database, January and July, API :8000, web app :3000
```

Open http://localhost:3000, sign in as `priya.raghunathan@northbaypt.example`
(password `demo`, the controller), and open the July hold on LEASE-01. Demo
mode has a switcher for every role. `make demo-data` alone builds the data;
`DEMO_MOMENT=` stops at January.

No API key is needed: the model's answers the demo uses are committed. With
`ANTHROPIC_API_KEY` set, anything not cached calls Claude.

## Develop

```bash
make up migrate seed      # Postgres, api and worker; schema and roles; the company
make prove-roles          # each role tries a forbidden write; the database refuses
make test                 # the whole suite (database tests run when Postgres is up)
make eval                 # generate the world and score a run against the answer key
make lint                 # ruff on the scope in ruff.toml
make ci                   # lint, the suite with database tests required, the eval
```

Compose publishes Postgres on host port **5433** so it never collides with a
local one. Every setting has a default, so `.env` is optional (copy
`.env.example`). Platform tests migrate a throwaway database and drop it;
CI loads `ci/require_db.py`, which turns any skipped database test into a
failure. GitHub Actions runs lint, the suite and the eval against Postgres 16,
`make migrate seed prove-roles` on a fresh database, and the frontend's lint,
build and tests.

## The accounting

Operating lease under ASC 842, payments in advance:

```
liability₀    = PV of all payments at the IBR
rou₀          = liability₀ + prepaid − incentives
straight_line = total payments / term months
interestₜ     = (liabilityₜ − paymentₜ) × (IBR / 12)
liabilityₜ₊₁  = liabilityₜ − paymentₜ + interestₜ
rou_amortₜ    = straight_line − interestₜ
```

A modification that isn't a separate contract remeasures the liability at the
revised payments and rate, with the difference booked against the ROU asset.
Months already closed on the stale schedule get a rent-expense catch-up.

## Layout

| Path | What's in it |
|---|---|
| `backend/app/` | FastAPI API, the work layer (states, transitions, gateway), agents, LLM layer, engine, jobs |
| `frontend/` | Next.js 15 web app: dashboard, the money screen, leases, audit trail |
| `agents_fetch/` | The Fetch.ai / ASI:One agents |
| `spacetime/` | The SpacetimeDB module for the live mirror and agent feed |
| `datagen/` | The generated company, its documents and the answer key |
| `eval/` | Scores a run against the answer key |
| `leasedesk/` | The original engine package (schedule, reconcile, remeasure) |
| `data/reference/` | SEC EDGAR exhibits, BLS CPI, and the committed model answers |
| `docs/` | Design, plan, security review, sponsor notes, handoff |

## Status

**Built and tested:** abstraction, the ASC 842 engine, checking, the
investigation and remeasurement, approvals through the gateway, the
hash-chained audit, policies, disputes, obligations, the web app, the ASI:One
agents and the SpacetimeDB mirror.

**Hosted:** the web app on Vercel (https://lease-desk-ten.vercel.app), the
API, worker, Postgres and agents on Azure Container Apps; see
[`docs/DEPLOY.md`](docs/DEPLOY.md).

**Not yet:** extraction scored on
the real SEC exhibits (the schema needs optional fields first, so a lease that
is silent on a term isn't forced to answer), finance-lease classification,
and variable or percentage rent.

Design notes: [`docs/DESIGN.md`](docs/DESIGN.md) · security review:
[`docs/SECURITY.md`](docs/SECURITY.md) · plan and status:
[`docs/PLAN.md`](docs/PLAN.md).

Built at Cal Hacks 13.0 by Sarvesh Waghmare and Jenil.
