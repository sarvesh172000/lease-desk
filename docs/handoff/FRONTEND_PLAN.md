# Frontend redesign: Jenil's playbook (with Claude Design)

## Where the frontend is today

- **Stack:** Next.js 15 App Router, React 19, TypeScript, Tailwind 3 with
  dual-theme CSS-variable tokens (dark default, light available),
  TanStack Query, framer-motion, Radix (dialog, dropdown, tabs, tooltip),
  cmdk command palette, recharts, react-pdf, sonner toasts, lucide icons.
  **Not installed yet:** `@react-three/fiber`, `@react-three/drei`, `three`
  (needed for the 3D pieces; we add them when integrating).
- **Screens (7):** `/welcome` landing, `/login`, `/` dashboard, `/leases`,
  `/leases/[id]`, `/exceptions/[id]` (the money screen), `/audit`.
- **Components:** AppShell, MetricTile, StatusBadge, WorkStateBadge,
  DocumentViewer, PdfPage, EvidenceCard, CheckerFindingCard,
  InvestigationTimeline, JournalEntryTable, ScheduleDiff, LeaseVersionPanel,
  AgentActivityFeed, data/CountUp, data/HashChain, ui/{Badge, Button, Card,
  CommandPalette, ConfirmDialog, States, Tooltip}, welcome/{Section, TheMoment}.
- **Data layer (do not redesign):** `lib/api.ts`, `lib/hooks.ts`,
  `lib/types.ts`, `lib/fixtures.ts`. Fixtures mode (`NEXT_PUBLIC_USE_FIXTURES=1`)
  is the offline demo.
- **The gap:** the backend grew a lot (policies, disputes, obligations,
  questions, the month run, the resolver's sources, "why", evidence packs,
  chat pairing, demo reset, batch release) and **none of it has a screen
  yet**. The hooks for most of it already exist (`usePolicies`,
  `useDisputes`, `useObligations`, `useQuestions`, `useMonthSummary`,
  `useItemSources`, `useDemoReset`, ...).
- Screenshots of the current UI: `frontend/docs/screenshots/*.png`.
- Existing design docs: `frontend/DESIGN_BRIEF.md` (what and why),
  `frontend/UI_PLAN.md` (tokens, aesthetic rules).

## Your steps

1. **Merge the open PR** once CI is green (Claude fixes CI in the next push).
   Pull `main`.
2. **Open Claude Design** and start a new project. Attach:
   - `docs/handoff/CLAUDE_DESIGN_PROMPT.md` (paste it as the first message),
   - `frontend/DESIGN_BRIEF.md` and `frontend/UI_PLAN.md`,
   - `frontend/lib/types.ts` (the exact data shapes),
   - 4–6 screenshots from `frontend/docs/screenshots/` (dashboard,
     live-money-duplicate-rent, live-audit-denied, leases, lease-detail).
3. **Work in this order**, one screen per round, approving each before the
   next (the prompt asks Claude Design to do the same):
   1. Design system + AppShell (nav, role switcher, live indicator, ⌘K)
   2. The money screen `/exceptions/[id]`
   3. Today `/` (per role) + the Month run stepper
   4. Audit trail with the 3D hash chain
   5. Leases portfolio with the 3D map, lease detail
   6. New screens: Disputes, Obligations, Policies, Questions inbox,
      "Why?" drawer + evidence pack, Connect chat (pairing)
   7. Landing `/welcome` and login
4. **Export** each approved round as code (Next.js/TSX components) or a zip.
   Put it in `frontend/_design/<round-name>/` or just send it to Claude here.
5. **Hand it to Claude (this session)** with: "integrate round N from
   `frontend/_design/...`". Claude wires it to the real hooks, keeps fixtures
   mode working, adds any missing hooks, runs `npm run build`, `npm run lint`,
   `npm test`, checks it in a real browser on the live API at 1280 px, and
   pushes under Jenil133.
6. **Rehearse** on a projector-sized window (1280×800) with reduced motion
   both on and off, and once with the wifi off (fixtures mode).

## Acceptance for each round

- Real data only, from the hooks. No number is computed, rounded or invented
  in the UI; count-ups land on the exact API value.
- Works in fixtures mode and on the live API; loading, empty and error states
  designed.
- Readable at 1280 px from the back of a room; contrast AA in both themes.
- `prefers-reduced-motion` respected; 3D lazy-loaded, never blocks first paint
  or a click; the money screen opens instantly.
- Only the actions the server allows are shown (`useAllowedActions`).
