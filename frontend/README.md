# Lease Desk — web app

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

**Against the API** (FastAPI on :8000, per DESIGN.md §18):

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
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
| `/` | Dashboard: active leases, open exceptions, dollars held, portfolio liability; exceptions queue; latest agent activity |
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

## What the UI expects beyond §16

The backend can add these; the UI degrades without each one.

| Endpoint / field | Shape the UI expects | Without it |
|---|---|---|
| `GET /api/exceptions/{id}` → `clinic_id`, `charge_type` | as on the list shape | title says "Variance" |
| `GET /api/exceptions/{id}` → `invoice_line` | `{doc_id, page, box, description, amount}` — the billed line | left pane empty state |
| `GET /api/exceptions/{id}` → `lease_citation` | `{doc_id, page, box, label, quote}` — the clause the expected amount comes from | no "Lease clause" tab |
| `investigation.liability_delta`, `rou_delta` | numbers from the engine | "Change" column filled from the SSE `remeasured` event, else hidden |
| `investigation.liability_before` … `rou_after` may be `null` | for exceptions with no remeasurement | — |
| `investigation` may be `null` | exception not investigated yet | — |
| `GET /api/leases/{id}/schedule?version=` | `{lease_id, version, effective_from, active, opening_liability, opening_rou, rows: [{index, period, payment, interest, liability_open, liability_close, rou_open, rou_amortization, rou_close, straight_line_cost}]}`; no `version` = active; 404 for a missing version | empty state |
| `GET /api/audit?lease_id=` | `{events: [{seq, at, actor_id, actor_name?, action, subject_type, subject_id, lease_id?, allowed, reason?, human_approved?, hash?, prev_hash?}], chain_verified, broken_at?}` | — |
| `GET /api/documents/{doc_id}/pages` | `{doc_id, kind?, title?, pages: [{page, width, height}]}` (PDF points); must accept evidence `doc_id`s such as `eml_20260618`, not only sha256 | box scaled against the PDF's own page size |
| `GET /api/documents/{doc_id}/file` | the PDF bytes (`application/pdf`) | quoted text shown instead of the page |
| `GET /api/items/{id}/allowed-actions` | `{"actions": ["approve", "hold"]}`; called with the `exception_id` | — (fixtures: approve+hold for controller / regional manager, none for others or when balanced) |
| `POST /api/exceptions/{id}/hold` | `{exception_id, status}` like approve | Hold errors |
| `POST /api/exceptions/{id}/investigate` | SSE frames `data: {...}\n\n` on a **POST** response (read with fetch streaming) | — |
| `GET /api/auth/me` | actor `{id, name, role, region_id, entity_id}`; **401** when signed out | — |
| `POST /api/auth/login` | `{email, password}` → actor; 401 on bad credentials | — |
| `POST /api/auth/logout` | 204 | session kept server-side |
| `GET /api/auth/demo-actors` | actor list; 404 or 403 when demo mode is off (hides the switcher) | — |
| `POST /api/auth/demo-switch` | `{actor_id}` → actor | — |
| CORS | allow origin `http://localhost:3000` with credentials | browser blocks calls |

Dashboard "dollars held" (sum of `|delta|` over open exceptions) and
"portfolio liability" (sum of lease `liability`) are display aggregates summed
in cents; a backend summary endpoint can replace them.
