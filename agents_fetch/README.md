# Northbay Lease Desk — Fetch.ai agents

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Lease accounting for Northbay PT, driven from **ASI:One**. Four uAgents work
together on real lease work: ASI:One talks to the front desk, and the front
desk hands each request to the right specialist over agent messaging. Each
person acts as **themselves**, paired to their own Lease Desk account.

| Agent | Name | Seed variable | Address | What it does |
|---|---|---|---|---|
| Front desk | `Northbay Lease Desk` | `AGENT_SEED_COORDINATOR` | `agent1qg2tetdj6qf5wnf744mvvtz66rzfrmvqkx5dcejzpg78q3prt9aa58j2g0g` | Agent Chat Protocol entry point; pairs your ASI:One account to your Lease Desk account; reads plain language with ASI:One's `asi1` model; routes to the specialists |
| Rulebook | `lease_desk_rulebook` | `AGENT_SEED_RECONCILIATION` | `agent1qtqqwygy3z7uc2ypu4qsc2dklqmuadvgy23mwpl54wqccl02sp3ag4pn3ud` | Answers lease questions with the page and quote each answer comes from |
| Investigation | `lease_desk_investigation` | `AGENT_SEED_INVESTIGATION` | `agent1q2mr89mwmdn0l8wj5t5uyzpd09fhfq8mvs037zf44wsvlt0znamqqkmg0l9` | Searches the mailbox for what explains a charge's variance; the engine remeasures the lease if it changed. Proposes, never posts |
| Approvals | `lease_desk_approvals` | `AGENT_SEED_APPROVALS` | `agent1qgfyhfmc2ngygsck8f3xllf9mqr7plc8dv82czjjn9f3gh4psjcrjczh4dg` | Your open items and questions, held-item review cards, answers and approvals |

Each address is derived from its seed, so it stays the same as long as the
seed does. The seed variable names are the ones these agents were first
registered on Agentverse under; keep them. Agentverse profiles are
`profiles/*.md`. Public ASI:One chat: *(fill in after the live check)*

```
ASI:One ──Chat Protocol──▶ Northbay Lease Desk (front desk: pairing, grammar, asi1 reading)
                              │ SpecialistRequest / SpecialistReply (send_and_receive, sender-checked)
                              ├──▶ rulebook       ──┐
                              ├──▶ investigation  ──┼──▶ Lease Desk HTTP API, as the paired person ──▶ Postgres
                              └──▶ approvals      ──┘        (can(), gateway, hash-chained audit)
         every agent ──▶ SpacetimeDB agent_step feed (its own steps, one run id per chat message)
```

## What you can say

```
pair K7QM-9XDA                       link this chat to your Lease Desk account (code from Today)
what needs me this week?             your open items and questions, with due dates and dollars at stake
review 42                            a held item as an Interactive Card: amounts, sources, trust, why
why was this held?                   (right after a review) or: why 42
investigate 42                       or: why is 42 off? — the mailbox search, the remeasurement, the entries
answer 42 yes, suite 110 is ours     answer the open question
uphold 42 lease caps CAM at 5%       approve / uphold / hold / reject / resume <item> [reason]
what is Clinic 03's escalation and where does it say so?
whoami · unpair · help
```

Anything else, from a paired person, may be read by ASI:One's model (below).

## Permissions are the web app's, not the chat's

- **The agents talk to the Lease Desk HTTP API only, never to the database.**
  Every action is `POST /api/items/{id}/actions/{action}` as the paired
  person, so `can()`, the gateway and the hash-chained audit stream run
  exactly as they do for a click in the web app.
- **Pairing, not passwords.** On the web app's Today screen a person asks for
  a one-time code (`POST /api/pairing/codes`: eight characters, ten minutes,
  works once). Sending `pair <code>` makes the front desk claim it
  (`POST /api/pairing/claim`) for a scoped bearer token bound to that person
  *and* that chat user. Only sha256 hashes are stored server side; the token
  reaches the chat routes only (reads, item actions and the investigation; no
  minting more codes, no batch release, no demo reset), expires in seven
  days, and dies on `unpair` or when revoked in the web app. Pair and unpair
  are audit events.
- **Unpaired chat users get help text and nothing else** — the front desk does
  not make a single API call for them, and their words never reach a model.
- **Chat input is untrusted; the grammar is the boundary.** Messages are
  matched against a fixed grammar (`grammar.py`). An action runs only when the
  message *starts* with its verb and item number; everything after is the
  reason or answer, stored as text. One message is at most one action. Card
  buttons go through the same grammar, and the specialists re-validate every
  command that crosses agent messaging.
- **ASI:One's model suggests, never acts** (`understand.py`). When a paired
  person's message doesn't parse and `ASI_ONE_API_KEY` is set, the front desk
  asks the `asi1` model to fill a fixed form (intent, item, lease, topic, the
  person's own words). That form is written out as a grammar line and parsed
  again; the model may only name items the person can see. A *read* (inbox,
  review, why, investigate, lease) then runs as if typed, with a note saying
  how the message was read. An *action* never runs from a reading: the reply
  is the exact command, to send yourself or confirm with a card button that
  goes through the grammar and `can()` like any other. Without the key, the
  grammar is all there is.
- **Specialists answer the front desk only.** Any agent on Agentverse can
  message any other; a specialist refuses a request from any address but the
  front desk's, and won't start without knowing it.
- **Refusals are visible.** A Desert regional manager who tries to answer a
  Bay Area question from chat gets *"Refused … item is in region REG-BAY, not
  PER-RM-DESERT's region REG-DESERT … recorded as audit event #N (allowed =
  false)"*, and the same event is in the web app's audit timeline.

## The live feed

With `SPACETIME_DB` and `SPACETIME_TOKEN` set, every agent records its own
steps in SpacetimeDB's `agent_step` table as it works (`live.py`; the module
is `spacetime/`): the front desk what it received and where it routed it, the
investigation agent each frame of the investigation as it streams, the
approvals and rulebook agents how their request came out. All steps of one
chat message share one run id. Steps carry commands and outcomes, never a
reason, answer or pairing code (the table is public). Sends are ordered, on a
background thread; a failure is dropped and never reaches the chat. The agents
do not write `desk_status`: the backend publishes item state after each
transition.

## Run locally

The backend first (`make demo-data && make api`, API on `:8000`). Then, in a
separate environment so the main install stays light:

```bash
python3.13 -m venv .venv-agents
./.venv-agents/bin/pip install -r requirements.txt -r agents_fetch/requirements.txt
```

`python -m agents_fetch.run` reads the repo's `.env` (shell variables win):

| Variable | |
|---|---|
| `AGENT_SEED_COORDINATOR`, `AGENT_SEED_RECONCILIATION`, `AGENT_SEED_INVESTIGATION`, `AGENT_SEED_APPROVALS` | One long random secret per agent (front desk, rulebook, investigation, approvals). Each *is* that agent's identity and address: never commit or change them. New ones: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `LEASEDESK_API_URL` | Default `http://localhost:8000` |
| `ASI_ONE_API_KEY` | Optional, from asi1.ai: plain-language reading. Unset: grammar only. `ASI_ONE_MODEL` defaults to `asi1` |
| `SPACETIME_DB`, `SPACETIME_TOKEN`, `SPACETIME_HOST` | Optional: the live feed (`spacetime/README.md`; a publisher token from `python -m agents_fetch.live identity`) |
| `AGENTVERSE_API_KEY` | Only for `python -m agents_fetch.connect` |
| `AGENT_PORT` | The Bureau's port, default `8001` |
| `LEASEDESK_PAIRING_CLIENT_KEY` | Optional, same value on the API: only the front desk can redeem pairing codes |

```bash
./.venv-agents/bin/python -m agents_fetch.runtime addresses   # the four agent1q... addresses
./.venv-agents/bin/python -m agents_fetch.run --offline       # all four in one Bureau, local only
```

The agents can also run one process each (`python -m agents_fetch.front_desk`,
`.rulebook_agent`, `.investigation_agent`, `.approvals_agent`; ports 8101–8104,
override with `LEASEDESK_FRONT_DESK_PORT` etc.). When the processes do not
share all four seeds, give each the others' addresses instead:
`LEASEDESK_RULEBOOK_ADDRESS`, `LEASEDESK_INVESTIGATION_ADDRESS` and
`LEASEDESK_APPROVALS_ADDRESS` for the front desk, `LEASEDESK_FRONT_DESK_ADDRESS`
for the specialists.

## Register on Agentverse (mailbox) and use from ASI:One

The four addresses above are already registered with Agentverse mailboxes.
To bring them up (or re-register after a reset):

1. Put the four seeds in the repo's `.env` (from the password manager; never
   in git). `python -m agents_fetch.runtime addresses` must print the
   addresses in the table above.
2. Start all four with mailboxes: `./.venv-agents/bin/python -m agents_fetch.run`.
   The log shows each agent's address and `Manifest published successfully`
   for each protocol.
3. Connect the mailboxes, once: with `AGENTVERSE_API_KEY` in `.env`
   (agentverse.ai → Profile → API Keys), run
   `./.venv-agents/bin/python -m agents_fetch.connect` while the Bureau runs.
   Or open each agent's inspector link from the log
   (`https://agentverse.ai/inspect/?uri=http%3A//127.0.0.1%3A8001&address=<address>`)
   → **Connect** → **Mailbox**. Browsers sometimes block the inspector from
   reaching 127.0.0.1; if the log never says `Successfully registered as
   mailbox agent`, use `agents_fetch.connect`.
4. In Agentverse → *Agents*: check each name, description and README (the
   agents publish `profiles/*.md` themselves), set a handle and avatar, and
   confirm the **AgentChatProtocol** manifest on the front desk.
5. In ASI:One, search for "Northbay Lease Desk" (or its address), send `help`,
   then `pair <code>` with a code from the web app's Today screen.
6. Fill in the public ASI:One chat URL above, and register the front desk
   address with the CalHacks ASI:One Submission Agent
   (asi1.ai/festival/calhacks2026/dashboard).

The agents answer only while the process runs.

## Layout

```
run.py                 all four agents in one Bureau, after loading the repo .env
connect.py             create the Agentverse mailboxes with AGENTVERSE_API_KEY
front_desk.py          FrontDesk: pairing, sessions, routing, the asi1 reading (plain Python)
rulebook_agent.py      lease questions -> GET /api/leases/{id}/versions, cited
investigation_agent.py investigate -> POST /api/exceptions/exc_{id}/investigate (SSE), frame by frame
approvals_agent.py     inbox / review / why / actions -> /api/items...
understand.py          ASI:One's asi1 model -> a grammar line, re-parsed; never an action
grammar.py             the fixed chat grammar, and render() back to a line
cards.py               ASI1 Interactive Cards (held item, inbox carousel, suggested action)
client.py              the HTTP API client (the agents' only way in)
live.py                the SpacetimeDB agent_step feed
pairing.py             per-chat-user token store (memory, or uAgents ctx.storage)
protocol.py            request/reply dicts between the agents
runtime.py, wire.py    the uAgents wiring: Chat Protocol, acks, sessions, send_and_receive
profiles/              each agent's Agentverse README
```

Everything except `runtime.py`, `wire.py`, `run.py` and `connect.py` imports
without uagents, and is tested against the real API and a real database in
`backend/tests/platform/test_fetch_agents.py`, `test_fetch_investigation.py`
and `test_pairing.py`, and without a database in
`backend/tests/test_fetch_grammar.py`, `test_fetch_understand.py` and
`test_fetch_feed.py`. `test_fetch_uagents.py` runs the four agents and a
stand-in ASI:One user as real uAgents in one Bureau; it is skipped when
uagents is not installed.

Not built: the Payment Protocol, and approving dispute letters from chat
(there is no dispute-letter action in the items API yet).
