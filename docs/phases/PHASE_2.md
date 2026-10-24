# Phase 2 - The Company, the Mess and the Full Autonomous Loop

> **Status — four groups started early, because the demo moment needed them.**
>
> | Group | Hours | Owner | Status |
> |---|---|---|---|
> | 3. Messy inputs | 16 | A | Partial — `datagen/emails.py`: 10 threads incl. forged sender and injection. No scans, tracker, or multi-format invoices |
> | 5. Bitemporal rulebook and lease changes | 14 | B/A | Partial — `agents/modification.py` finds causes and proposes versions. Not yet bitemporal |
> | 8. ASC 842 subledger and close | 26 | A | Partial — `engine/remeasurement.py` remeasures and proposes balanced entries. No transition, close, or tie-out |
> | 9. Resolver | 20 | B/A | Partial — `agents/trust.py` six-rank ranking + confidence. No routing, SLAs, or partial payment |
> | 15. Safety and defense in depth | 8 | B | Partial — untrusted fencing and 4 adversarial tests. No DB-role depth tests |
>
> Everything else in this phase is not started. See [`../PLAN.md`](../PLAN.md).

**Budget: 250 of 500 hours (50%)**

## Goal
Turn the platform into the lease accountant Northbay would actually hire. The company grows to 30 clinics in 3 legal entities with the mess left in: real leases from SEC EDGAR, scanned amendments, side deals that live only in email, a half-finished tracker left by the previous accountant, three landlord invoice formats and annual CAM reconciliations. The intelligence grows to cover Hyphenate's full loop and their five hard parts:

- **Learns:** reads every lease and amendment into a bitemporal rulebook (what was true, and when we knew it), and learns the team's habits from 2025 history as proposed policies with precedent counts.
- **Runs:** every month, on its own, checks rent, CPI escalations and CAM against each lease's own rules, drafts the payment batch and the ASC 842 entries, and prepares the close.
- **Escalates:** only when sources disagree, saying which source it trusts and why, with a confidence score, holding just the disputed amount and asking the person closest to the fact, chasing them if they are busy.
- **Improves:** turns answers into versioned policies, backtests each one against history before the controller approves it, remembers a "no", and cites the policy on every later decision.
- **Proves:** a held-out test company it has never seen, an answer key, and an evidence pack any auditor can pull for any number.

When this phase is done, all of 2026 runs month by month without a human (the people are played by LLM personas with known facts), the parking-lot-repaving double bill is caught, lease changes produce controller-approved remeasurements, each period closes with the lease subledger tied to the GL, and the eval report scores everything on both the development company and the held-out company.

## Scope
- In scope:
  - Real lease corpus from EDGAR with hand labels
  - Company generator v2: 3 entities, 30 clinics, 10 landlords, 8 centers, 2025 history, all of 2026, plus a held-out test company from a different seed
  - Messy inputs: scans, emails through a real local mail server, three invoice formats, CAM reconciliations, credit memos, the previous accountant's spreadsheet
  - Document understanding at full mess, entity resolution, totals validation
  - Bitemporal lease rulebook with amendments, side letters and suite moves
  - CAM engine and the shared-pool double billing check
  - Rent engine v2 with CPI escalations from real BLS data
  - ASC 842 operating lease subledger, monthly entries, remeasurement, period close and GL tie-out
  - Resolver: source trust ranking, confidence, routing, busy approvers, partial payment of undisputed amounts, handoffs
  - Policy engine: rule format, onboarding learning, learning from answers, backtest before approval, rejection memory
  - Disputes and landlord correspondence through the outbox
  - Critical dates and lease obligations
  - LLM-played human personas for unattended runs
  - "Why?" agent, auditor role and evidence packs
  - Safety: injection defenses, adversarial set, defense-in-depth tests
  - Eval v2, held-out scoring, counterfactual replay
- Out of scope (deferred to a later phase):
  - Visual polish, guided demo, scenario studio, chaos testing, cloud deployment (Phase 3)
  - Microsoft deliverables and the Fetch.ai / ASI:One front door (Phase 3)
  - Finance leases, percentage rent, gross-up calculations, multi-currency (not planned)

## Prerequisites & Dependencies
- Phase 1 Definition of Done met: replay equality, chain verification, DB role tests, gateway idempotency and the eval gate all green in CI
- EDGAR full-text search (efts.sec.gov) reachable with a declared User-Agent, as SEC requires
- BLS Public Data API reachable (a free registration key raises limits). The CPI series used are cached into the repo so runs work offline
- Fixed names from Phase 1 are unchanged: tables, roles, states, make targets, repo layout

## Tech, Tools & Components
Everything from Phase 1, plus:
- **SEC EDGAR full-text search** for lease exhibits, converted to PDF with WeasyPrint
- **BLS Public Data API** for CPI-U: `CUUR0000SA0` (U.S. city average) and `CUUR0400SA0` (West region), saved as a dated CSV snapshot
- **Mailpit** in Compose as the company inbox and outbox. Landlord emails are delivered into it over SMTP, the ingester reads them through Mailpit's HTTP API, and approved outbound mail is sent through it
- **Pillow and OpenCV** to render scanned-looking pages (rotation, blur, noise, JPEG artifacts, fax headers)
- **Claude vision** for image-only pages, using page PNGs from the Phase 1 pipeline
- **openpyxl and pandas** to read the previous accountant's messy tracker spreadsheet
- **Postgres full-text search** over page text and email bodies for cause-finding, no separate vector store
- **Recharts** for the eval and backtest charts in the UI

New modules (inside the fixed layout):

```
backend/app/
  rulebook/bitemporal.py   valid time + record time queries ("as known on")
  engine/rent.py           fixed, step and CPI escalations with floors and caps
  engine/cam.py            pro rata, exclusions, caps, mgmt fee, shared pools
  engine/asc842.py         measurement, schedules, remeasurement
  ledger/close.py          close checklist, subledger tie-out, sign-off, lock
  engine/policies.py       rule evaluation and backtest
  agents/modification.py   find causes of change, propose lease versions
  agents/resolver.py       sources, trust ranking, confidence, routing, SLAs
  agents/policy_learner.py onboarding and answer-driven policies
  agents/disputes.py       letters, dispute register, credit memo matching
  agents/obligations.py    renewal notices, audit windows, other lease dates
  agents/why.py            fixed-query explanations
  agents/evidence_pack.py  auditor bundles
  personas/                human simulation for unattended runs
datagen/
  edgar.py  company_v2.py  scans.py  emails.py  tracker_xlsx.py
  invoices/format_a_table.py  format_b_letter.py  format_c_portal_csv.py
  cam_pools.py  replies.py  heldout.py
```

### Source trust ranking (used by the resolver and shown in the UI)
1. Executed lease amendment or side letter signed by both parties
2. Original executed lease
3. Written confirmation from the landlord's authorized representative (named in the lease notices clause)
4. Email from property management without stated authority
5. Landlord invoice or statement
6. Payment history and the previous accountant's tracker

When a lower-ranked source contradicts a higher-ranked one, the system does not pick a side. It holds the item and asks. When sources of the same rank conflict, it also asks. When everything agrees, or an approved policy covers the case, it proceeds and says why.

## Task Breakdown

### 1. Real lease corpus from EDGAR (14 h, Person A)
- [ ] Search EDGAR full-text for exhibits matching phrases like "common area maintenance", "medical office lease", "shopping center lease", "base rent schedule"
- [ ] Select 10 real leases with clear rent schedules and operating expense sections, store the filing URL, company and date with each
- [ ] Hand-label 14 fields per lease into `data/edgar_labels.json` (commencement, expiration, RSF, rent schedule, escalation, CAM method, pro rata share, cap and cap type, exclusions, management fee, audit window, renewal option, notice address, security deposit)
- [ ] Add an EDGAR extraction benchmark to eval, reported separately from synthetic leases
- [ ] Mine clause wording into template variants so Northbay leases read like real ones

### 2. Company generator v2 and held-out company (26 h, Person A)
- [ ] 3 entities, 3 regions, 30 clinics, 10 landlords, 8 centers. Two centers hold 3 Northbay clinics each, one holds 2
- [ ] Per lease rules: escalation (fixed percent, fixed step, or CPI with floor and cap), pro rata share and its denominator, controllable CAM cap (cumulative or not), exclusion list, management fee cap, CAM audit window, renewal options and notice days, late fee terms, notice address and authorized representative
- [ ] `cam_pools.py`: per center, yearly operating expenses by category with vendors and invoice references
- [ ] History for 2025 including the team's habits (consistent treatments that become onboarding policies) and a few past mistakes they paid anyway
- [ ] 2026 January to December: monthly rent invoices, quarterly CAM estimates, 2025 CAM reconciliations in March and April, tax and insurance pass-throughs, credit memos, late notices
- [ ] Error catalog v2: about 60 planted errors across 18 types plus about 20 correct-but-unusual charges, across roughly 1,100 charges. Types include all Phase 1 types plus CPI cap ignored, CPI wrong index, abatement not applied, amendment not reflected, wrong pro rata denominator, cap breach, excluded capital expense passed through, management fee above cap, same CAM line billed in full to two clinics in one center, insurance billed twice, tax at wrong share, late fee on an on-time payment, true-up arithmetic error, credit memo never applied, renewal notice deadline, audit window closing
- [ ] Each answer key entry now includes the expected trusted source, expected route (auto, regional manager, controller), expected outcome, expected policy if any, and the correct journal impact
- [ ] `heldout.py`: generate a second company from a different seed and different landlord set. It is used only by eval, never during development, and its files live outside the dev data folder

### 3. Messy inputs (16 h, Person A)
- [ ] Three invoice formats by landlord: A is a PDF table, B is a letter with amounts in prose, C is a portal CSV export with its own column names
- [ ] 4 to 6 scanned amendments and one faxed side letter through `scans.py`
- [ ] About 120 email threads delivered into Mailpit: real side agreements from the authorized representative, the same agreement from an unauthorized property manager in another case, ambiguous promises, noise, out-of-office replies, and 3 injection attempts
- [ ] `tracker_xlsx.py`: the previous accountant's spreadsheet with merged cells, color-coded rows, free-text notes like "Clinic 9 abatement thru June per Dana", some notes right and some stale. This is the "colleague handed it over half done" source
- [ ] `replies.py`: landlord responses to disputes arriving in later months (full credit, partial credit, refusal with a reason)

### 4. Document understanding at full mess (20 h, Person A)
- [ ] Classifier for lease, amendment, side letter, rent invoice, CAM estimate, CAM reconciliation, tax or insurance bill, credit memo, late notice, other
- [ ] Image-only pages go through Claude vision. Store a per-page read quality score
- [ ] Invoice parser for all three formats returning line items with charge type, period, amount, page and box. Line items must sum to the stated total or a work item opens
- [ ] CAM reconciliation parser: category lines, claimed share, claimed fee, estimates paid, true-up
- [ ] Email ingestion from Mailpit: thread reconstruction, sender resolution against the lease notice clause (is this the authorized representative?), linking to clinic and landlord
- [ ] Tracker ingestion: each note becomes a low-trust claim linked to a clinic, never a rule
- [ ] Entity resolution for landlord and clinic names across all sources ("Pacific Crest Properties LLC" vs "Pacific Crest Prop. Mgmt")

### 5. Bitemporal rulebook and lease changes (14 h, Person B, cause-finding logic with A)
- [ ] Extend `lease_term` with `valid_from`, `valid_to` (when the term applies) and `recorded_at`, `superseded_at` (when we learned it)
- [ ] `rulebook/bitemporal.py`: `terms(lease, as_of_valid, as_known_on)`. This is what lets the system answer "what did we believe in March about June's rent"
- [ ] `agents/modification.py`: when charges diverge or a new amendment arrives, search pages and emails for the cause and propose a new version with citations. Signed amendments go to the regional manager to confirm. Lower-trust sources go to the resolver
- [ ] Suite moves and expansions update RSF and pro rata share from the effective date

### 6. CAM engine and shared pools (20 h, Person A)
- [ ] Allowed CAM per clinic: pool by category, exclusions, pro rata with the lease's own denominator, controllable cap against the base or prior year as the lease says, management fee cap, then compare to the landlord's statement line by line
- [ ] Shared pool check across all Northbay clinics in a center: flag any vendor line allocated beyond Northbay's combined share or billed in full to more than one clinic
- [ ] True-up recomputation: estimates paid vs allowed actuals
- [ ] Unit tests with hand-computed numbers for every rule and every planted CAM error type, plus Hypothesis tests that allocations never exceed 100% of a pool

### 7. Rent engine v2 with CPI (8 h, Person A)
- [ ] Fixed percent, fixed step and CPI escalations, with base month, lookback, floor, cap and rounding as each lease states
- [ ] CPI values from the BLS snapshot, with the exact series, month and value cited in the evidence
- [ ] Tests reproducing three escalations by hand

### 8. ASC 842 subledger and period close (26 h, Person A, ledger wiring by B)
- [ ] Transition at January 1, 2025 for leases in place, commencement accounting for leases that start later
- [ ] IBR table by remaining term in config, documented as an assumption and shown on every schedule
- [ ] Liability as the present value of remaining fixed payments. ROU asset as liability plus prepaid rent and initial direct costs minus incentives
- [ ] Monthly entry: Dr Lease cost (straight-line), Dr Lease liability (payment minus accretion), Cr ROU asset (straight-line minus accretion), Cr Cash or AP (payment). Current and non-current split of the liability
- [ ] Variable payments (CAM, tax, insurance, CPI changes after commencement) expensed as incurred
- [ ] Modifications not treated as a separate contract: remeasure at the modification date with an updated rate, adjust ROU by the same amount, propose the entry for controller approval
- [ ] Held CAM amounts: accrue the lease-supported amount, record the disputed difference in the dispute register, never expense money we believe is not owed without a decision
- [ ] `ledger/close.py`: per entity close checklist (all charges resolved or held with accrual, schedules posted, subledger liability and ROU tie to GL to the cent, no open questions over materiality), controller sign-off, then lock
- [ ] Hand-build two leases in a spreadsheet (one plain, one with a remeasurement) and assert the engine matches to the cent. Property tests that every generated entry balances

### 9. Resolver: trust, confidence, routing, busy people (20 h, Person B, logic with A)
- [ ] Every work item carries `sources`: each source, its trust rank, the value it claims, and its citation
- [ ] Decision rule from the trust ranking above, written as code and shown in the UI as "trusted the executed amendment over the invoice because..."
- [ ] Confidence: documented formula combining extraction confidence, read quality, source agreement, trust gap and policy coverage, with the reasons listed
- [ ] Routing: landlord facts to the clinic's regional manager, accounting judgments and policies to the controller, payment release to the AP clerk, anything over a materiality threshold also to the controller
- [ ] Partial payment: when only part of a charge is disputed, the undisputed portion proceeds through normal approval and only the disputed amount is held
- [ ] Busy approvers: questions have a due date on the business clock, reminders at set intervals, escalation to the controller after the SLA, and if the payment due date arrives first, pay the undisputed portion and keep holding the rest
- [ ] Handoffs: tracker notes and items left in NEEDS_INFO by the previous accountant are imported as open work with their history, not discarded

### 10. Policy engine (24 h, Person B, learning prompts with A)
- [ ] Rule format in JSON: scope (entity, landlord, lease, clinic), when (charge type, conditions), then (approve, hold, dispute, treat as account X, trust source Y), effective dates, evidence ids, version
- [ ] `engine/policies.py` evaluates rules deterministically and returns the matching policy id and version
- [ ] Onboarding: scan 2025 history and propose policies with precedent counts and the past decisions linked
- [ ] From answers: generalize only as far as the evidence supports, propose to the controller, link the question, answer and documents
- [ ] Backtest before approval: run the proposed policy over all past periods and show which decisions would change, how many dollars, and any conflicts with existing policies
- [ ] Rejection memory: a rejected policy and its reason are stored and not proposed again without new evidence
- [ ] Every decision driven by a policy records its id and version in the event

### 11. Disputes and landlord correspondence (12 h, Person B)
- [ ] Dispute letter drafted from structured facts, citing lease section and page, the math and attached evidence, sent to the notice address in the lease
- [ ] Regional manager approves, gateway sends through the outbox to Mailpit
- [ ] Dispute register with status (sent, acknowledged, credited, partially credited, refused). Landlord receivable posted when the controller approves recognizing it
- [ ] Credit memos matched back to disputes and the receivable cleared. Refusals reopen the item to the regional manager with the landlord's reason

### 12. Obligations and critical dates (8 h, Person B)
- [ ] Renewal notice deadlines, CAM audit windows, deposit return dates, expirations, all from the rulebook with citations
- [ ] Work items at 90, 60 and 30 business days, routed to the regional manager, decisions recorded on the lease

### 13. Human personas for unattended runs (10 h, Person A)
- [ ] Each persona has a facts file (what they know, what they agreed to by phone, what they would refuse), a response delay, and a small chance of being unavailable
- [ ] Persona answers are generated by Claude from the facts file only, with the question as input, and every answer is tagged `simulated` in the event
- [ ] The controller persona sometimes says no, so the "handles a no" path is exercised every run

### 14. "Why?", auditor role and evidence packs (10 h, Person B)
- [ ] Why agent with fixed query tools only: timeline_for, decisions_by_policy, sources_for, denied_attempts, as_known_on. Answers in two or three sentences plus the rows used
- [ ] Auditor role (read-only DB role and UI role) can request an evidence pack for any number: a PDF with the lease clauses, invoices, calculations, approvals, policy versions and a chain verification stamp

### 15. Safety and defense in depth (8 h, Person B)
- [ ] All documents and emails go to the model as fenced untrusted data. The model can only call work tools and every call goes through `can()`
- [ ] Adversarial set: injection emails, a forged "authorized representative" email from the wrong domain, an invoice with hidden white text, an instruction to change bank details. Each must produce zero unauthorized state change
- [ ] Defense-in-depth tests: even if `can()` is bypassed in a test harness, the `lease_agent` DB role still cannot write the ledger or outbox

### 16. Eval v2, held-out scoring and counterfactual replay (14 h, Person A)
- [ ] Metrics per error type: caught, missed, false holds, correct trusted source, correct route, correct outcome, correct journal impact, dollars
- [ ] Workflow metrics: straight-through rate, questions per 100 charges by month, repeated questions after a policy existed, median time to resolution on the business clock
- [ ] Policy metrics: precision of learned policies, backtest accuracy
- [ ] Extraction accuracy on EDGAR vs synthetic leases
- [ ] Safety metrics: adversarial cases passed, unauthorized writes blocked, chain integrity
- [ ] Cost per clinic per month from the usage log
- [ ] Held-out company score, reported next to the development score
- [ ] Counterfactual replay: rerun any past month with today's policies and rulebook "as known on" today, and show the diff. This powers the "what March would look like with June's knowledge" view
- [ ] HTML report rendered in the app

## Deliverables / Definition of Done
- `make seed && make run-range FROM=2026-01 TO=2026-12 && make eval` runs unattended on the dev company, and `make eval-heldout` runs on the held-out company
- The double-billed parking lot repaving is caught with every affected statement and the share clause, only the disputed amount is held, the regional manager is asked
- At least two remeasurements approved by the controller, engine matches the hand-built spreadsheets to the cent
- Every month closes with subledger tied to GL and a controller sign-off, closed months are locked
- At least four onboarding policies, at least two answer-driven policies, at least one rejection remembered, all cited in later events
- All adversarial cases pass with zero unauthorized state changes
- Targets on the held-out company: at least 90% of planted errors caught, false holds under 3% of charges, 100% of unauthorized writes blocked, questions per 100 charges falling month over month. Any miss is explained in the report

## Acceptance Criteria / How to Verify
- Run the full year twice from scratch: identical eval numbers
- Open March: CAM reconciliation for the three-clinic center shows the duplicate line flagged with all affected statements, the trust explanation and the paid undisputed portion
- Ask "why?" about any held item: the answer names the conflicting sources, which one was trusted and why, who was asked and what they said, with rows shown
- Backtest a new policy as the controller: the chart shows changed decisions and dollars before approval
- Pull an evidence pack as the auditor for one clinic's 2025 CAM: every number has a document behind it and the chain stamp verifies
- Counterfactual replay of March with December's knowledge shows a sensible diff, including items that would no longer need a question

## Risks & Mitigations
- **Accounting mistakes in CAM or ASC 842 in front of finance judges.** Mitigate with deterministic engines, hand-built spreadsheet checks, property tests, stated assumptions in the UI and README, and a review with the Hyphenate engineers at their booth.
- **Overfitting to our own generated data.** A system tuned on its own generator can score well and still be fragile. Mitigate with the held-out company from a different seed and landlord set, the EDGAR benchmark on real documents, and a rule that eval thresholds are reported on held-out numbers.
- **The system asks too much and stops feeling autonomous.** Mitigate with onboarding policies, partial payment of undisputed amounts, the trust ranking for clear cases, and the questions-per-100-charges metric as a tracked target that must fall over the year.

## Estimated Effort

| Task group | Hours | Share of phase | Share of project |
|---|---|---|---|
| 1. EDGAR corpus and labels | 14 | 5.6% | 2.8% |
| 2. Company generator v2 and held-out company | 26 | 10.4% | 5.2% |
| 3. Messy inputs | 16 | 6.4% | 3.2% |
| 4. Document understanding at full mess | 20 | 8.0% | 4.0% |
| 5. Bitemporal rulebook and lease changes | 14 | 5.6% | 2.8% |
| 6. CAM engine and shared pools | 20 | 8.0% | 4.0% |
| 7. Rent engine v2 with CPI | 8 | 3.2% | 1.6% |
| 8. ASC 842 subledger and close | 26 | 10.4% | 5.2% |
| 9. Resolver | 20 | 8.0% | 4.0% |
| 10. Policy engine | 24 | 9.6% | 4.8% |
| 11. Disputes and correspondence | 12 | 4.8% | 2.4% |
| 12. Obligations and critical dates | 8 | 3.2% | 1.6% |
| 13. Human personas | 10 | 4.0% | 2.0% |
| 14. Why, auditor, evidence packs | 10 | 4.0% | 2.0% |
| 15. Safety and defense in depth | 8 | 3.2% | 1.6% |
| 16. Eval v2, held-out, counterfactual replay | 14 | 5.6% | 2.8% |
| **Phase 2 total** | **250** | **100%** | **50%** |

Split by person: roughly 154 hours Person A (groups 1 to 4, 6 to 8, 13 and 16: data, documents, engines, personas, eval), roughly 96 hours Person B (groups 5, 9 to 12, 14 and 15: rulebook versioning, resolver, policy engine, disputes, obligations, auditor, safety, plus the UI for all of it). If Person B finishes first, they pick up the ASC 842 ledger wiring and close checklist from group 8.

## Handoff to Next Phase
A complete lease accountant over a messy, realistic, three-entity company, running a full year unattended, closing every month, explaining every decision from a hash-chained history, and scored on a company it has never seen. Every judging question already has its evidence: the held-out and EDGAR scores for "real enough", the routing, limits and evidence packs for "would you hire it", bitemporal leases with CAM and policy backtests for "something new", and the double billing catch with partial payment for the moment. Phase 3 adds no new accounting. It makes the product feel finished, impossible to break in front of judges, deployed, and packaged for Hyphenate, Microsoft and Fetch.ai.
