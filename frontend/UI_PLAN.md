# Frontend build plan

The plan for turning the working app into a professional product with a
landing page. [`DESIGN_BRIEF.md`](DESIGN_BRIEF.md) already describes how the
app screens should *feel*; this is what to install, what to build, and in what
order.

---

## 0. The one aesthetic decision, made up front

"Futuristic" splits two ways and only one of them survives a finance judge.

**Not this:** neon, scanlines, glowing wireframes, sci-fi HUD. On a product
whose whole claim is *"a controller would trust this with the books"*, it reads
as a toy. The moment a judge thinks "demo", the $443,255.70 stops being money
and becomes a prop.

**This:** the way the best software of 2026 looks — Linear, Stripe, Mercury,
Vercel, Raycast. Deep near-black surfaces, one electric accent, glass and
gradient used sparingly, type doing most of the work, and **motion that
explains rather than decorates**. That *is* futuristic, and it is also what a
CFO's office buys.

So: go as bold as you like on depth, motion, typography and density. Keep three
things sacred — **numbers stay precise and tabular**, **contrast stays legible
on a washed-out projector at 1280 px**, and **nothing moves that isn't saying
something**.

Dark is the default. Light stays available because finance people print.

---

## 1. Stack to add

```bash
cd frontend
npm i framer-motion lucide-react sonner recharts cmdk
npm i @radix-ui/react-dialog @radix-ui/react-tooltip @radix-ui/react-dropdown-menu @radix-ui/react-tabs
npm i -D @tailwindcss/typography tailwindcss-animate
```

| Package | Why this one |
|---|---|
| `framer-motion` | Layout animations and shared-element transitions. The investigation timeline and the before/after schedule both need `layoutId`. |
| `lucide-react` | One icon set, 1.5 px stroke, matches the type weight. Never mix icon sets. |
| `@radix-ui/*` | Headless and accessible. Keyboard and focus handling for free, which you will not get right by hand at 2 a.m. |
| `sonner` | Toasts for approve/hold/reject. Stacks, dismisses, does not block. |
| `recharts` | The schedule chart and the liability sparkline. |
| `cmdk` | Command palette — `⌘K`. Cheap, and it makes a demo feel like a tool. |
| `tailwindcss-animate` | Keyframe utilities so simple entrances need no JS. |

**Fonts** via `next/font` — zero layout shift, self-hosted:

- **Display / UI:** `Geist` or `Inter` with `cv11`, `ss01` on (already enabled).
- **Numerals:** the same family with `tabular-nums` — figures must not jitter
  when they animate. The existing `.num` class does this; keep it.
- **Mono:** `Geist Mono` or `JetBrains Mono` for ids, hashes, clause refs.

---

## 2. Design tokens

Replace the single light palette in `tailwind.config.ts` with a dual-theme
token set driven by CSS variables, so a theme switch is one attribute.

```css
/* app/globals.css */
:root[data-theme="dark"] {
  --bg:        10 11 13;      /* near-black, never pure #000 */
  --surface:   18 20 24;
  --raised:    26 29 34;
  --line:      38 42 49;
  --ink:       237 239 243;
  --ink-soft:  160 166 176;
  --ink-faint: 110 116 126;
  --accent:    94 234 212;    /* electric teal — carries the existing brand */
  --accent-ink: 8 10 12;
  --ok:  52 211 153;
  --bad: 248 113 113;
  --warn: 251 191 36;
  --esc: 167 139 250;
}
```

Also define, and then actually use:

| Token group | Values |
|---|---|
| **Radius** | `6 / 10 / 14 / 20` — one scale, no ad-hoc values |
| **Elevation** | 3 levels only: flat, raised card, floating overlay |
| **Motion** | `fast 120ms`, `base 200ms`, `slow 420ms`; easing `cubic-bezier(.2,.8,.2,1)` |
| **Spacing** | Stick to Tailwind's scale. Never `p-[13px]`. |

**Rule:** every colour in a component comes from a token. The moment a hex
appears in a `.tsx` file the theme switch is broken.

---

## 3. The landing page — `/welcome`

New, and the main piece of work. The app lives at `/`; this is what someone
sees before they sign in, and what a judge sees if they open the repo link.

Route it so `/welcome` is public and `/` still requires auth. Add a **"Open the
app"** button that goes to `/login`.

### Section-by-section

**1 · Hero — lead with the money**

> **$443,255.70 of lease liability was missing from the balance sheet.**
> Nobody knew. The amendment was in somebody's inbox.

- The figure counts up on load (`framer-motion`, ~900 ms, tabular so it does
  not reflow). This is the only decorative animation on the page and it earns
  its place because the number *is* the pitch.
- Beneath it, one line: *Lease Desk fills the lease accountant's seat — it
  reads every lease, checks every bill, and holds only the money that is wrong.*
- Two buttons: **Open the app** (primary) and **See how it works** (scrolls).
- Background: a very slow radial gradient drift. No particles.

**2 · The problem — three cards**

Dozens of leases · escalations and amendments buried in email · nobody tells
accounting. Cite KPMG: identifying lease changes stayed a persistent problem
*after* ASC 842 implementation, with companies reacting after the fact. One
sentence each, no filler.

**3 · The moment — a scroll-driven sequence**

The centrepiece. Four steps that advance as the user scrolls, each one a real
artefact from the system:

1. **The break** — July rent came in $2,226.65 short, three months running.
2. **The search** — 10 documents scanned; the executed amendment surfaces, the
   forged sender and the injection attempt are set aside.
3. **The proof** — the quoted sentence, highlighted on the actual page image.
4. **The entries** — liability $559,665.35 → $1,002,921.05, debits = credits,
   awaiting the controller.

Use `useScroll` + `useTransform`, pinned section, `prefers-reduced-motion`
falls back to all four shown at once.

**4 · The principle — the line that wins the argument**

> **The model reads. The code calculates.**

Two columns: what Claude does (reads messy documents, cites the sentence) and
what deterministic code does (every schedule, every balance, every entry). One
line under it: *no balance, schedule row or journal entry is ever produced by a
language model.*

**5 · Proof — a strip of real numbers**

| | |
|---|---|
| 476 | tests, all offline |
| 5/5 | planted errors caught, 0 false holds |
| 3 | real SEC lease exhibits, hand-labelled |
| 184 | real BLS CPI observations |
| 18 | clinics in a held-out company never seen in development |

**6 · Technology — honest, not a logo soup**

Group by what it does, and say what each is *for*:

- **Reads** — Claude (`claude-opus-5-5`), structured outputs, per-claim citations
- **Computes** — Python, ASC 842 engines, 476 tests
- **Remembers** — Postgres, hash-chained audit, four database roles
- **Shows** — Next.js 15, TypeScript, Tailwind, TanStack Query

**7 · Footer** — repo link, the team, the one-line pitch again.

---

## 4. App screens — what to upgrade

Jenil's brief has the layout for each. This is the polish pass per screen.

### `/` Dashboard
- Metric tiles: animated count-up on mount, a sparkline under the liability
  figure, and a coloured left rule that reads at a glance.
- Exception queue: row hover lifts, status pills with a soft glow, the
  variance column right-aligned and tabular.
- Agent activity feed: new entries slide in; a live pulse dot on the newest.

### `/exceptions/[id]` — the hero screen
This is where the demo is won. Priorities in order:
1. **The split view.** Invoice left, lease right, both boxed, synced scroll.
2. **The timeline.** Steps reveal one at a time with a connecting line that
   draws. This is the "it is working" moment.
3. **The entries table.** Debits and credits with a visible balance assertion —
   a green check and `447,880.44 = 447,880.44`.
4. **The schedule diff.** Before/after side by side, changed rows highlighted,
   `layoutId` so rows animate between states.
5. **The action bar.** Sticky at the bottom. Approve is the only filled button.
   When disabled, the reason shows in a tooltip — it already does, keep that.

### `/leases` and `/leases/[id]`
Dense table, sticky header, status pills, a filter row. The detail page gets
the full schedule as a chart plus a table under it.

### `/audit`
Make the hash chain *visible*: a vertical line of linked blocks, each showing a
truncated hash, with a "chain verified" badge at the top. This is a strong beat
and it is currently plain text.

### `/login`
Full-bleed split: brand and one sentence left, form right. Demo accounts as
one-click chips.

---

## 5. Component inventory

Build these as primitives first, then compose:

```
components/ui/     Button, Card, Badge, Tooltip, Dialog, Tabs,
                   Skeleton, EmptyState, Toast, CommandPalette
components/data/   MetricTile, Sparkline, DataTable, StatusPill,
                   MoneyCell, DeltaCell, Timeline, HashChain
components/domain/ EvidenceCard, ScheduleDiff, JournalEntryTable,
                   DocumentViewer, AgentActivityFeed, ActionBar
```

`Button` needs: `variant` (primary / secondary / ghost / danger), `size`,
`loading`, `disabled` **with a reason**. Everything else follows from it.

---

## 6. Order of work

| # | Phase | Hours | Done when |
|---|---|---|---|
| 1 | ~~Tokens, fonts, dark theme, `Button`/`Card`/`Badge`~~ **DONE** | 4 | Every existing screen renders dark with no hex in any `.tsx` |
| 2 | Dashboard polish — tiles, queue **DONE** (sparkline not built) | 3 | Count-up and hover states feel deliberate |
| 3 | ~~**Exception screen**~~ **DONE** — split view, timeline, entries, diff | 8 | The 3-minute demo runs on it without apology |
| 4 | ~~**Landing page** `/welcome`~~ **DONE** | 8 | A stranger reads it once and can say what the product does |
| 5 | ~~Leases, audit, login~~ **DONE** | 5 | Hash chain is visibly a chain |
| 6 | Command palette, empty and loading states **DONE** (no toasts) | 3 | Nothing ever shows a raw spinner or a blank panel |
| 7 | Motion pass, reduced-motion **DONE**; projector check at 1280 pending | 3 | Legible from across a room |

**34 hours.** If it slips, cut in this order: command palette → sparklines →
scroll-driven landing sequence (fall back to four static steps) → dark/light
toggle (ship dark only).

**Never cut:** the exception screen, the landing hero, legibility at 1280.

---

## 7. Rules that keep it professional

- **No raw spinners.** Skeletons shaped like the content that is coming.
- **No empty panels.** Every empty state says what will appear and why it is
  empty — the app already does this well on the document panes.
- **Every number tabular.** Figures must not shift width as they animate.
- **Every destructive or financial action confirms.** Approve posts entries;
  it gets a confirmation with the amount restated.
- **Focus rings stay visible.** Judges may tab. Radix gives this free.
- **`prefers-reduced-motion` is honoured** on every animation, not just the
  big ones.
- **No layout shift.** `next/font`, fixed aspect boxes for the page images.
- **One accent colour.** The moment there are two, nothing is emphasised.

---

## 8. What not to build

- A chat interface. It invites judges to break it live, and prose answers
  undercut the determinism the product is selling.
- A settings page nobody opens.
- Charts for figures that are not compared over time. A single number is a
  number, not a chart.
- Custom scrollbars, cursor trails, parallax on anything containing money.

---

## 9. Check it against the real thing

The stack runs. Point the UI at it rather than at fixtures while you build:

```bash
make up && make migrate && make seed && make run-month M=2026-01
cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Sign in as `priya.raghunathan@northbaypt.example` / `demo`.

Build against fixtures when the backend is in flux
(`NEXT_PUBLIC_USE_FIXTURES=1`), but do the final pass on live data — the live
payload is where the empty states and the missing fields actually show up.


---

## Status, 24 Oct 2026

Phases 1-6 are built and on `main`. Phase 7's motion and reduced-motion work is
done; the 1280 projector check still wants a human eye on a real screen.

Building phase 3 surfaced that the money screen had no data to show, and four
breaks underneath it, all now fixed: the detail endpoint returned seven scalars
and neither document; the api/worker containers had no data volume, so every
page request 404'd; the page viewer crashed on pdf.js and is now the server's
own PNG renders; and the page-size lookup compared `page` against the API's
`number`, so no citation box could ever draw.

`POST /api/exceptions/{id}/investigate` is now built: it runs the modification
agent over the mailbox, streams the four stages, and records what it found on
the work item so the screen survives a reload. A recorded investigation is
replayed rather than asked again; when no model can run, the stream shows the
checker's own evidence (the cited clause, boxed on the lease) and then an
`error` stage saying why the mailbox was not searched. It never invents a
remeasurement.

**Two things stand between it and the moment on live data:**

1. **A model key, once.** The agent reads the mailbox, and the response cache
   is empty. Put `ANTHROPIC_API_KEY=...` in `.env` and run the investigation
   once; the answer is then cached under `.cache/llm`, which the API and the
   eval share, and every later run is offline. Without it the timeline shows
   exactly that, rather than failing silently.
2. **Generate the month the amendment is in.** The seeded month is January
   2026, whose exceptions are a duplicate and a CAM over-bill — real holds,
   but no amendment to find, so an honest investigation returns
   "unexplained". The amendment takes effect 1 July 2026:

   ```bash
   python -m datagen.build --out data/generated --month 2026-07
   make seed && make run-month M=2026-07
   ```

   `datagen/build.py` now bills from the lease *as amended* while the books
   still run the old schedule — that gap is the variance. A month before the
   amendment generates byte-identically, so January is untouched.

Note the two months do not coexist: `build.py` generates one billing month, so
this replaces January rather than adding to it.
