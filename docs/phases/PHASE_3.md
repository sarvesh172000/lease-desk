# Phase 3 - Product Polish, Hardening and Multi-Track Delivery

> **Status — this phase is Block C, chunks C1–C9.** See [`../PLAN.md`](../PLAN.md).
>
> Two groups are added beyond the ten below, both sponsor targets:
> **11. SpacetimeDB** (14 h, chunk C5) and **12. Anthropic depth** (12 h, chunk
> C6), specified in [`../SPONSORS.md`](../SPONSORS.md).
>
> | Group | h | Chunk | Owner |
> |---|---|---|---|
> | 1. Product design and UI polish | 22 | C1 | B |
> | 2. Guided demo, summaries, snapshots | 12 | C2 | B |
> | 3. Scenario studio | 12 | C2 | B |
> | 4. Reliability and chaos testing | 14 | C3 | A+B |
> | 5. Performance and cost | 8 | C4 | A |
> | 6. Testing and QA | 12 | C4 | A+B |
> | 7. Cloud deployment and ops | 14 | C7 | B |
> | 8. Microsoft deliverables | 10 | C7 | A |
> | 9. Fetch.ai / ASI:One front door | 22 | C8 | B |
> | 10. Submission package and rehearsals | 14 | C9 | A+B |
> | **11. SpacetimeDB live layer** *(new)* | **14** | **C5** | **B** |
> | **12. Anthropic depth** *(new)* | **12** | **C6** | **A** |
>
> Nothing in Block C is started.

**Budget: 166 of 526 hours (32%)** — 140 below, plus 26 for the two added
sponsor groups (11 SpacetimeDB, 12 Anthropic).

## Goal
Make Lease Desk feel like a finished product a controller would trust on day one, make it impossible to break in front of judges, and package one system for three tracks. The UI becomes a real finance tool: a "Today" screen for each role, an evidence viewer that reads like a case file, a rulebook timeline you can scrub through time, policy backtests and a close dashboard per entity. The system gets chaos-tested (killed workers, failing model calls, a dead mail server, duplicate syncs) and must recover without losing or doubling anything. It is deployed on Azure with a local fallback, the Microsoft judges get a real path to production with measured cost, and the Fetch.ai judges get a multi-agent front door in ASI:One built on the same backend and the same permissions. When this phase is done, a guided demo opens with the double billing catch and walks every judging question in under three minutes, judges can throw their own scenario at it live, and everything is submitted with the evidence up front.

## Scope
- In scope:
  - Design system and UI polish across every screen, role-based "Today" screens, command palette, keyboard flow
  - Guided demo mode, run summary screens, demo snapshots and one-click reset
  - Scenario studio for judges
  - Chaos and soak testing with automatic recovery
  - Performance work and LLM cost reduction
  - Test suite completion: end-to-end per role, API contract tests, accessibility checks
  - Azure deployment, secrets, CI/CD, health checks, structured logs, local fallback
  - Microsoft deliverables: persona, measured usefulness, rollout plan, cost per clinic, responsible design
  - Fetch.ai: multi-agent front door registered on Agentverse, Chat Protocol, usable in ASI:One, Interactive Cards, optional Payment Protocol
  - README, docs, architecture diagram, demo video, slides, pitch, Devpost, rehearsals
- Out of scope:
  - New accounting logic, new document types or new error types. Gaps found now go into the README's known gaps list
  - Real ERP, bank or landlord portal integrations (written into the rollout plan, not built)

## Prerequisites & Dependencies
- Phase 2 Definition of Done met on the held-out company, all CI gates green
- Azure subscription with permission to create Container Apps, Azure Database for PostgreSQL Flexible Server, Blob Storage and Key Vault
- Agentverse and ASI:One accounts for the Fetch.ai work
- Confirmed submission rules for each track, including whether one Devpost project can enter multiple sponsor tracks
- Priority if hours run short, in order of what gets cut first: Payment Protocol, Fetch.ai specialist agents (keep the single front desk agent), extended 5-minute demo, cloud deployment polish (keep local). The guided demo, scenario studio and chaos recovery are never cut

## Tech, Tools & Components
Everything from Phases 1 and 2, plus:
- **UI:** shadcn/ui components on a small token-based design system (type scale, spacing, light and dark color tokens), `cmdk` for the command palette, Recharts for dashboards, react-pdf with synced scrolling between documents
- **Testing:** Playwright end-to-end per role, schemathesis for API contract tests against the FastAPI OpenAPI schema, axe-core accessibility checks through Playwright, Locust for load on the worker and API
- **Reliability:** tenacity retries, circuit breaker around the LLM client, worker heartbeats with stuck-job recovery, pg_dump and pg_restore snapshots
- **Azure:** Azure Container Apps (api, worker, web), Azure Database for PostgreSQL Flexible Server, Azure Blob Storage through the existing storage adapter, Azure Key Vault for secrets, GitHub Actions for build and deploy, Log Analytics for container logs. An optional config switch to route LLM calls to Azure OpenAI if the Microsoft judges ask for Microsoft models
- **Fetch.ai:** `uagents` and `uagents_core` packages, Agent Chat Protocol (`chat_protocol_spec`, `ChatMessage`, `ChatAcknowledgement`, `TextContent`, `StartSessionContent`, `EndSessionContent`), Agentverse mailbox connection, ASI1 Interactive Cards, Fetch.ai Payment Protocol if time allows
- **Video:** OBS for capture, any editor for cuts

New modules (inside the fixed layout):

```
frontend/app/
  today/          role-based home
  demo/           guided stepper and run summaries
  studio/         judge scenario studio
  rulebook/       timeline view over the bitemporal rulebook
  close/          per-entity close dashboard
  policies/       policy list, diff and backtest views
agents_fetch/
  front_desk.py   ASI:One entry point, Chat Protocol, pairing
  rulebook_agent.py   answers lease questions with citations
  approvals_agent.py  lists and answers open questions for the paired actor
  cards.py        Interactive Card builders
ops/
  azure/          Container Apps, Postgres, Blob, Key Vault definitions
  chaos/          fault injection scripts
  snapshots/      demo database snapshots
```

## Task Breakdown

### 1. Product design and UI polish (22 h, Person B)
- [ ] Design tokens and type scale, light and dark themes, consistent spacing, one icon set. Run the frontend-design pass so it reads as a finance tool, not a template
- [ ] "Today" screen per role: regional manager sees their open questions with due dates and the dollars at stake, AP clerk sees batches ready to release, controller sees policies to approve, close status per entity and anything over materiality, auditor sees evidence pack requests
- [ ] Evidence viewer as a case file: sources listed by trust rank, each with its claim and citation, documents side by side with synced scrolling and boxed highlights, the trust explanation, confidence with its reasons, the policy that applied, and the full timeline below
- [ ] Rulebook timeline: a slider over valid time and a toggle for "as known on", showing how a lease's terms changed and when the system learned each change
- [ ] Policy views: list with status and version, side-by-side diff between versions, backtest chart and table of changed decisions
- [ ] Close dashboard per entity: checklist progress, subledger to GL tie-out, open items, sign-off button for the controller
- [ ] Command palette and keyboard shortcuts (approve, hold, next item, open evidence)
- [ ] Empty, loading and error states for every screen, readable on a projector at 1280 wide

### 2. Guided demo, run summaries and snapshots (12 h, Person B, script by A)
- [ ] Snapshot after onboarding and January to March. `make demo-reset` and a controller-only button restore it in under 30 seconds, locally and in the cloud
- [ ] Run summary for any month: "April, Northbay Coffee California: 12 clinics, 148 charges checked, 139 approved, 6 held for $9,840, 3 disputes drafted, 2 questions out, batch ready for AP by 9:00 AM", every number clickable
- [ ] Guided stepper, each step one click away:
  1. **The moment:** parking lot repaving billed in full to three clinics in one center, the statements side by side with the share clause boxed, the undisputed portion paid, only the disputed amount held
  2. **Learns:** onboarding policy with precedents and the 2025 decisions behind it
  3. **Runs:** April run summary across all three entities
  4. **Escalates:** CAM cap in the lease vs a March email from an unauthorized property manager, the trust explanation, confidence 0.38, routed to the regional manager, reminder sent when they did not answer
  5. **Improves:** the manager answers live, a policy is proposed, the backtest shows what changes, the controller approves, the rerun cites the new policy
  6. **Limits:** the agent tries to approve, a manager tries to approve their own answer, and a raw SQL insert as the agent role all fail and show in the audit timeline
  7. **Time:** counterfactual replay of March with today's knowledge
  8. **Proof:** held-out score, EDGAR extraction score, an auditor evidence pack, chain verified
- [ ] A 3-minute core path (steps 1, 3, 4, 5, 6, 8) and a 5-minute full path

### 3. Scenario studio for judges (12 h, Person B)
- [ ] Controller-only panel: upload any invoice or amendment PDF or CSV, compose an email from any sender, edit a lease term with an effective date, or pick a forbidden action
- [ ] "Run checks now" processes only the affected clinic and period and jumps to the result
- [ ] Ten prepared scenarios tested end to end: new duplicate invoice, rent cut claimed in email only, scanned amendment with new rent, forged authorized-representative email, injection email, bank detail change request, CPI escalation applied a month early, CAM line already billed to another clinic, payment above schedule without approval, an approver trying to self-approve
- [ ] Studio inputs are tagged as judge-provided in the audit stream and cleared by demo reset

### 4. Reliability and chaos testing (14 h, Person A and B)
- [ ] Fault scripts in `ops/chaos/`: kill the worker mid-month, return errors from the LLM client, stop Mailpit, restart Postgres, deliver the same sync file twice, deliver events out of order
- [ ] Expected behavior for each, asserted by tests: jobs resume from where they stopped, no duplicate work items, entries or emails, LLM failures fall back to cache or route a "could not read" item to a human, outbox retries until the mail server returns, chain still verifies
- [ ] Circuit breaker on the LLM client so a provider outage holds work instead of failing it
- [ ] Soak test: run three simulated years back to back and check the chain, replay equality, trial balance and close tie-outs at the end

### 5. Performance and cost (8 h, Person A)
- [ ] Parallel extraction with bounded concurrency, batching of small classification calls, cache hit reporting
- [ ] Targets: a cold month for 30 clinics under 3 minutes, a warm month under 20 seconds, the demo path with zero uncached model calls except studio inputs
- [ ] Reduce cost per clinic per month by routing simple classification to a smaller Claude model where eval shows no loss, and report before and after

### 6. Testing and QA (12 h, Person A and B)
- [ ] Playwright end-to-end for each role's main path and for the full guided demo from reset
- [ ] schemathesis contract tests on every API endpoint, including that every write endpoint rejects actors without permission
- [ ] axe-core accessibility checks on the main screens, fixing anything serious
- [ ] Locust load test on the API and worker at five times the demo volume
- [ ] Final regression: eval on dev and held-out companies equals or beats the Phase 2 baseline

### 7. Cloud deployment and operations (14 h, Person B)
- [ ] Container images for api, worker and web, pushed by GitHub Actions on merge to `main`
- [ ] Azure Container Apps for the three services, Azure Database for PostgreSQL Flexible Server with the four DB roles created by migration, Azure Blob behind the storage adapter, secrets in Key Vault
- [ ] Health and readiness endpoints, structured JSON logs to Log Analytics, an ops page in the app showing job queue depth, last run per entity, cache hit rate and spend
- [ ] Demo snapshot restored in the cloud, HTTPS, a judge account per role
- [ ] Local fallback on both laptops with the same snapshot, plus a phone hotspot plan. No secret is ever committed, keys rotated before the repo goes public

### 8. Microsoft deliverables (10 h, Person A)
- [ ] **Customer understanding:** personas for the lease accountant, regional manager and controller at a 30-clinic group, plus notes from real conversations at the venue with anyone who has done lease accounting or property management
- [ ] **Measurable usefulness:** from eval on the held-out company: errors caught, dollars recovered, false holds, straight-through rate, questions per 100 charges by month, close time, EDGAR extraction accuracy
- [ ] **Path to production:** one-page rollout: shadow mode on 12 months of history, assisted mode with every decision approved, then autopilot within policies and materiality thresholds. Connectors: ERP journals and AP, inbox ingestion, portal exports. Running cost per clinic per month measured from the usage log, and the hosting cost of the Azure setup
- [ ] **Responsible design:** limits enforced in code and in the database, separation of duties, gateway as the only writer, hash-chained audit, untrusted-content handling with adversarial results, no payment ever made by the system, simulated personas clearly labeled, data minimization
- [ ] **End to end:** link the guided demo, the full-year run and the reproducible eval
- [ ] Ask the Microsoft judges early whether they want Azure OpenAI. If yes, turn on the model switch and rerun eval to show parity

### 9. Fetch.ai / ASI:One front door (22 h, Person B, agent logic with A)
- [ ] `front_desk.py`: a uAgents agent "Northbay Lease Desk" implementing the Chat Protocol with acknowledgements and session handling. It talks to the existing API only, never to the database
- [ ] Two specialist agents, also registered: `rulebook_agent` answers lease questions with citations ("what is Clinic 14's CAM cap and where does it say so?"), `approvals_agent` lists and answers open questions for the paired actor. The front desk routes to them over agent messaging, which demonstrates multi-agent collaboration on real work
- [ ] Pairing: a one-time code from the web app's Today screen links an ASI:One user to an actor. Every action still goes through `can()`, the gateway and the audit stream. Chat input is treated as untrusted
- [ ] Primary workflow fully inside ASI:One: "what needs me this week?", review a held item through an Interactive Card with the sources and the trust explanation, answer it, approve a dispute letter, ask "why was this held?"
- [ ] Register all three agents on Agentverse through the mailbox, confirm discoverability from ASI:One, capture the public shared chat URL and Agentverse profile URLs
- [ ] README section listing each agent's name and address with the Innovation Lab and hackathon badges required by the Fetch.ai hackpack
- [ ] Payment Protocol, only if hours remain: a contingency fee on dollars actually recovered through disputes, charged when a credit memo clears. Leave it out rather than ship something not credible

### 10. Submission package and rehearsals (14 h, both)
- [ ] One line on the seat: "Lease Desk fills the lease accountant seat at a 30-clinic physical therapy group: it drafts every rent and CAM payment and lease entry across three entities, never pays, and asks the regional manager when a landlord's bill and the lease disagree."
- [ ] README: setup in a few commands, architecture diagram, how the four beats map to code, what is real (EDGAR leases, CPI data, accounting rules, permission model, database roles) and what is simulated (Northbay, landlords, invoices, emails, personas), how we know (dev and held-out eval, EDGAR benchmark, adversarial set, chaos results), assumptions (IBR table, transition date, operating leases only), known gaps
- [ ] Slide in Hyphenate's own Real, Hireable, New, Wow format with our numbers
- [ ] Demo video cuts: 2 minutes opening with the moment for Hyphenate and Microsoft, 3 to 5 minutes for Fetch.ai including the ASI:One workflow
- [ ] Pitch scripts at 30 seconds and 2 minutes, both opening with the moment
- [ ] Devpost entries for each track, and the CalHacks ASI:One submission agent registration for Fetch.ai
- [ ] Five full rehearsals from reset, each teammate presenting alone at least twice, one rehearsal fully offline on the local fallback
- [ ] Final check before submitting: fresh clone works, cloud and local both restored, every link opens in a private window, every number in the README and slide matches `eval/report.json`

## Deliverables / Definition of Done
- Every screen polished, Today screens for every role, guided demo in 3 and 5 minute versions
- Ten studio scenarios behave correctly
- All chaos scenarios recover with no lost or doubled work, soak test passes
- End-to-end, contract, accessibility and load tests green, eval at or above the Phase 2 baseline on both companies
- Cloud deployment live on Azure with the demo snapshot, local fallback ready
- Microsoft deliverables written with measured numbers
- Three Fetch.ai agents registered and the full primary workflow shown in a public ASI:One chat
- Submissions complete for every target track

## Acceptance Criteria / How to Verify
- Someone outside the team watches the 2-minute video once and can say what seat it fills, what it caught and why they would trust it
- A judge-style scenario typed live in the studio produces the right hold, routed to the right person, with the right source trusted, and nothing paid
- Kill the worker during the April run in front of a teammate: the run finishes after restart with identical results to an uninterrupted run
- Pair an ASI:One account as the Desert regional manager and try to answer a Bay Area question from chat: denied, and the denial shows in the web app's audit timeline
- Every number on the slide traces to the eval report, and every number in the eval report reproduces from a fresh clone

## Risks & Mitigations
- **Live demo failure from wifi, cloud or model outages.** Mitigate with snapshots, a demo path that needs no fresh model calls, the circuit breaker, a tested offline rehearsal and the local fallback.
- **Polish and extras eat the hours meant for reliability.** Mitigate with the fixed cut order in Prerequisites, and by finishing chaos recovery and the scenario studio before starting Fetch.ai specialist agents or the Payment Protocol.
- **Three tracks dilute the story.** Mitigate by keeping one product and one moment everywhere, and changing only the emphasis: autonomy and evidence for Hyphenate, customer and production path for Microsoft, agents working inside ASI:One for Fetch.ai.

## Estimated Effort

| Task group | Hours | Share of phase | Share of project |
|---|---|---|---|
| 1. Product design and UI polish | 22 | 15.7% | 4.4% |
| 2. Guided demo, summaries, snapshots | 12 | 8.6% | 2.4% |
| 3. Scenario studio | 12 | 8.6% | 2.4% |
| 4. Reliability and chaos testing | 14 | 10.0% | 2.8% |
| 5. Performance and cost | 8 | 5.7% | 1.6% |
| 6. Testing and QA | 12 | 8.6% | 2.4% |
| 7. Cloud deployment and ops | 14 | 10.0% | 2.8% |
| 8. Microsoft deliverables | 10 | 7.1% | 2.0% |
| 9. Fetch.ai / ASI:One front door | 22 | 15.7% | 4.4% |
| 10. Submission package and rehearsals | 14 | 10.0% | 2.8% |
| **Phase 3 total** | **140** | **100%** | **28%** |

Split by person: roughly 60 hours Person A (half of 4 and 6, plus 5, 8, half of 10, and agent logic in 9), roughly 80 hours Person B (1, 2, 3, 7, most of 9, and the other halves).

## Handoff to Next Phase
This is the final phase. The handoff is a submitted, deployed and rehearsed product: a reproducible repo, a live Azure deployment with a local fallback, three registered Fetch.ai agents, and a team that can present it cold. If the project continues after the hackathon, the rollout plan from the Microsoft deliverables is the next roadmap: real ERP and inbox connectors, shadow mode on a real company's leases, then widening from the lease accountant seat into CAM audits, lease renewals and landlord negotiations.
