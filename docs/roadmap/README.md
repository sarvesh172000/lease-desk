# Roadmap — after the hackathon

**Nothing in this folder is being built this weekend.** It is Jenil's full
three-phase plan, 500 effort-hours, kept intact as the product roadmap.

[`../PLAN.md`](../PLAN.md) is what we are actually building.

| Phase | Hours | What it adds |
|---|---|---|
| [Phase 1](PHASE_1.md) | 110 | Event-sourced platform, DB roles, gateway, ledger, first thin slice |
| [Phase 2](PHASE_2.md) | 250 | 30 clinics, EDGAR leases, scans, email, CAM, CPI, ASC 842 close, resolver, policy engine |
| [Phase 3](PHASE_3.md) | 140 | Polish, chaos testing, Azure, Microsoft and Fetch.ai tracks, submission |

## Why it was compressed

500 effort-hours against 72 person-hours available (two people × 36 hours, no
sleep) — about 7×. Phase 1 alone is 1.5× the whole event, and the submission
package sits in Phase 3 behind 486 hours of prerequisites, so following the
phases in order never reaches "record the video and submit."

`PLAN.md` keeps the architecture, the naming and the task-group numbering, and
compresses the scope. What was cut and why is listed there.

## First things to build after the hackathon

In order, because each unlocks a demo beat we had to drop:

1. **CAM engine and shared pools** (Phase 2 group 6) — the parking-lot
   double-bill moment. The data generator already sets it up: Serramonte
   Medical Plaza holds two Northbay suites.
2. **Policy engine with backtests** (Phase 2 group 10) — the "improves" beat.
3. **Bitemporal rulebook** (Phase 2 group 5) — "what did we believe in March
   about June's rent."
4. **Held-out test company** (Phase 2 group 2) — the honest answer to
   overfitting.
