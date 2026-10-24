# Sponsor plan: Fetch.ai (ASI:One), Azure, SpacetimeDB

How Lease Desk uses each sponsor's technology without rewriting what already
works. The rule carried over from the README still holds: the model decides
*what the lease says*, the code decides *what the lease costs*. None of the
sponsor tech below gets to produce a balance or a journal entry.

| Sponsor | What it does for us | What it does NOT replace |
|---|---|---|
| Fetch.ai / ASI:One | The front door: the whole workflow runs inside an ASI:One chat | The engine, the ledger, Claude extraction |
| Azure | Hosting: Postgres, API, worker and agents running 24/7 | Any code; same containers |
| SpacetimeDB | Real-time feed of what the agents are doing, live in the web app | Postgres as the system of record |

---

## 1. Fetch.ai track: ASI:One Agent Challenge

### What the judges require (from the hackpack)

1. At least one agent registered on **Agentverse**.
2. The **Agent Chat Protocol** (`chat_protocol_spec` from `uagents_core`): handle
   `ChatMessage`, ack every message with `ChatAcknowledgement`, handle
   `TextContent`, `StartSessionContent`, `EndSessionContent`.
3. Discoverable and usable through **ASI:One**: `agent.include(chat_proto, publish_manifest=True)`.
4. Real tool execution or multi-agent orchestration, "more than a chatbot".
5. The **primary workflow is completed entirely inside an ASI:One conversation**,
   with no custom frontend. This is the one that shapes everything below.
6. A public GitHub repo whose README has each agent's **name and address**, the
   two badges below, and run instructions.
7. A demo video of 3 to 5 minutes, a Devpost submission, and registration through
   the CalHacks ASI:One Submission Agent.

Bonus points go to multi-agent collaboration, the **Payment Protocol**,
**ASI1 Interactive Cards**, recovery from failed tool calls, and an agent that
could keep running after the hackathon.

Judging weights: Functionality 25%, Use of Fetch.ai 20%, Innovation 20%,
Impact 20%, UX and presentation 15%.

```markdown
![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)
```

### The agents

Lease Desk already has the pieces as Python modules (`backend/app/agents/`).
Each one becomes a uAgent; the coordinator is the only one ASI:One talks to.

```
ASI:One chat
    │  Chat Protocol
    ▼
LeaseDesk Coordinator  ── asi1 model: work out what the user wants, plan the steps
    │
    ├── Abstraction Agent    "read this lease"        → agents/abstraction.py (Claude)
    ├── Reconciliation Agent "does cash match?"       → engine schedule + checker
    └── Investigation Agent  "why doesn't it match?"  → POST /api/exceptions/{id}/investigate
                                                        (mailbox search, trust.py, remeasure)
```

- **Coordinator** (`fetch/agents.py`, run by `python -m fetch.run`): uses the ASI:One LLM
  (`https://api.asi1.ai/v1`, model `asi1`, OpenAI-compatible client) for
  intent and planning, which is the ASI:One usage the "Use of Fetch.ai" score
  looks for. It never computes money; it calls the other agents and relays
  their results.
- **Specialist agents** talk to the existing FastAPI backend over HTTP as the
  `lease_agent` role, so the database permissions, the state machine and the
  audit hash chain apply to them exactly as they do to the web app.
- Keep Claude for extraction. The hackpack allows the Claude Agent SDK and plain
  Python, and our extraction eval scores Claude. ASI:One does routing; Claude
  does reading.

### The demo conversation (all of it inside ASI:One)

1. "Which of our leases have a problem this month?" → the Reconciliation Agent
   lists Store 14: underpaid $2,226.65 a month since July.
2. "Why?" → the Investigation Agent searches the mailbox, finds the amendment
   (a three-year extension at lower rent) and quotes the clause it relied on.
3. It shows the remeasurement (liability $559,665.35 → $1,002,921.05) and the
   balanced adjusting entries as an **Interactive Card** (a review screen).
4. "Approve" on the card → the entries are posted through the API as the
   controller, and the audit trail records it.
5. "Abstract this new lease" (a PDF link) → a **Payment Protocol** request
   (Stripe test mode, e.g. $5 per lease abstracted) → on `CommitPayment` the
   agent verifies the Checkout Session is `paid`, sends `CompletePayment`, and
   only then runs the abstraction.

That covers multi-step planning, tool execution, multi-agent work, Cards and
payments, and every step is a real write to a real ledger rather than chat.

### Payment Protocol (bonus)

- `Protocol(spec=payment_protocol_spec, role="seller")` on the Abstraction Agent.
- `RequestPayment` with `Funds(payment_method="stripe")` and an embedded Stripe
  Checkout Session in `metadata["stripe"]` (publishable key only).
- On `CommitPayment`: retrieve the session; `payment_status == "paid"` →
  `CompletePayment` and run; otherwise `CancelPayment`.
- The model is believable: per-lease abstraction is how lease-abstraction
  services actually charge.
- The reference example pins `uagents==0.25.5`, `uagents-core==0.4.9`.

### Steps

1. Get an ASI:One API key (asi1.ai) and an Agentverse account.
2. `pip install uagents uagents-core openai stripe` (a separate
   `fetch/requirements.txt`, so the backend's dependencies don't change).
3. Build the coordinator from the ASI:One example (`mailbox=True`,
   `publish_agent_details=True`, `publish_manifest=True`), run it, open the
   Inspector link, connect the **Mailbox**, then edit the name, handle and
   description on Agentverse so ASI:One can find it for lease questions.
4. Add the three specialist agents; test with `client.py` by address first,
   then from ASI:One Chat.
5. Add Cards for the review step, then the Payment Protocol.
6. Host the agents on Azure (below) so they're online while judges try them.
   An agent that isn't running doesn't answer.
7. README: agent names and addresses, the badges, run steps. Devpost, plus the
   ASI:One Submission Agent at
   `asi1.ai/festival/calhacks2026/dashboard`.

Env: `ASI_ONE_API_KEY`, `AGENT_SEED_<NAME>` (one per agent, kept secret: the
seed *is* the agent's identity and address), `STRIPE_SECRET_KEY`,
`STRIPE_PUBLISHABLE_KEY` (test keys), `LEASEDESK_API_URL`.

---

## 2. Azure: hosting everything

Same containers as `docker-compose.yml`, run on Azure with the credits.

| Local (compose) | Azure |
|---|---|
| `db` (postgres:16.4) | **Azure Database for PostgreSQL Flexible Server**, v16 (Burstable B1ms is enough) |
| `api` | **Azure Container Apps**, external ingress on 8000 |
| `worker` | Container Apps, no ingress, min replicas 1 |
| Fetch agents | Container Apps, **min replicas 1** (they must stay online for ASI:One) |
| `web` (Next.js) | Container Apps or Azure Static Web Apps |
| `data/generated` documents | **Azure Blob Storage** container, or Azure Files mounted at `/app/data` |
| `.env` secrets | Container Apps secrets, or Key Vault |
| images | **Azure Container Registry** |

Checked against our schema:

- `001_schema.sql` uses `CREATE EXTENSION pgcrypto`. On Flexible Server,
  allow-list it first: server parameter `azure.extensions = PGCRYPTO`.
- `roles.sql` uses `CREATE ROLE ... LOGIN`. The Flexible Server admin has
  `CREATEROLE`, so the four roles (`lease_agent`, `lease_gateway`, `lease_api`,
  `lease_reader`) are created as usual. Nothing needs superuser; the
  `SECURITY DEFINER` functions run as their owner, which is the admin.
- Point the containers at it with `LEASEDESK_DB_HOST`, `LEASEDESK_DB_PORT=5432`
  and the role passwords; Azure requires TLS, so add `sslmode=require` to the
  connection.
- Documents: the cheapest change is Azure Files mounted at `/app/data`, so no
  code changes. Blob Storage is the cleaner end state, but it is not
  S3-compatible, so the storage adapter would need an Azure backend.

Run the test suite against the Azure database once
(`LEASEDESK_DB_HOST=<server>.postgres.database.azure.com python -m pytest -p ci.require_db`)
to prove the roles and integrity triggers behave the same as on local Postgres.

Rough order: Resource group → ACR (`az acr build` the backend image) →
Postgres Flexible Server (+ pgcrypto allow-list, firewall for Container Apps) →
`python -m app.db.bootstrap` against it → Container Apps environment with
api, worker, agents and web → secrets.

---

## 3. SpacetimeDB: the live view

**Don't move the ledger into SpacetimeDB.** Postgres holds the database roles,
the state machine, the audit hash chain and the 576 database tests that prove
them. Rebuilding that on SpacetimeDB during a hackathon would trade a
working, tested ledger for a demo risk. SpacetimeDB is very good at one thing
we don't have yet: pushing changes to every open browser instantly. Use it
for exactly that.

**What goes in it:** a small module (TypeScript; SpacetimeDB modules are written
in Rust, C#, C++ or TypeScript, and there is no Python SDK) with two public tables:

- `agent_step`: `run_id, agent, step, detail, at`. Each line is one thing an
  agent did ("Coordinator → Investigation Agent", "searched 214 emails",
  "found amendment dated 2026-06-12", "proposed 4 entries").
- `desk_status`: one row per open exception and its current state, mirrored
  from Postgres after each change.

**How data gets in:** the Python agents and the worker call reducers over
SpacetimeDB's HTTP API, with no Python SDK needed:

```
POST https://maincloud.spacetimedb.com/v1/database/leasedesk-live/call/record_step
Authorization: Bearer <token>
["run-42", "investigation", "found_amendment", "Amendment No. 2, 2026-06-12"]
```

A failed call is logged and dropped. The live feed is decoration and must never
block a posting.

**How it gets out:** the Next.js frontend uses the SpacetimeDB TypeScript/React
client SDK to subscribe to `agent_step` and `desk_status`. While a judge talks
to the agents in ASI:One, a second screen (the web app's exception page, or a
"live" panel on `/welcome`) shows each agent's step as it happens. That is the
"agents communicate and reason in real time" line from the Functionality
criterion, made visible, and it puts SpacetimeDB on screen in the video.

**Hosting:** `spacetime login`, `spacetime publish leasedesk-live` to Maincloud
(or run it in a Container App on Azure if credits require it to be there).

---

## Ownership

This repo splits ownership, so the work splits along the same lines:

- **Sarvesh:** a new top-level `fetch/` (the agents), `spacetime/` (the module),
  and the README badges and agent addresses.
- **Jenil (needs their OK):** anything in `backend/app/{api,db,work,auth,...}`,
  `frontend/`, `Makefile`, `.github/`: the Azure connection settings
  (`sslmode`), the SpacetimeDB subscription in the frontend, and any new API
  endpoint the agents need (for example a list of open exceptions if one
  doesn't exist).

## Suggested order (most points first)

1. Coordinator + chat protocol on Agentverse, answering from the existing API. *(eligibility)*
2. Investigation Agent end to end in ASI:One: the Store 14 story. *(the demo)*
3. Azure: Postgres + API + agents always on. *(judges can actually try it)*
4. Interactive Card for the approval step.
5. SpacetimeDB live feed.
6. Payment Protocol on abstraction.
7. README, video, Devpost, ASI:One Submission Agent.
