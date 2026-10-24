# Sponsor Strategy — five targets

Cal Hacks 13.0 · Oct 23–25 2026 · Palace of Fine Arts, SF
Presented by **Anthropic, Annapurna Labs, SpacetimeDB, Hyphenate**.
Also sponsoring: Microsoft, Visa, Fetch.ai, Supercell, and ~40 others.

> **Verify in hour one.** The Devpost Prizes tab would not load for me (HTTP
> 403). The sponsor roster is confirmed from the official site; the per-sponsor
> prize list is partly inferred. Open the Prizes tab and correct this file.
> Only SpacetimeDB's special prize is confirmed from a published source.

One product, five framings. The system does not change per track — only the
emphasis does.

| Sponsor | Emphasis | Lands in | Owner |
|---|---|---|---|
| **Hyphenate** | Autonomy, escalation, evidence | The whole product | Both |
| **Anthropic** | Disciplined model use, determinism | P3 group 12 | A |
| **SpacetimeDB** | The audit trail *is* the database | P3 group 11 | B |
| **Microsoft** | Customer, production path, cost | P3 groups 7 + 8 | B then A |
| **Fetch.ai** | Multi-agent, inside ASI:One | P3 group 9 | B |

---

## 1. Hyphenate — the product is the pitch

There is no public API. Hyphenate sells an **autonomous finance platform for
the office of the CFO**: order-to-cash, treasury, GL accounting,
procure-to-pay, reporting. Agents that do routine finance work, escalate
judgement calls to people, and document every step with an audit trail.

**Lease accounting is not one of their five modules.** And LeaseDesk is built
in their exact idiom. You are a missing module in a presenting sponsor's
product line, built the way they build.

- Booth in hour one: ask which module they get asked for that they don't have.
- Mirror their vocabulary: *continuous close*, *escalation*, *audit trail*,
  *traceable answers*, *the office of the CFO*.
- Show where it feeds their modules: lease entries into GL accounting, rent
  into procure-to-pay as an AP bill.
- **Do not clone their branding.** Match the idiom — dense, enterprise,
  high-contrast — in your own palette. They are judging; borrowed branding
  reads as pandering.

**The line:** "Hyphenate automates order-to-cash, treasury, GL and
procure-to-pay. Lease accounting is the gap, and it's the one where the source
of truth isn't in any system — it's in somebody's inbox."

---

## 2. Anthropic — Phase 3 group 12 (12 h, Person A)

Claude is already the extraction and investigation layer. This group makes that
use *prize-worthy* rather than incidental.

| Task | h | What it demonstrates |
|---|---|---|
| Effort sweep: `low` for classification, `high` for investigation, measured against eval | 3 | Cost-awareness, not just "we called an LLM" |
| Prompt caching over the document corpus, report cache-hit rate in the ops page | 2 | Re-investigating is near-free |
| Cost per clinic per month from `llm/usage.py`, charted | 2 | A real unit economic |
| Model comparison on the eval: Opus vs Sonnet vs Haiku per task type | 3 | Evidence for model choice, not vibes |
| Write up the determinism split for the submission | 2 | The strongest line available |

**Already done:** structured outputs via `messages.parse`, versioned prompts
with the id and version on every event, response cache, usage log, untrusted
fencing with per-call nonces, and `uncertain[]` surfaced to humans.

**The argument:** *we use Claude for exactly the thing it is good at — reading
messy documents — and nothing else.* Most projects at this event put an LLM on
the critical path of a calculation. We deliberately did not, and the citation
check catches a model that invents a number before it reaches a schedule.

Have `agents/abstraction.py` and `agents/trust.py` open at their booth.

---

## 3. SpacetimeDB — Phase 3 group 11 (14 h, Person B)

**Confirmed special prize for the most impressive use of the platform.**

SpacetimeDB puts application logic inside the database as reducers and pushes
subscribed queries to clients live. Two parts of LeaseDesk map onto that
without being forced.

| Task | h | What it gives |
|---|---|---|
| Mirror `audit_event` into a SpacetimeDB module; every transition is a reducer call | 5 | "The audit trail *is* the database" |
| Subscribe the exception queue and work-item status | 4 | Live updates with no polling |
| Two-window demo: approve on the left, right turns green | 2 | The beat judges remember |
| Chain verification as a reducer, so tamper-detection runs in the DB | 3 | Auditability argument |

**Scoping rules:**
- Postgres stays the system of record. SpacetimeDB is the live projection
  layer. Do not move the accounting engine into it.
- The SQLite/Postgres path must stay runnable. This is an upgrade, never a
  dependency.
- One person owns it end to end.

---

## 4. Microsoft — Phase 3 groups 7 and 8 (24 h)

Group 7 is the Azure deployment; group 8 is the judging-criteria write-up.
Jenil's Phase 3 already specifies both. Additions:

- **Ask early** whether they want Azure OpenAI. If yes, flip the model switch
  and rerun the eval to show parity — that comparison is itself a deliverable.
- **Measurable usefulness** comes from `eval/report.json`, not adjectives:
  errors caught, dollars recovered, false-hold rate, straight-through rate,
  questions per 100 charges, close time, extraction accuracy on real EDGAR
  leases.
- **Cost per clinic per month** comes from `llm/usage.py` plus the Azure
  hosting cost. Most teams cannot quote a unit cost at all.
- **Responsible design** is already built, not retrofitted: limits enforced in
  code *and* in the database through separate roles, separation of duties, the
  gateway as sole writer, a hash-chained audit, untrusted-content handling with
  adversarial results, and no payment ever made by the system.

---

## 5. Fetch.ai — Phase 3 group 9 (22 h, Person B)

Confirmed prize with cash plus internship interviews. Jenil's Phase 3 specifies
it in full: a `uagents` front desk on Agentverse implementing the Chat
Protocol, two specialist agents (`rulebook_agent`, `approvals_agent`), pairing
an ASI:One user to an actor, and the primary workflow run entirely inside
ASI:One.

**The constraint that keeps it honest:** the agents talk to the existing API
only, never to the database. Every action still goes through `can()`, the
gateway and the audit stream, and chat input is treated as untrusted. A
regional manager paired in ASI:One who tries to answer another region's
question gets denied, and the denial shows in the web app's audit timeline.

That denial, demonstrated live, is the strongest Fetch.ai beat — it shows
multi-agent work inside their platform under real permissions, not a chatbot
wrapper.

---

## Booth plan

Sponsors judge their own prizes, often from booth conversations as much as the
demo. Budget two hours total.

- [ ] **Hour 1 — Devpost Prizes tab.** Correct this file with the real list.
- [ ] **Hour 1 — Hyphenate.** Which module do they get asked for most?
- [ ] **Hour 2 — SpacetimeDB.** Confirm prize criteria before building group 11.
- [ ] **Hour 2 — Anthropic.** Show `abstraction.py` and the citation check.
- [ ] **Hour 2 — Microsoft.** Ask about Azure OpenAI before group 7.
- [ ] **Hour 3 — Fetch.ai.** Confirm Agentverse registration requirements.
- [ ] **Later:** go back to each with a working demo, not a description.
- [ ] **Submission:** name all five, with where each is actually used.

## What to say in the submission

> LeaseDesk found a $443,255 understatement of lease liability hiding in an
> email thread. It abstracts leases with **Claude** — structured outputs, every
> term carrying the sentence it came from, checked against the page before any
> number reaches a schedule — keeps a hash-chained audit trail in
> **SpacetimeDB** so every figure traces to a source, deploys on **Azure**, and
> is driven from **ASI:One** through three **Fetch.ai** agents under the same
> permission model as the web app. Lease accounting is the one module
> **Hyphenate** doesn't have, and it's the one where the source of truth lives
> in somebody's inbox.
