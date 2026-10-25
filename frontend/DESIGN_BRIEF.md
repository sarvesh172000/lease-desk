# Lease Desk — design brief

Paste this whole file into Claude Design. It describes what to design, the real
data on every screen, and the rules that let a new design drop into the app
without touching the data layer.

---

## 1. What this is, in one breath

Lease Desk fills the **lease accountant's seat** at a 30-store coffee
chain. Every month it reads every landlord bill, checks it against what the
lease actually says, drafts the payments and the accounting entries, and
**holds only the money that is wrong** — showing the exact line in the invoice
and the exact clause in the lease side by side. It never pays and never signs
off: a human approves, and every action is written to a tamper-evident,
hash-chained history.

Audience on demo day: hackathon judges (Hyphenate, Microsoft, Fetch.ai,
Anthropic), on a **projector at 1280 px wide**, for **2–3 minutes**. They must
leave knowing: *what seat it fills, what it caught, and why they would trust it.*

## 2. The feeling

Bold, alive, unmistakably premium — **and** a tool a controller would trust with
the books. Think a mission-control for money: motion that *explains*, not
motion that decorates.

Go big on:
- **Moving segments**: the investigation unfolding step by step, documents
  sliding in side by side, the boxed invoice line and lease clause drawing
  themselves, a ledger that "settles" when debits equal credits.
- **3D / depth** where it carries meaning: the portfolio as a spatial map of
  clinics and leases; a document "stack" the agent searches through; the hash
  chain as linked blocks (tamper one and the chain visibly breaks).
- **Dynamic numbers**: count-ups on load, live status changes when someone
  approves.

Hold the line on (non-negotiable — judges include finance people):
- **Every number is real.** It comes from the API; the UI never computes,
  rounds or invents money. Count-up animations must end on the exact value.
- **Money is legible**: tabular numerals, right-aligned, two decimals, red only
  for a real problem. Readable from the back of a room at 1280 px.
- **Status is never ambiguous**: four states only — `balanced`, `exception`,
  `pending_review`, `escalated`.
- **Motion respects `prefers-reduced-motion`** and never blocks a click. The
  whole demo must work with the wifi off (fixtures mode, see §6).

## 3. The demo moment (design around this)

> **The hidden amendment.** STORE-01's July rent stops matching the schedule
> by **−$2,226.65**. The agent searches the mailbox, finds an executed
> amendment (trust rank 1, confidence 94%) that cut the rent to $17,400 and
> extended the lease three years, remeasures the lease under ASC 842 —
> liability **$559,665.35 → $1,002,921.05 (+$443,255.70)** — and proposes four
> balanced journal entries for the controller to approve.

Second beat: **January**, 12 charges checked, **5 held** for **$25,736.36**,
including a rent invoice billed twice (both copies *correct*, which is why it
survived) and rent for a suite the clinic doesn't lease.

Third beat (trust): the agent **tries** to post to the ledger and the database
itself refuses; a regional manager tries to approve their own answer and is
refused; both refusals appear in the audit trail, and the chain still verifies.

## 4. Screens and the data each one shows

Field names below are the real API fields.

### 4.1 Today (dashboard) — `/`
- Metric tiles: active leases, open exceptions, dollars held (sum of held
  over-bills only), portfolio liability.
- Exception queue: status, title, lease/clinic, period, expected, actual,
  variance, confidence.
- Agent activity feed: agent name, action, subject, time.
- Role switcher (demo): controller, regional manager, AP clerk, auditor — the
  same screen changes with role.

### 4.2 Leases — `/leases`
`lease_id, clinic_id, location, lessor, status, monthly_rent, liability, end`.
Filters by status and clinic, counts at the top. A great place for the 3D
portfolio map.

### 4.3 Lease detail — `/leases/[id]`
ASC 842 schedule rows: `period, payment, interest, liability_open,
liability_close, rou_close, straight_line_cost`; versions (v1 original, v2
after amendment); before/after.

### 4.4 The money screen — `/exceptions/[id]` (the hero)
- Header: title, status, expected / actual / variance, explanation + confidence.
- **Two documents side by side**: the invoice page with the billed line boxed,
  the lease (or amendment email) with the cited clause boxed. Boxes are
  `[x0, y0, x1, y1]` in PDF points, scaled against the page size.
- Evidence card: quote, source, trust rank (1 = executed amendment … 6 =
  payment history), date, confidence.
- Investigation timeline (streamed, 4 stages): *searching → found → remeasured
  → complete*.
- Journal entries table with a visible **balanced** assertion (debits = credits).
- Remeasurement before/after: liability, ROU asset, schedule from the change.
- Actions: **Approve / Hold** (only the actions the server allows for this
  person), result posts to the ledger.

### 4.5 Audit trail — `/audit`
Events: `seq, at, actor, action, subject, allowed (true/false), reason`, plus
**chain verified** (or the sequence number where it broke). Denied attempts are
first-class rows, not errors. Ideal for the hash-chain-as-blocks visual.

### 4.6 Login — `/login`
Email + password; demo role switcher when demo mode is on.

## 5. Components that exist today (same props, new skin)

`AppShell, MetricTile, StatusBadge, DocumentViewer, PdfPage, EvidenceCard,
InvestigationTimeline, JournalEntryTable, ScheduleDiff, AgentActivityFeed`
in `frontend/components/`. Screenshots of the current, plain version are in
`frontend/docs/screenshots/`.

## 6. Handoff rules (so a redesign drops straight in)

- **Stack**: Next.js App Router + TypeScript + Tailwind. Motion: `framer-motion`.
  3D: `@react-three/fiber` + `@react-three/drei`. Keep heavy 3D lazy-loaded so
  the money screen opens instantly.
- **Do not touch** `frontend/lib/api.ts`, `lib/hooks.ts`, `lib/types.ts`,
  `lib/fixtures*`. Screens get data only through the hooks; the redesign
  changes components and pages, not data fetching.
- Keep component **names and props**; add new components freely.
- Must work in **fixtures mode** (`NEXT_PUBLIC_USE_FIXTURES=1`) — that is the
  offline demo.
- Must pass `npm run build`, `npm run lint`, `npm test`.
- Deliver as code in `frontend/` (or exported components + a short note on
  where each goes).
