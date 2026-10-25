# UI test plan

`scripts/ui-suite.mjs` runs every case below in headless Chrome (no
dependency: it drives the installed Chrome over the DevTools protocol, like
`rehearsal-walk.mjs`) and exits non-zero if any check fails. Each case's ID is
what the script prints.

```bash
# read-only: safe on the live site
node scripts/ui-suite.mjs https://lease-desk-ten.vercel.app out/ui
# everything, including approvals: a fresh local desk only (make demo-data)
MUTATE=1 API_URL=http://localhost:8000 node scripts/ui-suite.mjs http://localhost:3000 out/ui
```

Every step also records console errors, uncaught exceptions, failed or 4xx/5xx
requests (except the expected 401 from `/api/auth/me` when signed out) and
horizontal overflow, and saves a screenshot to the output folder.

## Read-only cases

| ID | Case | Passes when |
|---|---|---|
| R01 | Front door, signed out | `/` lands on `/welcome`; the hero, the sponsor strip and the proof footer render |
| R02 | Deep link, signed out | `/exceptions/exc_18` goes to `/login?next=…` |
| R03 | Sign-in form, wrong password | "Email or password is incorrect.", still on `/login` |
| R04 | Demo sign-in | The persona list shows the four people; Priya lands on Today |
| R05 | Shell | The rail has its screens, the persona button names Priya, the data source is the live API |
| R06 | Today, controller | Tiles, the hero card and the queue (6 open) render |
| R07 | Exceptions list | Six rows; one opens its exception |
| R08 | January hold | Both documents boxed, confidence 56%, no "0%", Investigation / Evidence / Sources tabs switch |
| R09 | Why? | The drawer answers in words |
| R10 | July hold | The amendment and the remeasurement pane; the balance seal; the lease-change approval card names its item and links the lease |
| R11 | Leases | Five runway rows; LEASE-01 has the newer-version ghost when v2 exists |
| R12 | Lease detail | Terms table with quotes, versions v1 and v2, the schedule chart |
| R13 | Month, Obligations, Disputes, Policies, Questions | Each renders its content or its empty state, no error state |
| R14 | Policy detail | Opens from the list with its rule in words |
| R15 | Audit | The chain banner says verified; rows; a row opens its detail; tamper simulation shows a break and restores |
| R16 | Command palette | ⌘K opens it, "LEASE-01" finds the lease, Enter goes there |
| R17 | Theme | The toggle switches light ↔ dark and the page keeps rendering |
| R18 | Roles | Dana sees her region's queue; Marcus sees the AP view; the auditor gets no action buttons on the July hold |
| R19 | Not found | `/no-such-page` shows "No such page" |
| R20 | Phone width (375 px) | Welcome, login, Today and an exception have no horizontal scroll |

## Mutating cases (`MUTATE=1`, fresh desk only)

| ID | Case | Passes when |
|---|---|---|
| M01 | Run investigation on the July hold | Four stages; +$443,255.70; four balanced entries; the approval card says "proposed" |
| M02 | Approve the lease change | On LEASE-01, Priya confirms v2; the July page says the gateway posted, entries labelled posted |
| M03 | Uphold a January hold as Dana | Confirm dialog, then the action result; the page shows the resolution |
| M04 | Pay as billed needs a reason | The form will not submit empty |
| M05 | Auditor cannot approve | A forced approve is refused (403) and the audit trail shows the denied row |
| M06 | Connect chat | Minting shows an 8-character code and a countdown |
