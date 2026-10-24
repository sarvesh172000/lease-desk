# LeaseDesk — System Design

> Final design for Cal Hacks 13.0. Scoped so the critical path
> (ingest → extract → schedule → match → investigate → approve) demos cleanly
> in 36 hours while still reading as a real autonomous finance system.

## 1. The thesis

Lease accounting breaks for one reason: **the schedule is only correct until
someone signs an amendment, and nobody tells accounting.** The amendment lands
in a facilities inbox. The AP team pays the new amount because the landlord
invoiced it. The books keep running the old schedule. Nobody notices until
audit.

LeaseDesk closes that loop. It reconciles cash against the schedule
continuously, and a variance is what *triggers* a search for the document that
explains it.

## 2. The one principle everything else follows from

**The model reads. The code calculates.**

| Layer | Who does it | Why |
| --- | --- | --- |
| "What does this document say the rent is?" | Claude | Messy PDFs, email threads, inconsistent language |
| "What is the liability at 2026-07-01?" | Deterministic Python | Must be reproducible, auditable, and identical every run |
| "Which document explains this variance?" | Claude, with evidence | Search + reasoning over a document corpus |
| "What are the adjusting entries?" | Deterministic Python | Debits must equal credits, always |

No balance, schedule row or journal entry is ever produced by a language model.
A wrong extraction becomes a *reviewable* error instead of a silently wrong
balance sheet. This is the sentence that makes the product credible to a
controller, and it is the sentence to say out loud in the demo.

## 3. Trust model

Three gates, in order. Nothing skips a gate.

1. **Evidence.** Every extracted term carries the exact sentence it came from
   and a pointer to the source document. A claim with no quote is not a claim.
2. **Confidence.** Every investigation returns a score. Below threshold it does
   not propose entries — it escalates with what it found and what it could not
   determine.
3. **Human sign-off.** Proposed entries are *proposed*. A controller approves
   before anything is marked ready to post. The approval itself is an audit
   event.

### What happens when the agent is wrong

This is the question judges will ask, so it is a design requirement, not a
disclaimer:

- The agent cannot write a schedule. It can only propose a set of lease terms,
  which the deterministic engine then turns into a schedule.
- If extraction is wrong, the proposed entries are wrong — and visibly so,
  because the controller sees the before/after schedules and the source quote
  side by side before approving.
- If no document explains the variance, the exception is routed to a human with
  `root_cause: unexplained`. **Ship one of these in the demo.** A system that
  knows what it doesn't know reads as far more serious than one that is always
  confident.

## 4. Agents

Three, with a sequential orchestrator. No agent framework.

| Agent | Input | Output | Runs when | Model |
| --- | --- | --- | --- | --- |
| **Extractor** | Lease PDF / amendment email text | Structured lease terms + quotes + `uncertain[]` | New document | `claude-opus-5-5` |
| **Reconciliation** | Payment events + active schedule | Match or `Exception` | Every payment | Rules only — no LLM |
| **Investigation** | Exception + document corpus | `InvestigationResult` with evidence | Only on exception | `claude-opus-5-5` |

Deliberate choices:

- **Reconciliation uses no LLM.** Comparing two numbers is not a reasoning task.
  Putting a model there would be slower, cost money, and occasionally be wrong
  about arithmetic.
- **Investigation runs only on exceptions.** It is the expensive call. On a
  clean portfolio it never fires.
- **The orchestrator is a function, not a framework.** LangGraph buys nothing
  here and costs hours.

## 5. Data model

```
Lease ─┬─ RentStep[]        (a block of months at a fixed rent)
       ├─ Amendment[]       (what changed, effective when, from which source)
       └─ Schedule[]        (versioned; v1 original, v2 post-amendment)
                └─ Period[]  (monthly rows)

PaymentEvent ──▶ matched against Schedule.Period
                      │
                      └─ mismatch ──▶ Exception
                                          └─ InvestigationResult
                                                 ├─ Evidence[]      (quote + source doc)
                                                 └─ JournalLine[]   (proposed, unposted)

AuditEvent[]  — append-only, every action by every actor
```

`Lease.as_of(date)` applies every amendment effective on or before a date. This
is what makes before/after comparison trivial: build the schedule from
`as_of(amendment_date - 1)` and from `as_of(today)` and diff them.

## 6. The accounting

**Operating lease under ASC 842, payments in advance.** This matters: retail
stores, clinics and warehouses are almost always operating leases, which present
a *single straight-line lease cost* — not a principal/interest split. Presenting
them as a finance lease is the fastest way to lose an accountant judge.

```
liability₀    = PV of all payments at the IBR
rou₀          = liability₀ + prepaid − incentives
straight_line = total payments ÷ term months
interestₜ     = (liabilityₜ − paymentₜ) × (IBR ÷ 12)
liabilityₜ₊₁  = liabilityₜ − paymentₜ + interestₜ
rou_amortₜ    = straight_line − interestₜ        ← the ROU plug
```

### Remeasurement

A modification that is not a separate contract: remeasure the liability at the
revised payments and discount rate, and book the difference **against the ROU
asset** — no immediate P&L. Months already closed on the stale schedule get a
rent-expense catch-up.

```
Δliability = PV(revised remaining payments) − carrying liability
Δrou       = Δliability
catchup    = Σ(correct straight-line) − Σ(booked straight-line), over closed months
```

Verified on the sample lease: liability $559,665.35 → $1,002,921.05
(+$443,255.70), ROU $538,771.19 → $982,026.89, catch-up −$4,624.74, debits =
credits = $447,880.44.

## 7. Request flow

```
POST /api/ingest/document
  → Extractor → Lease terms → Accounting Engine → Schedule v1

POST /api/ingest/payment
  → Reconciliation → match? → done
                   → mismatch? → Exception created

POST /api/exceptions/{id}/investigate      (SSE stream)
  → Investigation → searches corpus → Evidence
  → Accounting Engine → Schedule v2 → Δ → proposed JournalLine[]
  → status: pending_review

POST /api/exceptions/{id}/approve
  → Schedule v2 becomes active
  → entries marked ready_to_post
  → AuditEvent(human_approved=true)
  → status: balanced
```

The investigate call streams over SSE. That is what makes the demo feel alive
without faking anything — the timeline fills in as the agent actually works.

## 8. What is deliberately out of scope

| Not building | Why |
| --- | --- |
| Finance-lease classification | Everything here is operating; adding both doubles the test surface for zero demo value |
| Variable / percentage rent, CPI escalation | Real, but invisible in a 2-minute demo |
| Scanned-PDF OCR | Unbounded debugging; the sample corpus is text |
| Multi-entity consolidation | Nobody understands why it matters in 2 minutes |
| Chat interface | Invites judges to break it live, and prose answers undercut the determinism pitch |
| Actual GL posting | `ready_to_post` is the honest boundary for a hackathon |

## 9. Failure modes and what the system does

| Failure | Behaviour |
| --- | --- |
| Extraction returns a term it isn't sure of | Lands in `uncertain[]`, surfaced in UI, never silently defaulted |
| No document explains a variance | `root_cause: unexplained`, escalated to a human, no entries proposed |
| Investigation confidence below threshold | Evidence shown, entries withheld, human decides |
| Two amendments affect the same months | Applied in `effective` order; later wins on overlapping steps |
| Payment arrives for an unknown lease | Logged unmatched, does not create a false exception |
| Claude API unavailable | Reconciliation and schedules still work; investigation degrades to manual |

## 10. Demo-critical invariants

Hold these or the demo breaks:

- Debits equal credits on every proposed entry set. Assert it in code.
- Liability and ROU both amortize to zero at term end. Tested.
- The schedule is reproducible — same inputs, same numbers, every run.
- `--live` and stored-amendment paths produce the same remeasurement.

## 11. Related documents

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — high and low level diagrams
- [`SPONSORS.md`](SPONSORS.md) — sponsor API integration strategy
- [`BUILD_PLAN.md`](BUILD_PLAN.md) — stage-by-stage build plan for two people
