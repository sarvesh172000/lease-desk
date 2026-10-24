# Lease Desk

**Cal Hacks 13.0**

A lease desk for a multi-location business. It abstracts leases out of PDFs and
email, builds the ASC 842 schedules, checks every rent payment against the
schedule, and when something doesn't match, goes looking for why.

## The problem

Any company with stores, clinics or warehouses has dozens of leases, each a PDF
with escalations, renewal options and amendments buried in email. KPMG found the
top implementation challenges include abstracting leases into a system and
setting the right borrowing rate — and after implementation, *identifying lease
changes* stayed a persistent problem, with many companies only reacting after
the fact.

That last part is the gap. The schedule is only correct until someone signs an
amendment, and nobody tells accounting.

## The seats

The lease accountant, and the AP person paying rent.

## End to end

```
Lease PDFs ─┐
Amendments ─┤
Invoices   ─┼──▶  extract  ──▶  schedule  ──▶  reconcile  ──▶  remeasure
Bank feed  ─┘    (Claude)      (ASC 842)       (cash vs.      (+ proposed
                                                schedule)       entries)
```

1. **Extract** — Claude reads the lease and returns structured terms, with the
   sentence it relied on and an explicit list of what it couldn't determine.
2. **Schedule** — plain arithmetic builds the liability and ROU amortization.
3. **Reconcile** — every payment is checked against the month it belongs to.
4. **Remeasure** — a variance triggers a search of the mailbox; a found
   amendment is applied and the adjusting entries are proposed for sign-off.

## The moment

Store 14's rent payments stopped matching the schedule in July. The system finds
an amendment in an email thread that extended the lease three years and cut the
rent, recalculates the lease, proposes the adjusting entries, and asks the
controller to sign off.

```bash
python -m leasedesk.cli
```

```
2. Reconciling cash against the schedule
  ! STORE-14 Jul 2026: expected $19,626.65, paid $17,400.00 (underpaid $2,226.65)
  ! STORE-14 Aug 2026: expected $19,626.65, paid $17,400.00 (underpaid $2,226.65)
  ! STORE-14 Sep 2026: expected $19,626.65, paid $17,400.00 (underpaid $2,226.65)

4. Remeasuring the lease
Liability  $  559,665.35  ->  $1,002,921.05   (+443,255.70)
ROU asset  $  538,771.19  ->  $  982,026.89   (+443,255.70)

5. Proposed adjusting entries — awaiting controller sign-off
  Account                           Debit         Credit
  Lease liability                             443,255.70
  ROU asset                    443,255.70
  ROU asset                      4,624.74
  Rent expense                                  4,624.74
                               447,880.44     447,880.44
  Balanced.
```

Add `--live` to have Claude recover the amendment from the raw `.eml` files in
`data/inbox/` instead of reading the stored one. Needs `ANTHROPIC_API_KEY`.

## The split that makes this trustworthy

The model decides **what the lease says**. The code decides **what the lease
costs**. No balance, no journal entry and no schedule row is ever produced by a
language model — `schedule.py` and `remeasure.py` are ordinary arithmetic with
tests. That's what makes a wrong extraction a *reviewable* error instead of a
silently wrong balance sheet.

Everything the model produces carries the quote it came from and a list of what
it wasn't sure about, and nothing posts without the controller clicking sign-off.

## The accounting

Operating lease under ASC 842, payments in advance:

```
liability₀   = PV of all payments at the IBR
rou₀         = liability₀ + prepaid − incentives
straight_line= total payments / term months
interestₜ    = (liabilityₜ − paymentₜ) × (IBR / 12)
liabilityₜ₊₁ = liabilityₜ − paymentₜ + interestₜ
rou_amortₜ   = straight_line − interestₜ
```

A modification that isn't a separate contract remeasures the liability at the
revised payments and rate, with the difference booked against the ROU asset.
Months already closed on the stale schedule get a rent-expense catch-up.

## Layout

| Path | What's in it |
|---|---|
| `leasedesk/models.py` | Lease, rent steps, amendments, and applying them as of a date |
| `leasedesk/schedule.py` | ASC 842 amortization — the deterministic core |
| `leasedesk/reconcile.py` | Cash vs. schedule, variance detection |
| `leasedesk/remeasure.py` | Remeasurement on amendment + journal entries |
| `leasedesk/extract.py` | Claude-powered lease and amendment extraction |
| `leasedesk/cli.py` | The demo |
| `data/` | Sample lease, payment history, and the inbox the amendment hides in |

## Run it

**Prerequisites:** Python 3.11 or newer (macOS ships 3.9, which ReportLab will
not run on) and Docker with Compose v2.

```bash
git clone https://github.com/sarvesh172000/lease-desk.git
cd lease-desk
python3.13 -m venv .venv          # or python3.11 / python3.12
./.venv/bin/pip install -r requirements.txt

make up migrate seed              # Postgres, api and worker; schema and roles; the company
make prove-roles                  # each role tries a forbidden write; the database refuses
make test                         # the whole suite
make api                          # the API on the host with reload, http://localhost:8000
```

The Makefile uses `.venv/bin/python` when it exists. Compose publishes
Postgres on host port **5433** so it never collides with a local Postgres;
containers reach it as `db:5432`. Every setting has a default, so `.env` is
optional (copy `.env.example` to override). The worker restarts until
`make migrate` has created its role, then settles.

**Database roles.** `make migrate` runs as the owner (`leasedesk`) and creates
four logins. Each process connects as exactly one:

| Role | For |
|---|---|
| `lease_agent` | The worker and agents: reads records, writes ingestion, drafts and work; cannot touch the ledger, outbox or golden tables |
| `lease_gateway` | The only writer back to records: golden tables, the journal, the outbox, period status |
| `lease_api` | Serves the UI: writes events and work items, never the ledger |
| `lease_reader` | The auditor: read-only on everything |

Nobody, the owner included, can rewrite or delete `audit_event`.

**Tests without Postgres.** `backend/tests/platform` migrates a throwaway
database from empty for each run and drops it afterwards. When no Postgres is
reachable those tests skip and everything else still runs offline, with no API
key. Point them elsewhere with `LEASEDESK_DB_HOST` / `LEASEDESK_DB_PORT` (e.g.
`LEASEDESK_DB_PORT=5432` for a local Postgres 16 whose owner can create
databases and roles). CI loads `ci/require_db.py`, which turns any such skip
into a failure.

**The eval.** Generate the world and score a run against the answer key:

```bash
make eval                         # python -m datagen.build, then python -m eval.run
```

Only the `--live` paths call the Claude API and need `ANTHROPIC_API_KEY`.

**Lint and CI.**

```bash
./.venv/bin/pip install ruff pre-commit && ./.venv/bin/pre-commit install
make lint                         # ruff on the platform scope in ruff.toml
make ci                           # lint, the suite with database tests required, the eval
```

GitHub Actions (`.github/workflows/ci.yml`) runs lint; migrations from empty,
pytest and the eval against a Postgres 16 service; `make migrate seed
prove-roles` on a fresh database; and the frontend's lint, build and tests once
`frontend/` exists. Behind a TLS-intercepting proxy, `docker compose build`
fails at `pip install` with `CERTIFICATE_VERIFY_FAILED`; the image itself is
fine, the build container just does not trust the proxy's CA.

**Start here:** [`docs/PLAN.md`](docs/PLAN.md) — 27 chunks, who owns each, and
what counts as done.

## Design docs

| Document | What's in it |
|---|---|
| **[docs/PLAN.md](docs/PLAN.md)** | **The plan.** Three phases, 526 hours, live status board |
| [docs/DESIGN.md](docs/DESIGN.md) | How it works: trust model, agents, accounting, diagrams, API |
| [docs/SPONSORS.md](docs/SPONSORS.md) | Five sponsor targets and where each lands in the plan |
| [docs/phases/](docs/phases/) | Phase 1, 2 and 3 in full — the task detail |

## Status


Hackathon project — the schedule engine, reconciliation, remeasurement and
entry proposal are implemented and tested. Lease abstraction from PDFs is
wired to Claude but the demo ships with pre-abstracted sample data.

### Not built yet

- PDF text extraction (the extractor takes text; a real run needs a PDF step)
- Multi-lease portfolio view and the web UI (`web/` is a placeholder)
- Finance-lease classification — everything here assumes operating
- Variable/percentage rent, CPI escalations, impairment
