> **Superseded by [`PLAN.md`](PLAN.md)**, which follows Jenil's phase structure.
> Kept for the fixtures in Stage 0 and the cut list.

# Build Plan — Sarvesh + Jenil

36 hours, two people, frontend and backend in parallel. Stage gates, not a
wishlist.

## The one rule

**The demo path is always runnable.** Never spend more than two hours in a state
where you couldn't show something to a judge who walks up. Every stage below
ends with something demonstrable.

## Division of labour

| | Sarvesh | Jenil |
| --- | --- | --- |
| Owns | Backend, engine, agents, API | Frontend, all screens, the demo UX |
| Language | Python / FastAPI | TypeScript / Next.js |
| Never touches | `web/` | `leasedesk/` |
| Shared | `docs/`, the API contract, the demo script |

**Why this split:** the accounting engine already exists in Python and is
tested. Rewriting it in TypeScript throws away the test suite. The contract
between you is the JSON in §Stage 1 — agree on it in hour one and neither of you
is ever blocked.

### The contract rule

Jenil builds every screen against **hardcoded JSON fixtures** that match the
agreed shape. Sarvesh makes the API return that shape. Neither waits for the
other. Swap the fixture for a `fetch` at the end of each stage.

---

## Stage 0 — Agree and scaffold (H0–H2)

**Gate: a Next.js page renders, and `GET /api/leases` returns fixture JSON.**

| Who | Task |
| --- | --- |
| Both | Read [`SYSTEM_DESIGN.md`](SYSTEM_DESIGN.md) §2 and agree the model/code split out loud |
| Both | Freeze the API contract — copy the fixtures below into both repos |
| Sarvesh | Open Devpost Prizes tab, correct [`SPONSORS.md`](SPONSORS.md) |
| Sarvesh | `pip install fastapi uvicorn`, stub the 9 endpoints returning fixtures |
| Jenil | `npx create-next-app@15.0.3 web --ts --tailwind --app`, add shadcn/ui |
| Jenil | Sidebar shell: Dashboard · Leases · Exceptions · Audit |
| Both | Hyphenate + SpacetimeDB booths |

**Fixtures to freeze now** — put these in `web/lib/fixtures.ts` and
`leasedesk/api/fixtures.py`:

```json
{
  "leases": [
    {"lease_id": "STORE-14", "location": "Store 14 — Daly City, CA",
     "lessor": "Serramonte Retail Partners LLC", "status": "exception",
     "monthly_rent": 19626.65, "liability": 559665.35, "end": "2028-12-31"}
  ],
  "exception": {
    "exception_id": "exc_014_jul", "lease_id": "STORE-14",
    "period": "2026-07-01", "expected": 19626.65, "actual": 17400.00,
    "delta": -2226.65, "status": "pending_review",
    "investigation": {
      "root_cause": "amendment", "confidence": 0.94,
      "evidence": [{"doc_id": "eml_20260618", "date": "2026-06-18",
        "source": "dana.reyes@serramonteretail.com",
        "quote": "Base rent reduced to $17,400 per month effective July 1, 2026."}],
      "liability_before": 559665.35, "liability_after": 1002921.05,
      "rou_before": 538771.19, "rou_after": 982026.89,
      "entries": [
        {"account": "Lease liability", "debit": 0, "credit": 443255.70},
        {"account": "ROU asset", "debit": 443255.70, "credit": 0},
        {"account": "ROU asset", "debit": 4624.74, "credit": 0},
        {"account": "Rent expense", "debit": 0, "credit": 4624.74}
      ]
    }
  }
}
```

---

## Stage 1 — The money screen, on fixtures (H2–H6)

**Gate: the exception screen renders Store 14 end to end from fixtures.**
Screenshot it. This is your floor — you can now always demo something.

| Who | Task |
| --- | --- |
| Sarvesh | `GET /api/leases`, `/api/exceptions`, `/api/exceptions/{id}` against the real engine |
| Sarvesh | Wire `remeasure()` output into the exception response shape |
| Jenil | `ExceptionDetail` page layout: header, timeline, evidence, schedules, entries |
| Jenil | `JournalEntryTable` with the debits = credits assertion shown |
| Jenil | `EvidenceCard` — quote, source, date, confidence |

**Build order within the screen:** entries table → evidence card → schedule diff
→ timeline. The entries table is the proof; the timeline is the theatre. Proof
first.

---

## Stage 2 — Real data, real wiring (H6–H10)

**Gate: THE DEMO PATH WORKS END TO END on real engine output. Stop and
celebrate. This is the project.**

| Who | Task |
| --- | --- |
| Sarvesh | SQLite persistence: leases, schedules, payments, exceptions, audit |
| Sarvesh | `POST /api/exceptions/{id}/approve` — activate v2, append audit event |
| Sarvesh | Seed script: load `data/` into the DB on boot |
| Jenil | Replace every fixture with real `fetch` |
| Jenil | Dashboard: four metric tiles + exception list |
| Jenil | Leases list with status badges |

**Checkpoint question:** can a stranger walk up, click from dashboard to
approval, and understand it with no narration? If not, fix that before
anything else.

---

## Stage 3 — Backup, then the live agent (H10–H16)

**Gate: a recorded video exists on disk, and Claude actually finds the
amendment.**

| Who | Task |
| --- | --- |
| **Both** | **H10–H11: record the backup video.** Not optional, not later |
| Sarvesh | Test `--live`: Claude recovers the amendment from the raw `.eml` |
| Sarvesh | `POST /api/exceptions/{id}/investigate` as an SSE stream, 4 events |
| Jenil | `InvestigationTimeline` consuming SSE with staged reveals |
| Jenil | `ScheduleDiff` — before/after side by side, changed rows highlighted |

The SSE timeline is what makes the demo feel alive. It is also the first thing
to cut if it fights you — a static timeline with a 600ms fake delay per stage
looks identical on stage and takes 20 minutes.

---

## Stage 4 — The trust story (H16–H22)

**Gate: the "what if it's wrong" answer is visible on screen, not spoken.**

| Who | Task |
| --- | --- |
| Sarvesh | Confidence threshold → `Escalated` state when below 0.7 |
| Sarvesh | **Second exception that the agent cannot explain** — route to human |
| Sarvesh | `GET /api/audit` — every action, every actor, append-only |
| Jenil | Audit trail screen: chronological, agent vs human, evidence links |
| Jenil | `AgentActivityFeed` — three agents, last action each |
| Jenil | Escalated state styling — distinct from exception |

The unexplained exception is the highest-value item in this stage. It is a
30-minute change that answers the single most likely judge question.

---

## Stage 5 — Scale and sponsors (H22–H28)

**Gate: the portfolio looks like a real company, and one sponsor integration
is done.**

| Who | Task |
| --- | --- |
| Sarvesh | Seed 8–10 leases so the dashboard isn't one row |
| Sarvesh | **Pick one:** SpacetimeDB audit trail, or Elastic document search |
| Jenil | Portfolio view with filters, straight-through-processing % |
| Jenil | Two-window live sync demo, if SpacetimeDB landed |
| Jenil | Empty states, loading states, error states |

**Hard rule:** if the sponsor integration isn't working by H26, revert it and
move on. A half-integrated SpacetimeDB that breaks the demo is worse than no
SpacetimeDB.

---

## Stage 6 — Submission (H28–H32)

**Gate: submitted. Not drafted — submitted.**

| Who | Task |
| --- | --- |
| Sarvesh | Make the repo public, README with a screenshot at the top |
| Sarvesh | Verify no API key in history: `git log -p \| grep -i "sk-ant"` |
| Jenil | Re-record the video with the finished UI |
| Both | Devpost writeup, leading with the dollar number, naming all sponsors |
| Both | Submit with four hours to spare — the deadline queue is real |

---

## Stage 7 — Rehearsal (H32–H36)

**Gate: both of you can run the demo alone, cold, five times.**

- Run it with Wi-Fi off. Know exactly which step needs the network.
- One drives, one talks. Never both. Swap once so either can do either.
- Rehearse the three judge questions out loud ([plan doc](https://claude.ai/artifact/SMhFpskYkhDhRNdnqohWss) §judge questions).
- Laptop: never sleep, notifications off, one clean browser window, terminal
  pre-opened and scrolled to the top.
- Say the numbers out loud. "Four hundred forty-three thousand" lands.

---

## Cut list, in order

You will slip. Cut from the top of this list, early rather than halfway
through:

1. Visa payment integration
2. Portfolio view across locations — say "all 40" instead of showing it
3. Agent activity feed — the exception timeline covers it
4. SpacetimeDB / Elastic — revert cleanly
5. SSE streaming — static timeline with fake delays
6. `--live` extraction — demo the stored amendment

**Never cut:** the exception screen, before/after schedules, the approve button,
the unexplained exception, the backup video.

## Never build

- A chat interface — invites judges to break it live
- Scanned-PDF OCR — unbounded debugging, zero demo value
- Multi-entity consolidation — nobody understands it in 2 minutes
- Finance-lease classification — doubles the test surface for nothing
- Real GL posting — `ready_to_post` is the honest boundary

## Working agreements

- **Commit every 30 minutes.** Hackathon laptops die.
- **Separate files, always.** Sarvesh never opens `web/`, Jenil never opens
  `leasedesk/`. Conflicts cost more than duplication.
- **Branch per stage**, merge at each gate. `main` is always demo-ready.
- **Say "I'm stuck" at 30 minutes**, not at three hours.
- **Sleep in shifts from H18.** Two tired people make worse decisions than one
  rested one. Four hours each, staggered.
- **One terminal runs the tests on repeat.** If `pytest` goes red, stop and fix
  before anything else.
