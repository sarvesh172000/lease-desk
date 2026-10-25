# Prompt for Claude Design — Lease Desk

> Paste everything below this line as your first message. Attach
> `frontend/DESIGN_BRIEF.md`, `frontend/UI_PLAN.md`, `frontend/lib/types.ts`
> and a few screenshots from `frontend/docs/screenshots/`.

---

You are designing the complete web app for **Lease Desk**, a product competing
at Cal Hacks 13.0. I want the most striking, alive, interactive finance product
the judges have ever seen — and one a CFO would still trust with the books.
Design it screen by screen, show me each round, and wait for my approval
before moving on. Deliver production-ready **Next.js 15 (App Router) + React 19
+ TypeScript + Tailwind 3** components I can drop into an existing codebase.

## 1. The product in one breath

Lease Desk fills the **lease accountant's seat** at a 30-store coffee
chain (Northbay Coffee). Every month, a team of AI agents
reads every landlord invoice, checks every charge against what the lease
actually says, drafts payments and accounting entries, and **holds only the
money that is wrong** — showing the billed line in the invoice and the clause
in the lease side by side, boxed on the real PDF. It never pays and never signs
off: a person approves. Every action — including every *refused* attempt — is
written to a tamper-evident, hash-chained audit trail, and the database itself
refuses anything an agent isn't allowed to do.

Judges see it on a **projector at 1280 px wide for 2–3 minutes**. They must
leave knowing *what seat it fills, what it caught, and why they'd trust it.*

## 2. The feeling — "mission control for money"

Bold, cinematic, premium; think Linear × Stripe × Vercel × Apple keynote, with
real depth and motion. **Not** neon sci-fi HUD (finance judges read that as a
toy).

- Deep near-black surfaces, one electric teal accent (`rgb(94 234 212)`),
  semantic ok/bad/warn/escalated colours, glass and gradient used with
  restraint, type doing most of the work. Light theme also required.
- **Motion that explains, never decorates:** documents slide in side by side;
  the box around the billed line and the lease clause *draws itself*; the
  investigation unfolds stage by stage; debits and credits "settle" into
  balance; a held amount visibly peels off the payment.
- **3D where it carries meaning** (React Three Fiber + drei, lazy-loaded):
  1. **Portfolio constellation** — the 30 clinics as glowing nodes on a
     stylised West-Coast map / globe, grouped by region (Bay Area, SoCal,
     Desert), node size = monthly rent, colour = status; hover a node for the
     lease card, click to fly in.
  2. **The document stack** — while the agent investigates, a 3D stack of
     invoices, lease pages and emails fans out; the one it found lifts to
     the front and lands in the viewer.
  3. **The hash chain** — audit events as linked translucent blocks in a
     receding chain; each block shows seq, actor, action; refused attempts are
     red blocks *in* the chain (first-class, not errors); a "tamper" demo
     toggle makes the chain visibly crack at the broken sequence number.
  4. **The ledger settle** — a balance scale / two columns that level when
     debits = credits, with a satisfying lock.
- **Alive:** count-up numbers (ending on the exact value), live status pulses
  when someone else approves (we stream live updates), agent activity ticker,
  skeleton shimmer while loading, micro-interactions on every control,
  ⌘K command palette, keyboard shortcuts (A approve, H hold, J/K next/prev).

**Non-negotiable:**
- Every number comes from the API. The UI never computes, rounds or invents
  money. Money is tabular, right-aligned, two decimals; red only for a real
  problem.
- Exactly four exception statuses: `balanced`, `exception`, `pending_review`,
  `escalated`. Work states (8): NEW, PROPOSED, NEEDS_INFO, HELD, APPROVED,
  POSTED, REJECTED, CLOSED.
- Respect `prefers-reduced-motion` (fall back to fades); motion never blocks a
  click; 3D never delays the first paint; every 3D view has a flat 2D
  fallback.
- Legible at 1280 px on a washed-out projector; WCAG AA contrast in both
  themes; full keyboard navigation.
- Show only the actions the server allows for this person (an
  `allowed_actions` list comes from the API).

## 3. The three demo beats (design around these)

1. **The hidden amendment.** STORE-01's July rent stops matching by
   **−$2,226.65**. The agent searches the mailbox, finds an executed amendment
   (trust rank 1, confidence 94%) that cut rent to $17,400 and extended the
   lease 3 years, remeasures under ASC 842 — liability
   **$559,665.35 → $1,002,921.05 (+$443,255.70)** — and proposes four
   balanced journal entries for the controller.
2. **January.** 12 charges checked, **5 held for $25,736.36** — including a
   rent invoice billed twice (both copies individually correct) and rent for a
   suite the clinic doesn't lease. Approving a hold *upholds* it: only the
   supported amount posts; a dispute letter is drafted to the landlord.
3. **Trust.** The agent tries to post to the ledger and the database refuses;
   a regional manager from another region tries to approve and is refused;
   both refusals sit in the audit chain and the chain still verifies.

## 4. People (role switcher in demo mode)

Controller (Priya Raghunathan) · Regional manager, Bay Area (Dana Whitfield) ·
Regional manager, Desert (Theo Lindqvist) · AP clerk (Marcus Oyelaran) ·
External auditor (read-only). The same screens change with the role; design
a "Today" view per role.

## 5. Screens and the real data on each

Field names are the API's; full shapes are in the attached `types.ts`.

**App shell** — left rail nav (Today, Month, Exceptions, Leases, Disputes,
Obligations, Policies, Questions, Audit), entity/period picker, role switcher
with avatar, theme toggle, live-connection pulse, ⌘K, data-source badge
(LIVE API vs OFFLINE fixtures).

**Today `/`** — `Summary`: active_leases, open_exceptions, pending_review,
held_total, held_count, portfolio_liability (count-up tiles with sparkline
accents). Exception queue (`ExceptionSummary`: status, title, lease_id,
clinic_id, period, expected, actual, variance, confidence) as a dense,
animated table/list. Agent activity feed. Per role: controller = approvals +
liability; RM = their region's questions and holds; AP = batch readiness;
auditor = chain status + refused attempts.

**Month run `/month`** — `MonthSummary`: headline, metrics {clinics,
checked, approved, held, disputes, questions, batch}, each a step in a
**guided stepper / pipeline** (ingest → read leases → check → hold →
dispute → batch) with a drill-down list per metric (`MonthSummaryRow`).
Batch panel: ready, released, awaiting_decision, releasable,
releasable_total, and a **Release batch** action (AP clerk).

**The money screen `/exceptions/[id]` (the hero)** — header (title,
status, expected / actual / variance, explanation, confidence ring); **two
real PDF pages side by side** (invoice with billed line boxed, lease or
amendment with clause boxed; boxes are `[x0,y0,x1,y1]` in PDF points);
evidence card (quote, source, trust rank 1–6 with labels, date,
confidence); **resolver sources** (`ItemSources`: ranked sources, which one
was trusted and why, confidence reasons, route, who was asked); the
streamed investigation timeline (searching → found → remeasured → complete)
with the 3D document stack; journal entries with a visible **balanced**
assertion; remeasurement before/after; actions Approve / Hold /
Pay as billed (controller, needs a reason) / Ask a question; **"Why?"**
button opening a chat drawer that answers in 2–3 sentences with the rows
behind it; **Evidence pack** download (PDF; shows "chain verified").

**Leases `/leases`** — `LeaseSummary`: lease_id, clinic_id, location,
lessor, status, monthly_rent, liability, end; filters and counts; the **3D
portfolio constellation** with a table toggle. **Lease detail
`/leases/[id]`** — ASC 842 schedule (period, payment, interest,
liability_open, liability_close, rou_close, straight_line_cost) as an
animated chart + table; versions v1 → v2 with cited terms and a "confirm
version" action for the regional manager (`LeaseVersion`, `LeaseTerm`);
obligations for this lease.

**Disputes `/disputes`** — `DisputeList` with counts by status (drafted,
sent, acknowledged, credited, partially_credited, refused) as a kanban or
pipeline. **Dispute detail** (`DisputeDetail`): the drafted letter rendered
like real correspondence (notice_to, facts, amount), history timeline,
credits received, receivable; actions: approve letter (RM), approve
receivable (controller), record landlord reply (acknowledged / credit full or
partial / refused).

**Obligations `/obligations`** — `Obligation`: kind, lease, clinic,
due_date, days_left, action, citation (lease clause). A **timeline / calendar
river** of upcoming deadlines (renewal notices, CAM audit windows,
escalations) with urgency colour; filter by kind and window.

**Policies `/policies`** — `PolicySummary`: name, version, status (proposed /
approved / rejected / retired), scope, action, charge_types,
precedent_count, backtest summary. **Policy detail** (`PolicyDetail`): the
rule in plain words, versions, evidence, **backtest visual** (what would
have changed historically, conflicts), "cited by" decisions; actions:
run backtest, approve / reject (controller), onboard from history.

**Questions `/questions`** — an inbox of open questions the agents asked
people (`Questions`/`QuestionItem`): who is asked, about which item, payment
due date; answer inline.

**Audit `/audit`** — `AuditResponse`: chain_verified, broken_seq,
events (seq, at, actor_id, action, subject, allowed, reason, policy_ref).
The **3D hash chain** plus a filterable table; refused attempts highlighted;
"Verify chain" moment.

**Connect chat `/settings/chat`** — pair your ASI:One chat: show an 8-char
one-time code (10-minute countdown), active pairings with revoke.

**Login `/login`** — email + password; demo persona cards when demo mode is
on. **Landing `/welcome`** — a scroll-told story of the three beats with the
real numbers, ending in "Open the desk".

**Demo controls** (controller, demo mode only) — "Reset demo" with a
confirm dialog and progress.

## 6. States to design for every screen

Loading (skeletons), empty, error (with retry), offline fixtures badge,
permission-refused (403 with the reason from the server, shown calmly),
reduced motion, light theme, 1280 × 800 and 1920 × 1080.

## 7. Handoff rules (so it drops straight in)

- Next.js App Router + TypeScript + Tailwind; motion with `framer-motion`;
  3D with `@react-three/fiber` + `@react-three/drei`, dynamically imported
  (`next/dynamic`, `ssr: false`).
- All colours from CSS-variable tokens (dark + light), no hex values inside
  components. Radius 6/10/14/20; motion 120/200/420 ms,
  `cubic-bezier(.2,.8,.2,1)`.
- Components receive data as **props typed with the attached `types.ts`**;
  do not fetch data or call APIs inside them — I wire them to our existing
  hooks (`useSummary`, `useExceptions`, `useException`, `useAllowedActions`,
  `useMonthSummary`, `useItemSources`, `useDisputes`, `useDispute`,
  `useObligations`, `usePolicies`, `usePolicy`, `useQuestions`, `useAudit`,
  `useLeases`, `useSchedule`, `useLeaseVersions`, ...).
- Keep these existing component names (new props allowed): AppShell,
  MetricTile, StatusBadge, WorkStateBadge, DocumentViewer, PdfPage,
  EvidenceCard, InvestigationTimeline, JournalEntryTable, ScheduleDiff,
  LeaseVersionPanel, AgentActivityFeed, HashChain, CountUp.
- For each round deliver: the TSX files, any new token CSS, a list of new
  npm packages, and a short note mapping each component to the screen and
  hook it uses. Use realistic sample data from section 3 for previews.

Start with **Round 1: the design system and the app shell**, then propose the
money screen. Show me 2–3 distinct visual directions for Round 1 first.
