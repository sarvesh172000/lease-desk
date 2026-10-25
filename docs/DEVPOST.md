# Devpost draft: Lease Desk

## Tagline

The lease accountant's seat, filled: Lease Desk reads every lease, checks
every landlord bill against it, and holds only the money that's wrong, with
the invoice line and the lease clause side by side.

## Inspiration

A multi-clinic physical therapy group pays dozens of landlords every month.
Leases get amended, landlords bill the new terms, and the books keep running
the old schedule. In our generated company, one unrecorded amendment left
**$443,255.70** of lease liability off the balance sheet. Nobody knew,
because each invoice on its own looked right.

## What it does

- **Reads leases.** Claude extracts 13 terms per lease, each one cited to the
  exact box on the PDF page it came from. Invented quotes are rejected.
- **Checks every charge.** Every month, every landlord charge is checked
  against the confirmed lease: rent, CAM, escalations, duplicates, the wrong
  suite. In January it checked 12 charges and held 5 for $25,736.36,
  including a rent invoice billed twice (both copies individually correct)
  and rent for a suite the clinic doesn't lease.
- **Finds the cause.** When rent stops matching, an investigation agent
  searches the mailbox, finds the executed amendment, ranks it above the
  lease, and the ASC 842 engine remeasures the lease ($559,665.35 →
  $1,002,921.05). It then proposes balanced journal entries.
- **Never pays on its own.** Agents propose; people approve. Only a separate
  gateway role can post to the ledger, and the database enforces it: when an
  agent tried to post, Postgres refused.
- **Keeps everything on record.** Every action, including every refused
  attempt, goes into an append-only, hash-chained audit trail that verifies on
  demand. An auditor can download an evidence pack for any item.
- **Runs the rest of the desk:**
  - drafts dispute letters for upheld holds;
  - tracks lease obligations (CAM audit windows, renewal notices);
  - learns payment policies from history, backtests them and waits for a
    controller's approval;
  - answers "why was this held?" from the rows behind it.

## How we built it

- **Claude (Anthropic):** lease abstraction with structured output and cited
  boxes, the investigation agent and the "why" explanations. Prompts are
  versioned, responses cached, and untrusted documents fenced.
- **Postgres 16:** four database roles (agent, gateway, API, reader) with
  exact grants. Triggers enforce an append-only, hash-chained audit trail,
  balanced journal entries, closed periods and who may move work to which
  state.
- **Python 3.13 / FastAPI / SQLAlchemy:**
  - an event-sourced work layer (8 states, 9 transitions, separation of
    duties) that replays byte-identically;
  - a job queue and worker;
  - an ASC 842 engine.
- **Fetch.ai / ASI:One:** Lease Desk as a chat agent. A person pairs their
  chat with a one-time code and then acts as themselves, under the same
  permissions.
- **SpacetimeDB:** a live mirror of work-item state and agent steps, so
  screens update without a refresh. Postgres stays the source of truth.
- **Next.js 15 / React 19 / Tailwind:** a dual-theme "control room" UI with
  framer-motion and React Three Fiber (the investigation's document stack, the
  audit chain).
- **Reliability:** a chaos suite kills the worker mid-month and checks the
  recovered run is identical to an uninterrupted one. The backend has more
  than 1,600 tests and the frontend 123.

## Challenges we ran into

- Making "the AI is never trusted with money" true in the database, not just
  in the code.
- Getting an investigation, a remeasurement and a human approval to replay
  byte-identically from the event log.
- Keeping every number on screen exactly what the engine produced: the UI
  never computes or rounds money.

## Accomplishments we're proud of

- The hidden-amendment moment runs live, end to end, from the PDF to balanced
  entries.
- Refused attempts are first-class, visible red blocks in the audit chain.
- A judge's path through the whole desk takes under three minutes with no
  console errors (measured in our rehearsal report).

## What we learned

<!-- fill in -->

## What's next

- Approving the remeasurement from the money screen and posting it through the gateway.
- Running the dispute and obligations sweeps as part of the monthly run.
- Azure deployment with one login per role.
- More landlords and invoice formats.

## Built with

claude, anthropic, python, fastapi, postgresql, sqlalchemy, next.js, react,
typescript, tailwindcss, three.js, fetch.ai, asi-one, spacetimedb
<!-- add azure once the deployment (backend task S3) is live -->
