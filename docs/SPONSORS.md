# Sponsor Strategy

Cal Hacks 13.0 · Oct 23–25 2026 · Palace of Fine Arts, SF
Presented by **Anthropic, Annapurna Labs, SpacetimeDB, Hyphenate**.

> **Verify before relying on this.** The per-sponsor prize list on the Devpost
> Prizes tab would not load for me (HTTP 403). The sponsor roster below is
> confirmed from the official site; the *prizes* are partly inferred. Open the
> Devpost Prizes tab in the first hour and correct this file.

## The headline

**Hyphenate sells an autonomous finance platform for the office of the CFO.**
Their modules are order-to-cash, treasury, GL accounting, procure-to-pay, and
reporting. Their pitch is agents that do routine finance work, escalate
judgment calls to people, and document every step with an audit trail.

**Lease accounting is not one of their modules.** And LeaseDesk is built in
their exact architectural idiom: agents propose, humans approve, everything
carries an audit trail.

You are not "a project that happens to fit a sponsor." You are a missing module
in a presenting sponsor's product line, built the way they build. Say that out
loud at their booth and in your submission.

## Where to spend effort

Three sponsors, no more. Spreading across eight is how you end up with eight
shallow integrations and no prize.

| Sponsor | Fit | Has a public API? | Effort | Verdict |
| --- | --- | --- | --- | --- |
| **Hyphenate** | Exact | No | 0h | **Target** — positioning, not integration |
| **Anthropic** | Exact | Yes, already used | 2h to deepen | **Target** |
| **SpacetimeDB** | Strong | Yes | 4–6h | **Target if one person owns it** |
| Visa | Strong | Yes (sandbox) | 3–4h | Stretch |
| Elastic | Strong | Yes | 2–3h | Stretch |
| Convex | Overlaps SpacetimeDB | Yes | 4h | Skip — pick one realtime DB |
| Capital One | Moderate | Yes | 3h | Skip unless a prize names it |
| Annapurna Labs | Weak | Inference hardware | — | Skip — no inference bottleneck here |
| Bright Data, Apify | Weak | Yes | — | Skip — nothing to scrape |

---

## 1. Hyphenate — positioning, not code

There is no public API to integrate. The play is entirely in how you present.

**Do this:**

- Go to their booth in hour one. Ask which modules they get asked for that they
  don't have yet. If lease accounting comes up, you have your opening line for
  the demo.
- Mirror their vocabulary in the UI and the pitch: *continuous close*,
  *escalation*, *audit trail*, *traceable answers*, *the office of the CFO*.
  These are their words. Using them signals you understand the category.
- Frame LeaseDesk as sitting beside their modules, not competing: lease
  accounting feeds GL accounting (the journal entries) and procure-to-pay (rent
  is an AP bill). Show that in the architecture slide.
- **Do not clone their visual identity.** Borrowed branding reads as pandering.
  Match the *idiom* — dense, high-contrast, enterprise — in your own palette.

**The line:** "Hyphenate automates order-to-cash, treasury, GL and
procure-to-pay. Lease accounting is the gap, and it's the one where the source
of truth isn't in any system — it's in an email. That's what we built."

---

## 2. Anthropic — deepen what you already have

Claude is already the extraction and investigation layer on `claude-opus-5-5`.
To make it prize-worthy rather than incidental, show *disciplined* use:

| Technique | Where | Why it demos well |
| --- | --- | --- |
| **Structured outputs** (`messages.parse` + Pydantic) | `extract.py` — already done | Schema-validated terms, no JSON parsing bugs |
| **Citations** | Investigation evidence | Every claim links to the sentence it came from |
| **Effort control** (`output_config.effort`) | `low` for reconciliation triage, `high` for investigation | Shows cost-awareness, not just "we called an LLM" |
| **Prompt caching** | The document corpus prefix | Re-investigating is near-free; mention the cache-hit number |
| **Refusal / uncertainty handling** | `uncertain[]` in `ExtractedLease` | The answer to "what if it hallucinates" |

**The strongest Anthropic-specific line** is the architectural one: *we use
Claude for exactly the thing it is good at — reading messy documents — and
nothing else.* Most projects at this event will put an LLM on the critical path
of a calculation. You deliberately did not. That is a more sophisticated use of
the model than piling on features.

Have `extract.py` open in your editor when you talk to them, and have the
`uncertain[]` and quote fields visible.

---

## 3. SpacetimeDB — the audit trail belongs in it

SpacetimeDB has a **confirmed special prize for the most impressive use of the
platform**, and the fit is real rather than forced.

SpacetimeDB puts your application logic inside the database as modules
(*reducers*) and lets clients subscribe to SQL queries that push updates live.
Two parts of LeaseDesk map onto that cleanly:

**a) The audit trail as append-only database state.** Every `AuditEvent` is a
reducer call. The log is literally the database's transaction history — which is
a much stronger claim than "we have an `audit_events` table." For an auditability
pitch, "the audit trail *is* the database" is the line.

**b) The live portfolio dashboard.** Multiple controllers watch the same
exception queue. When one approves Store 14, every other screen turns green
without a refresh. Subscriptions give you that for free, and it demos
beautifully — open two browser windows side by side on stage.

### Honest scoping

This is 4–6 hours and it is the riskiest item in the plan. Rules:

- **One person owns it end to end.** Do not split it.
- **Only after the SQLite demo path already works.** It is an upgrade, never a
  dependency.
- **Keep the SQLite path runnable.** If SpacetimeDB isn't working by H24, you
  demo SQLite and say nothing about it.
- Scope it to the audit trail and exception-status subscription only. Do not
  move the accounting engine into it.

### The two-window demo

Worth the effort on its own: approve on the left window, watch the right window
go green. Judges remember that.

---

## 4. Visa — rent is a payment (stretch)

Rent payment is a real payment rail, so this is not a contrived fit. The Visa
Developer sandbox lets you initiate a push payment in test mode.

**The integration:** after the controller approves the remeasurement, the next
month's rent goes out at the *corrected* amount through a Visa sandbox payment,
and the resulting payment event flows straight back into reconciliation — where
it now matches. That closes the loop from document to cash in one screen.

**Only do this if** the core demo is done by H20 and the sandbox signup is
quick. Use sandbox/test credentials exclusively — never real card or account
numbers.

---

## 5. Elastic — the search behind the Investigation Agent (stretch)

Right now the Investigation Agent reads every document in the corpus. That works
for four files and is obviously not how it scales.

**The integration:** index the document corpus in Elasticsearch, and have the
Investigation Agent retrieve candidates (BM25 plus vector search over
embeddings) before Claude reads them. Then the demo line becomes concrete:
"searching 1,284 documents" instead of "searching the folder."

This is also the honest answer to the scaling question, so it earns its place
even without the prize. 2–3 hours.

---

## What to say in the submission

Devpost writeups get skimmed. Lead with the number, name the sponsors
explicitly, and say where each is used:

> LeaseDesk found a $443,255 understatement of lease liability hiding in an
> email thread. It abstracts leases with **Claude** (`claude-opus-5-5`,
> structured outputs with per-claim citations), keeps an append-only audit
> trail in **SpacetimeDB** so every number traces to a source sentence, and
> proposes ASC 842 adjusting entries for a controller to approve. Lease
> accounting is the one module **Hyphenate** doesn't have, and it's the one
> where the source of truth lives in somebody's inbox.

## Booth plan

Sponsors judge their own prizes, usually from booth conversations as much as the
demo. Budget 90 minutes total.

- [ ] **Hour 1:** Hyphenate booth — ask what module they get asked for most
- [ ] **Hour 1:** Devpost Prizes tab — correct this file with the real list
- [ ] **Hour 2:** SpacetimeDB booth — confirm the prize criteria before building
- [ ] **Hour 2:** Anthropic booth — show them `extract.py`
- [ ] **By H20:** go back to each with a working demo, not a description
- [ ] **Submission:** name all three in the writeup, with where each is used
