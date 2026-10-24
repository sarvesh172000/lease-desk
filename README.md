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

## Running it

```bash
pip install -r requirements.txt
python -m leasedesk.cli      # the demo
python -m pytest tests -q    # 16 tests, no API key needed
```

The demo and the whole test suite run offline. Only `--live` calls the API.

## Design docs

| Document | What's in it |
|---|---|
| [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) | Final system design: trust model, agents, accounting, failure modes |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | High and low level diagrams, API surface, frontend structure |
| [docs/SPONSORS.md](docs/SPONSORS.md) | Sponsor integration strategy |
| **[docs/PLAN.md](docs/PLAN.md)** | **The plan being executed** — 36 hours, 7 stages, Jenil's phase structure |
| [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md) | Superseded by PLAN.md; kept for its fixtures and cut list |
| [docs/PLAN_RECONCILIATION.md](docs/PLAN_RECONCILIATION.md) | Why the roadmap was compressed, and what was cut |
| [docs/ROADMAP_PHASE_1.md](docs/ROADMAP_PHASE_1.md) | Roadmap: platform core and first thin slice |
| [docs/ROADMAP_PHASE_2.md](docs/ROADMAP_PHASE_2.md) | Roadmap: the company, the mess, the full loop |
| [docs/ROADMAP_PHASE_3.md](docs/ROADMAP_PHASE_3.md) | Roadmap: polish, hardening, multi-track delivery |

## Status


Hackathon project — the schedule engine, reconciliation, remeasurement and
entry proposal are implemented and tested. Lease abstraction from PDFs is
wired to Claude but the demo ships with pre-abstracted sample data.

### Not built yet

- PDF text extraction (the extractor takes text; a real run needs a PDF step)
- Multi-lease portfolio view and the web UI (`web/` is a placeholder)
- Finance-lease classification — everything here assumes operating
- Variable/percentage rent, CPI escalations, impairment
