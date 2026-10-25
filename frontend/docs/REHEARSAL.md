# Rehearsal — round 8

Updated in round 13: the January beat is now the LEASE-03 base-rent hold (exc_12), see
"The January beat" below. Rows 10–13 carry that walk's timings; the rest is round 8's.

The judge's path, walked at 1280×800 against the live API on a fresh `make demo-data`,
then again in light theme, with reduced motion, offline on fixtures, and as each role.
Everything below was measured by `scripts/rehearsal-walk.mjs` (headless Chrome over the
DevTools protocol: per-step time to usable, console errors, failed and 4xx/5xx requests,
layout shifts with the elements that moved, horizontal overflow, cold-load timing). The
raw logs sit beside the screenshots in `docs/screenshots/round-8/walk-*.json`.

## The timed path

Fresh desk (`scripts/reset-desk.sh`), signed out, dark theme. "Ready" is the time from the
click to the screen being usable (the thing you would talk about is on screen).

| # | Beat | Ready | Notes |
|---|------|------:|-------|
| 1 | /welcome | 131 ms | headline, documents, proof tags |
| 2 | Open the desk → /login | 107 ms | four personas, demo badge |
| 3 | Sign in as Priya → Today | 105 ms | July hero, tiles, queue |
| 4 | Open → money screen (exc_18) | 409 ms | both documents boxed, actions |
| 5 | Run investigation | 7.5 s | the replay itself: search → found → remeasured → entries, `Balanced` |
| 6 | Why? | 104 ms | drawer with the audit rows behind the answer |
| 7 | Evidence pack | — | PDF downloads; no screen change |
| 8 | Switch to Dana | 106 ms | persona menu |
| 9 | Dana's Today | 108 ms | her region's queue |
| 10 | January base-rent hold (exc_12) | 106 ms | Lease supports $16,726.50 · Billed $17,270.11 · Variance +$543.61; §3.3 and the invoice line boxed |
| 11 | Uphold hold → confirm | 104 ms | `Hold upheld · $16,726.50 posted to the ledger (journal entry #2); $543.61 stays held · POSTED` |
| 12 | Disputes | 109 ms | the drafted letter (see backend note 1) |
| 13 | The letter (DSP-000012) | 103 ms | Billed $17,270.11 · Lease supports $16,726.50 · Disputed $543.61 |
| 14 | Audit trail | 31 ms | chain verified · 3 refused blocks red |
| 15 | Month run | 108 ms | seven stages, batch panel |
| 16 | Leases runway | 7 ms | five bars, today line |
| 17 | Lease detail (LEASE-01) | 103 ms | Claude's reading, clause boxed |

Machine time on the whole path: **9.5 s**, of which 7.5 s is the investigation's own
replay. Walked by hand with the narration from the demo script it comes in under three
minutes; the machine never makes you wait except where the replay is the point.

### The January beat

Round 8 walked the $4,820 premises hold (exc_6, Suite 118 billed against a lease for
Suite 115). It is a clean refusal, but its header reads `Lease supports $0.00 · Billed
$4,820.00 · Variance +$4,820.00`: no part of the charge is supported, so the three figures
say nothing a judge can subtract. The same goes for the January duplicate (exc_7, the
month's rent billed twice: $0.00 supported, $19,626.65 billed; it now says "Billed twice
this month · one installment is due" under the zero).

The beat is now the LEASE-03 base-rent hold (exc_12): the landlord billed $17,270.11 for
January, the rent schedule (§3.3, the escalation clause) provides $16,726.50, the checker
holds the $543.61. Both documents are boxed. Upholding posts the supported $16,726.50 to
the ledger and keeps the $543.61 held, and the dispute letter carries the same three
figures, so the money adds up on every screen Dana touches. Every number is the API's;
the walk picks the row by its billed amount (`JAN_HOLD`, default `17,270.11`, in
`scripts/rehearsal-walk.mjs`). Screenshots of the four beats:
`docs/screenshots/round-13/`.

Cold loads (cache disabled, full navigation): Today usable in **122 ms**, the money screen
in **119 ms** (TTFB 39 ms, load 79 ms). Target was under 2 s.

Console: **0 errors, 0 warnings** on the path. Network: **no 4xx or failures** once signed
in; the only 4xx anywhere is `GET /api/auth/me → 401` while nobody is signed in (the
session probe on /welcome and /login), which is the API saying "no session", not a fault.

## What broke or read badly, and what was done

1. **Fixtures contradicted the live demo** — the offline July invoice was cited at
   $19,626.65 while the exception said $17,400.00, and the lease clause quoted a different
   schedule line than the live one. New `scripts/sync_fixture_docs.mjs` (documented in its
   header) asks the running API for the two demo cases and copies what they cite: boxes,
   amounts, labels, the PDF bytes and the page renders. Stale documents are removed. The
   amendment email keeps its rendered fixture page because live it has no page to copy.
   Fixtures mode now shows the same $17,400.00 line boxed as the live desk.

2. **A stranger on /welcome in live mode was bounced to /login.** The API client redirects
   on any 401; the welcome page's live-figure queries fired without a session. Fixed twice
   over: the public routes are exempt from the redirect (`lib/api.ts`, behaviour-only), and
   the welcome page only asks for summary / audit / exceptions once `/api/auth/me` says
   someone is signed in (`useSignedIn`, `useSummaryWhen`, `useAuditWhen`,
   `useExceptionsWhen` in `lib/hooks.ts`, additive). Signed out, it shows the labelled
   fixture copy of the case and the measured figures, never a redirect.

3. **Leaving the audit trail threw** `NotFoundError: Failed to execute 'removeChild'` —
   every time, on every route out of /audit. The 3D chain strip's two drei `<Html>` labels
   portal into the canvas's parent, which React removes on navigation while drei is still
   removing the label. They now portal into a div the strip owns, so the page takes them
   down with it. Zero exceptions on the path since.

4. **`THREE.Clock` deprecation warning** in the console whenever a 3D view mounted. three
   0.186 deprecates the class react-three-fiber still constructs; pinned `three` and
   `@types/three` to 0.182.0 (fiber's peer range is `>=0.156`). Clean console.

5. **The money screen asked the API for pages of the amendment email** (`400 …/pages`): the
   email is evidence without a page, and the viewer still requested page sizes while the
   email overlay was showing. The viewer no longer asks for pages when something else holds
   the stage.

6. **Layout jumps on Today**: the hero and queue placeholders were a few skeleton lines
   where a 176 px card and a 300 px table would land. `LoadingBlock` takes a `className`
   and every Today placeholder now reserves the loaded height. Today's shift went from
   0.20 to 0.09 (what remains is the queue's column widths settling when rows arrive).

7. **Truncated labels**: the runway's lease column cut "Serramonte Hand Therapy, Suite 115"
   (column 250 → 300 px); the centre pane's title ("Before and after") vanished behind the
   three pane tabs (tabs have their own row now); the dispute letter's "Attn … · email"
   line (email and address moved beside it); the audit table's time and actor columns
   ("Oct 25, 04:29…", "agent:checker …" — the column is wider and the redundant "· agent"
   suffix is gone when the id already says so; reasons carry a title); the checker's
   explanation on the money screen (two lines → three); email addresses in evidence cards
   now wrap after the "@" instead of being cut.

8. **Projector type**: the smallest text was 11 px (`text-2xs`) and 12 px (`text-xs`); both
   are 13 px now (`tailwind.config.ts`). Checked every screen after: no overflow, no new
   truncation except the ones fixed above.

9. **Contrast**: every text token on every surface passes AA in both themes except
   `ink-faint`, which sat at 3.1–3.6:1. Raised to 4.6–5.4:1 in both themes (dark
   99/106/117 → 127/134/145; light 128/136/148 → 100/108/120). The computation is in the
   round-8 notes; the full table:

   | token | dark (bg/surface/raised/sunken) | light |
   |---|---|---|
   | ink | 17.1 / 16.0 / 14.7 / 16.6 | 17.5 / 18.9 / 18.9 / 16.6 |
   | ink-soft | 9.4 / 8.8 / 8.1 / 9.1 | 9.0 / 9.7 / 9.7 / 8.5 |
   | ink-muted | 5.7 / 5.4 / 4.9 / 5.5 | 5.5 / 6.0 / 6.0 / 5.3 |
   | ink-faint (now) | 5.4 / 5.0 / 4.6 / 5.2 | 4.9 / 5.3 / 5.3 / 4.6 |
   | accent · ok · bad · warn · esc | all ≥ 6.1 | all ≥ 4.8 |
   | ok/bad/warn/esc on their soft tints | 5.8 – 8.8 | 5.3 – 7.0 |
   | accent-ink on accent | 13.4 | 5.5 |

10. **No favicon** (`404 /favicon.ico` on every first load): `app/icon.svg` added.

11. **Queue header** "Billed · supports" wrapped to two lines after the rows arrived
    (17 px shift): `whitespace-nowrap` on the header cells.

## The other passes

- **Light theme**: full path, no console errors, no overflow, nothing unreadable
  (`*-light.png`).
- **Reduced motion**: full path with `prefers-reduced-motion: reduce`; every animated piece
  renders its final frame (reveals, count-ups, the chain, the investigation replay's stages
  all land at once). `*-reduced-dark.png`.
- **Fixtures, network off** (`NEXT_PUBLIC_USE_FIXTURES=1`, API unreachable): welcome, login,
  Today, money screen (both documents boxed at the synced positions, investigation on
  record, Replay), persona switch, audit, leases all work. Screens that are honest about
  needing the live API show a designed message, not a blank: Month run ("needs the live
  API"), Why? (disabled with its reason), lease detail's "as read" panel ("not been read
  yet"), Disputes (empty state). `*-fixtures-dark.png`.
- **Roles**: controller (the path), regional manager (Dana's half of it), AP clerk
  (batch-readiness hero, Month run with the batch panel, Audit, Leases) and auditor
  (chain-verified hero, read-only queue, refused attempts, Audit, lease detail).
  `*-ap-dark.png`, `*-auditor-dark.png`. Every screen has a designed loading, empty and
  error state; nothing renders blank or shows a raw key.
- **Projector**: 13 px minimum, AA contrast (above), money tabular everywhere (`.num`),
  no horizontal scroll on any step at 1280 (measured), and on Today and the money screen
  the headline, documents/tiles and the decision buttons all sit above 800 px.
- **Performance**: cold loads above; 3D views (`ChainStrip3D`, `DocumentStack3D`) are
  `next/dynamic` with `ssr: false` and load only when WebGL is available; the walk logs
  no console errors and no failed or 4xx requests on the path.

## Still visible, by design or out of scope

- Entering the money screen folds the rail to icons; the content slides left (a
  200 ms width transition, since round 2). The walk counts it as a layout shift
  (0.23 in, 0.11 out); it reads as a deliberate move, not a jump. Say if you want the rail
  fixed-width on the money screen instead.
- The investigation replay is 7.5 s by design (search 1.8 s, found 2.0 s, remeasure 2.2 s,
  then the entries). Reduced motion lands it at once.
- The `401 /api/auth/me` before sign-in, as above.

## Needs the backend

1. **Nothing drafts the dispute after an uphold.** The `disputes` job sweep exists
   (`app/work/disputes.draft_disputes`, registered as a job handler) but nothing enqueues
   it: not the approve action, not the worker's heartbeat, not `make run-month`. On a fresh
   desk, Dana upholds the $543.61 hold and Disputes stays empty. For the rehearsal
   `scripts/disputes-sweep.sh` enqueues the job and drains it (the walk calls it between
   steps 11 and 12). Fix on the backend: enqueue `disputes` when a hold is upheld (or sweep
   on the worker heartbeat).
2. **`make demo-data` can race the docker worker.** With `leasedesk-worker-1` running, the
   `confirm_leases` step ran before the abstraction jobs had landed, confirmed nothing, and
   the month runs produced zero exceptions. `scripts/reset-desk.sh` waits and confirms
   again, then re-runs both months. Fix: have `demo-data` drain the abstraction jobs before
   confirming (or stop the worker for the seed).
3. **The welcome page cannot show the amendment case live to a stranger**: every data route
   needs a session. A public read of the one demo case (or a public `GET /api/summary`)
   would let the first screen be live before sign-in.
4. **`GET /api/auth/me` answers 401 to a stranger** — fine, but if the judges watch the
   network tab, a 204 "no session" would read cleaner.

## Running it again

```bash
scripts/reset-desk.sh                     # fresh desk, both months, three refused attempts
docker compose stop web                   # the API's CORS list is only :3000
npm run build && npx next start -p 3000
DISPUTES_HOOK="zsh scripts/sweep.sh disputes" API_URL=http://localhost:8000 \
  node scripts/rehearsal-walk.mjs http://localhost:3000 docs/screenshots/round-8 dark 0 "" all
node scripts/rehearsal-walk.mjs http://localhost:3000 out light 0 "" all          # light
node scripts/rehearsal-walk.mjs http://localhost:3000 out dark 1 "-reduced" all   # reduced motion
PERSONA=Marcus node scripts/rehearsal-walk.mjs http://localhost:3000 out dark 0 "-ap" welcome,login,today,month,audit,leases
docker compose start web
```
