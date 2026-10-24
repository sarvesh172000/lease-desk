# Reconciling the two plans

Jenil wrote a three-phase, 500-hour plan. [`BUILD_PLAN.md`](BUILD_PLAN.md) is a
36-hour plan. This document says where they agree, where they conflict, and what
to actually do.

## Verdict

**Aligned on substance. Not aligned on time — by a factor of seven.**

Jenil's plan is the better *product* document. It is domain-deeper than mine in
at least six places, and several of its ideas should go into the hackathon build
tonight. It is not a hackathon plan, and using it as one loses the hackathon.

## The arithmetic

| | Hours |
| --- | --- |
| Jenil's plan | **500 effort-hours** |
| Available (2 people × 36h, zero sleep) | 72 person-hours |
| Realistic (2 × 26h after ceremony, meals, sleep, submission) | 52 person-hours |
| **Overrun** | **6.9× to 9.6×** |

Per phase, against the *entire* event with nobody sleeping:

| Phase | Hours | vs. whole event |
| --- | --- | --- |
| Phase 1 — platform + thin slice | 110 | **1.5×** |
| Phase 2 — the company and the mess | 250 | 3.5× |
| Phase 3 — polish, deploy, three tracks | 140 | 1.9× |

**Phase 1 alone does not fit.** Not Phase 1 plus 2 — Phase 1 by itself is half
again as long as the hackathon, before anyone sleeps.

The plan says hours are effort rather than wall clock, counting coding agents.
That is fair, but it does not close a 7× gap: 500 effort-hours in 36 wall-clock
hours needs ~14 workstreams running continuously, and two people cannot review,
integrate and debug 14 streams. Review is the bottleneck, not generation.

### The structural problem

**The submission package is Phase 3, task group 10.** Everything before it is
486 hours — 6.8× the event. In this plan's own ordering, you never reach "record
the demo video and submit."

That is the same failure I flagged in the first plan review, in a more severe
form: the demo is built last, so slipping means having nothing to show. Here,
slipping is certain.

## What Jenil's plan gets right that mine didn't

This is not politeness. These are genuinely better, and some are going into
tonight's build.

| Idea | Why it's better |
| --- | --- |
| **Hash-chained audit events** | The audit trail as an append-only chain where state is *rebuilt* from events, with tamper detection. Stronger than my `audit_events` table. |
| **DB roles as defense in depth** | `lease_agent` physically cannot `INSERT` into `journal_entry`. Not a policy — a grant. Demonstrable in one SQL statement. |
| **Source trust ranking** | Executed amendment > original lease > authorized rep > property manager > invoice > payment history. This is the real answer to "sources that disagree," and I didn't have it. |
| **Held-out test company** | A second company from a different seed, never seen during development. The honest answer to "did you overfit your own generator." |
| **Real EDGAR leases** | Extraction benchmarked on actual SEC-filed lease exhibits, not only synthetic PDFs. Large credibility gain for ~1 hour of work. |
| **Partial payment of undisputed amounts** | Pay what isn't contested, hold only the disputed portion. Genuinely sophisticated domain thinking. |
| **Beancount / Fava export** | A judge opens the books in an independent, well-known ledger tool. Clever. |
| **Separation of duties** | No actor approves what they proposed. Thirty minutes of code, real trust signal. |

The parking-lot-repaving double bill — one vendor line billed in full to three
clinics in the same center — is also arguably a **better demo moment** than the
hidden amendment. It is more visual: three statements side by side, one share
clause.

## Where the two plans actually conflict

These are decisions to make together, now, not at hour 30.

### 1. Which moment opens the demo

- **The concept doc and mine:** the hidden amendment. "The 'found the hidden
  amendment' moment has to carry it."
- **Jenil's Phase 3:** the guided demo opens with the parking lot double bill;
  the amendment is a later step.

Both are good. **Pick one and build only that one.** Two half-built moments beat
nothing, but one finished moment beats two half-built ones. My recommendation:
the **amendment**, because the engine for it already works and is tested, and
the double bill needs the whole CAM pool engine (20h in Jenil's own estimate).

### 2. Which sponsors to target

| | Targets |
| --- | --- |
| Jenil's plan | Hyphenate, Microsoft, Fetch.ai |
| [`SPONSORS.md`](SPONSORS.md) | Hyphenate, Anthropic, SpacetimeDB |

Only Hyphenate overlaps. Notes:

- **Fetch.ai is a good call** — confirmed prize with cash plus internship
  interviews. But Phase 3 budgets **22 hours** for the ASI:One front door, which
  is a third of one person's realistic time.
- **Anthropic is a presenting sponsor** and is missing from Jenil's plan
  entirely, despite Claude being the core of the system. That is a free target
  being left on the table.
- **SpacetimeDB has a confirmed special prize** and no mention in either of
  Jenil's three phases.

Resolve this at the Devpost Prizes tab in hour one, not by debate.

### 3. Postgres + event sourcing vs. SQLite

Jenil: Postgres 16, four DB roles, triggers, transactional outbox, job queue
with `SKIP LOCKED`, replay equality tests. Mine: SQLite, seed on boot.

Jenil's is correct engineering and the right answer for a real product. It is
also most of Phase 1's 110 hours. **Compromise below.**

### 4. Model

Jenil's plan says "the current Claude Sonnet model." The repo uses
`claude-opus-5-5`. Use Opus for extraction and investigation — the reasoning
quality matters on messy documents — and Haiku or Sonnet for bulk
classification if you add it.

### 5. Who is Person A?

Phase 1 names **"Person A (Srinidhi)"**. That is neither of you. Either there is
a third teammate I don't know about, or the plan was adapted from another
document. The entire A/B task split depends on this, so settle it before
assigning anything.

## What to actually do

### Steal these five into tonight's build — about 6 hours total

Ranked by demo value per hour. All five fit inside
[`BUILD_PLAN.md`](BUILD_PLAN.md) Stage 4 without displacing anything.

| # | Steal | Cost | Demo beat |
| --- | --- | --- | --- |
| 1 | **Hash-chained audit events** | 1h | "Every event is chained. Tamper with one and the chain breaks." Add a Verify button. |
| 2 | **Source trust ranking** | 1.5h | A lookup table plus a line in the investigation prompt. "It trusted the executed amendment over the invoice, because the amendment is signed by both parties." |
| 3 | **One real EDGAR lease** | 1h | "This isn't a lease we wrote. It's a real one filed with the SEC, and the extraction holds." |
| 4 | **Answer key + eval script** | 1.5h | "Five planted errors, five caught, zero false holds." Run it live. |
| 5 | **Separation of duties** | 0.5h | The approver cannot approve their own proposal. Show the denial in the audit timeline. |

If you have Postgres running anyway, add **DB role denial** (1h): connect as the
agent role, attempt an insert into `journal_entry`, get permission denied on
camera. It is the single most convincing trust demo in either plan. Do not
introduce Postgres solely for it.

### Leave these for after the hackathon

Everything else in Phases 1–3 is a real roadmap and should be kept as one:
bitemporal rulebook, CAM pools, CPI escalation, policy engine with backtests,
disputes and correspondence, personas, chaos testing, Azure, ASI:One.

Rename Jenil's three files to `ROADMAP_PHASE_*.md` and keep them in `docs/`.
They are the answer to "what would you build next," which judges ask and most
teams cannot answer.

### The one-line summary for Jenil

> Your plan is the product. [`BUILD_PLAN.md`](BUILD_PLAN.md) is the 36 hours. We
> build the 36 hours, steal your five best ideas into it, and show your phases
> as the roadmap when they ask what's next.
