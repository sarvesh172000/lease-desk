# Lease Desk — web app

**Building the UI?** Start with [`UI_PLAN.md`](UI_PLAN.md) — what to
install, what to build and in what order — and
[`DESIGN_BRIEF.md`](DESIGN_BRIEF.md) for how it should feel.

Next.js (App Router) + TypeScript + Tailwind, TanStack Query and Table,
react-pdf. The UI only formats and asserts: every figure comes from the API
(or the frozen fixtures). Nothing in here does lease accounting.

## Run it

Node 22.

```bash
cd frontend
npm ci
```

**Against the fixtures** (no backend needed):

```bash
NEXT_PUBLIC_USE_FIXTURES=1 npm run dev        # http://localhost:3000
```

Fixtures mode is also what you get automatically when the API cannot be
reached at all: the first failed connection switches the session to fixtures
and the header shows a **Fixtures** badge. HTTP errors from a live API (401,
403, 500) are never masked by fixtures. In fixtures mode you are signed in as
the controller (Priya Raghunathan); the demo role switcher lists the four
datagen org-chart actors, and Approve / Hold change status for the session and
append to the audit trail.

**The live demo** (the default: FastAPI on :8000, Next on :3000, per DESIGN.md §18).
From the repo root, against Postgres 16 (here the one on :5432; drop the port
variable for the Compose database on :5433):

```bash
LEASEDESK_DB_PORT=5432 LEASEDESK_DB_NAME=leasedesk_demo make demo
# open http://localhost:3000 and sign in as dana.whitfield@northbaypt.example / demo
```

`make demo` = `make demo-data` (create the database if missing, `migrate`,
`seed`, `dev-passwords`, `run-month M=2026-01`, then confirm the leases and
run the month again; all idempotent) and then the API
(`cd backend && python3 -m uvicorn app.main:app --port 8000`) and
`npm run dev` together until Ctrl-C. The same by hand, in three terminals:

```bash
export LEASEDESK_DB_PORT=5432 LEASEDESK_DB_NAME=leasedesk_demo
make demo-data
make api                                                    # :8000
cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev   # :3000
```

**Lease confirmation.** The checker only uses lease terms a regional manager
has confirmed (PHASE_1.md group 9). The first `run-month` drafts version 1 of
each of the five leases (every term with its page, box, quote and
confidence, plus one LEASE_ABSTRACTION work item each) and checks nothing: the
twelve charges wait. By default `make demo-data` then confirms the five
versions as Dana Whitfield (`PER-RM-BAY`) with `python -m app.work.confirm_leases`
(demo mode only; it is the same approve the UI sends, so each confirmation is
a hash-chained event in her name) and runs the month again, so the demo opens
on the twelve checked charges and five holds. To show the confirmation
itself, start from a fresh database with

```bash
LEASEDESK_DB_PORT=5432 LEASEDESK_DB_NAME=leasedesk_demo DEMO_CONFIRM=0 make demo
```

then open a lease (Leases → a row), check a field against its boxed clause
(the **p.N** link opens the cited page with the box), press **Confirm lease
terms** as Dana, and run `make run-month M=2026-01` in another terminal: the
charges of the confirmed leases are checked and appear on the dashboard.
Which path read the terms is shown on the card: *read by the abstraction
agent* (ANTHROPIC_API_KEY set, or the LLM cache warm) or *from the generated
lease terms* (located in the real PDF by the citation check, never presented
as a model output).

To start over, drop the demo database (`DROP DATABASE leasedesk_demo`) and run
`make demo-data` again. Seeded people, all with password `demo` (the header's
**Demo** switcher changes person without a password):

| Person | Email | Role |
|---|---|---|
| Dana Whitfield | dana.whitfield@northbaypt.example | regional manager, Bay Area: approves and holds |
| Priya Raghunathan | priya.raghunathan@northbaypt.example | controller: approves and holds |
| Marcus Oyelaran | marcus.oyelaran@northbaypt.example | AP clerk: releases batches, no charge approvals |
| External Auditor | audit@brennan-cpa.example | auditor: reads everything, may press nothing |

What a judge sees after a fresh January: five held exceptions ($25,736.36 of
over-bills held) and all twelve checked charges on the dashboard; each opens on
the money screen with the billed line boxed on the real invoice PDF and the
cited clause boxed on the real lease PDF. Approve on a correct charge posts it
through the gateway (status **Posted**, journal entry number shown); the
auditor gets no buttons, and a forced request is refused and shows up as a
denied row in the audit trail, with the chain still verified.

**Live end-to-end check** (Playwright, mutates the database: use a fresh one):

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run build && npx next start -p 3000 &
BASE_URL=http://localhost:3000 npm run live-e2e     # screenshots: docs/screenshots/live-*.png
```

The browser calls the API directly with `credentials: "include"` (cookie
sessions), so the API must allow CORS from `http://localhost:3000` with
credentials. `NEXT_PUBLIC_*` variables are inlined at build time: set them
before `npm run build` for `npm run start`.

**Checks:**

```bash
npm run build && npm run lint && npm test
```

**Screenshots** (`docs/screenshots/`, 1280 px wide):

```bash
npm run build && npx next start -p 3011 &
BASE_URL=http://localhost:3011 npm run screenshots
```

## Screens

| Route | What |
|---|---|
| `/` | Dashboard: active leases, open exceptions, dollars held, portfolio liability; exceptions queue; every charge checked this month; latest agent activity |
| `/leases` | TanStack Table, status counts as filter chips, clinic filter, search, sortable columns |
| `/leases/[id]` | Lease facts, its exceptions, schedule (active / v1 / v2) |
| `/exceptions/[id]` | The money screen: invoice with the billed line boxed next to the cited source (evidence or lease clause) boxed, calculation strip, evidence card, investigation timeline (SSE), journal entries with a balance assertion, before/after remeasurement, Approve / Hold from allowed-actions |
| `/audit` | Audit trail with the "chain verified" badge, denied-attempt filter, `?lease_id=` |
| `/login` | Email + password; demo quick sign-in when demo actors exist |

## Where the fixture data comes from

`lib/fixtures.ts` holds the DESIGN.md §16 JSON **verbatim** (`SECTION_16_*`).
The rest is generated from the real code, never computed in TypeScript:

| File | Source | Regenerate |
|---|---|---|
| `lib/fixtureSchedules.json` | `leasedesk.remeasure` on `data/leases/store-14.json` (the §16 lease: $559,665.35 → $1,002,921.05) | `python3 frontend/scripts/build_fixture_engine.py <datagen-out>` |
| `lib/fixturePortfolio.json` | LEASE-02..05 from `datagen`, liability from `leasedesk.schedule` at 2026-06-30 | same |
| `lib/fixtureDocs.json`, `public/fixtures/docs/*.pdf` | datagen lease and invoice PDFs; boxes located with PyMuPDF; the amendment email rendered so the §16 box lands on the quote | `python3 frontend/scripts/build_fixture_docs.py <jan-out> <jul-out>` |

(`<datagen-out>` from `python -m datagen.build --out DIR [--month 2026-07]`.)

## The live API beyond §16

All of these are served by `backend/app/api/` today (added fields only; no §16
key renamed or removed). The UI still degrades without each one, so fixtures
mode and an older API keep working.

| Endpoint / field | Shape | Without it |
|---|---|---|
| `GET /api/summary` | `{as_of, active_leases, open_exceptions, pending_review, held_total, held_count, portfolio_liability}`; `held_total` is the open over-bills only (positive variances of unresolved holds) | — (fixtures: the same sums over the fixture rows) |
| `GET /api/items?kind=CHARGE_CHECK` | the queue; the dashboard's "All charges this month" keys each row as `exc_<id>` | empty state |
| `GET /api/exceptions/{id}` → `clinic_id`, `charge_type`, `item_id`, `state`, `proposal`, `reason`, `rule`, `confidence` | the work item behind the exception and the checker's finding | title says "Variance" |
| `GET /api/exceptions/{id}` → `invoice_line` | `{doc_id, page, box, description, amount}`, boxed on the real invoice PDF; **null** when it cannot be located | left pane empty state |
| `GET /api/exceptions/{id}` → `lease_citation` | `{doc_id, page, box, label, quote, match_score}`, the checker's cited clause boxed on the real lease PDF; **null** when it cannot be located | no "Lease clause" tab |
| `GET /api/exceptions/{id}` for any charge check | a correct charge (`proposal: approve`, variance 0) opens on the money screen too; `/api/exceptions` lists only the holds | — |
| `investigation` | always an object on the live API; all-null is read as "not investigated" (`lib/api.ts`) | — |
| `GET /api/leases/{id}/schedule?version=` | as before, plus `active`, `versions`, `confirmed` | empty state |
| `GET /api/audit?lease_id=` | events with `actor_name`, `hash`, `prev_hash`; `chain_verified`, `broken_at` (= `broken_seq`) | — |
| `GET /api/documents/{doc_id}/pages`, `/file`, `/pages/{n}.png` | `doc_id` is a sha256 or a `source_document.id`; pages carry `page` (= `number`), `width`, `height` in PDF points; `/file` is the PDF, fetched by pdf.js with credentials | quoted text shown instead of the page |
| `GET /api/items/{id}/allowed-actions` | `{"actions": [...]}` from `can()`; `lib/api.ts` maps `exc_42` → `42` | — |
| `POST /api/exceptions/{id}/approve` and `/hold` | `{status, exception_id, state, posting: {status: posted|pending, journal_entry_id, error} | null}` | — |
| `POST /api/exceptions/{id}/investigate` | SSE `data: {...}` frames: a recorded investigation is replayed (searching, found, remeasured, complete); otherwise the checker's own evidence (searching, found or `not_found`, complete with `entries: 0, balanced: null`). No remeasurement is ever invented | — |
| 401 on any data call | the browser goes to `/login?next=…` | — |
| auth | `/api/auth/me` (401 signed out), `login`, `logout`, `demo-actors` (404 when demo mode is off), `demo-switch` | — |
| CORS | origin `http://localhost:3000` with credentials (`LEASEDESK_CORS_ORIGINS`) | browser blocks calls |

All data fetching lives in `lib/api.ts` (fetch wrappers + fixtures) and
`lib/hooks.ts` (one hook per query or mutation); pages and components only call
hooks, so a redesign can replace any screen without touching it.
