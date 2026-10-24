# Northbay Lease Desk — Fetch.ai agents

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Lease accounting for Northbay PT, driven from **ASI:One**. Three uAgents work
together on real lease work: ASI:One talks to the front desk, and the front
desk hands each request to the right specialist over agent messaging.

| Agent | Name | Address | What it does |
|---|---|---|---|
| Front desk | `Northbay Lease Desk` | `agent1q…` *(after registration)* | Agent Chat Protocol entry point; pairs your ASI:One account to your Lease Desk account; routes to the specialists |
| Rulebook | `lease_desk_rulebook` | `agent1q…` *(after registration)* | Answers lease questions with the page and quote each answer comes from |
| Approvals | `lease_desk_approvals` | `agent1q…` *(after registration)* | Your open items and questions, held-item review cards, answers and approvals |

Agentverse profiles: *(fill in after registration)* · Public ASI:One chat: *(fill in)*

## What you can say

```
pair K7QM-9XDA                       link this chat to your Lease Desk account (code from Today)
what needs me this week?             your open items and questions, with due dates and dollars at stake
review 42                            a held item as an Interactive Card: amounts, sources, trust, why
why was this held?                   (right after a review) or: why 42
answer 42 yes, suite 110 is ours     answer the open question
uphold 42 lease caps CAM at 5%       approve / uphold / hold / reject / resume <item> [reason]
what is Clinic 03's escalation and where does it say so?
whoami · unpair · help
```

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
  reaches the chat routes only (no minting more codes, no batch release, no
  demo reset), expires in seven days, and dies on `unpair` or when revoked in
  the web app. Pair and unpair are audit events.
- **Unpaired chat users get help text and nothing else** — the front desk does
  not make a single API call for them.
- **Chat input is untrusted.** Messages are matched against a fixed grammar
  (`grammar.py`), never handed to a model to pick a tool. An action runs only
  when the message *starts* with its verb and item number; everything after is
  the reason or answer, stored as text. One message is at most one action.
  Card buttons go through the same grammar, and the specialists re-validate
  every command that crosses agent messaging.
- **Refusals are visible.** A Desert regional manager who tries to answer a
  Bay Area question from chat gets *"Refused … item is in region REG-BAY, not
  PER-RM-DESERT's region REG-DESERT … recorded as audit event #N (allowed =
  false)"*, and the same event is in the web app's audit timeline.

## Run locally

The backend first (`make demo-data && make api`, API on `:8000`). Then, in a
separate environment so the main install stays light:

```bash
python3 -m venv .venv-agents
./.venv-agents/bin/pip install -r requirements.txt -r agents_fetch/requirements.txt

# One seed per agent. Seeds ARE the agents' identities: keep them out of git.
export LEASEDESK_FRONT_DESK_SEED="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export LEASEDESK_RULEBOOK_SEED="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export LEASEDESK_APPROVALS_SEED="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export LEASEDESK_API_URL=http://localhost:8000

./.venv-agents/bin/python -m agents_fetch.runtime addresses   # print the three agent1q... addresses
./.venv-agents/bin/python -m agents_fetch.runtime bureau      # all three in one process, local endpoints
```

Or one process per agent (each on its own port: 8101 / 8102 / 8103,
override with `LEASEDESK_FRONT_DESK_PORT` etc.):

```bash
./.venv-agents/bin/python -m agents_fetch.rulebook_agent
./.venv-agents/bin/python -m agents_fetch.approvals_agent
./.venv-agents/bin/python -m agents_fetch.front_desk
```

When the processes do not share all three seeds, give each the others'
addresses instead: `LEASEDESK_RULEBOOK_ADDRESS` and
`LEASEDESK_APPROVALS_ADDRESS` for the front desk, `LEASEDESK_FRONT_DESK_ADDRESS`
for the specialists (they then accept requests from the front desk only).
Optionally set the same `LEASEDESK_PAIRING_CLIENT_KEY` on the API and the
front desk so only the front desk can redeem pairing codes.

## Register on Agentverse (mailbox) and use from ASI:One

This needs the team's Agentverse / ASI:One account; nothing below is done
until someone signs in. Steps:

1. Generate the three seeds once (above) and keep them in a password manager
   or the deployment's secret store. The addresses are derived from them, so
   the same seeds always give the same agents.
2. Start the agents with the mailbox on:
   `export LEASEDESK_AGENT_MAILBOX=1`, then run the three processes (or the
   bureau). Each logs `Agent inspector available at https://agentverse.ai/inspect/?uri=…&address=agent1q…`.
3. Open each inspector link, sign in to Agentverse, and choose
   **Connect → Mailbox**. The agent is now registered and receives messages
   through its Agentverse mailbox while it runs on your machine.
4. In Agentverse → *Agents* → each agent: check the name, paste this README
   (the agents also publish it via `readme_path`), set a handle and avatar,
   and confirm the **AgentChatProtocol** manifest shows (published on startup).
5. In ASI:One, search for "Northbay Lease Desk" (or its handle / address),
   start a chat and send `help`, then `pair <code>` with a code from the web
   app's Today screen.
6. Fill in the table at the top: the three `agent1q…` addresses
   (`python -m agents_fetch.runtime addresses`), the Agentverse profile URLs,
   and the public shared ASI:One chat URL. Check the badge tags above against
   the current Fetch.ai hackpack.
7. For the CalHacks ASI:One submission, register the front desk address in the
   hackathon's submission form.

## Layout

```
front_desk.py       FrontDesk: pairing, sessions, routing (plain Python)
rulebook_agent.py   lease questions -> GET /api/leases/{id}/versions, cited
approvals_agent.py  inbox / review / why / actions -> /api/items...
cards.py            ASI1 Interactive Cards (detail card for a held item, carousel for the inbox)
grammar.py          the fixed chat grammar
client.py           the HTTP API client (the agents' only way in)
pairing.py          per-chat-user token store (memory, or uAgents ctx.storage)
protocol.py         request/reply dicts between the agents
runtime.py, wire.py the uAgents wiring: Chat Protocol, acks, sessions, send_and_receive
```

Everything except `runtime.py` and `wire.py` imports without uagents, and is
tested against the real API and a real database in
`backend/tests/platform/test_fetch_agents.py` (and `test_pairing.py`,
`backend/tests/test_fetch_grammar.py`). `test_fetch_uagents.py` runs the
three agents and a stand-in ASI:One user as real uAgents in one Bureau; it is
skipped when uagents is not installed.

Not built: the Payment Protocol (cut first by PHASE_3's priority order), and
approving dispute letters from chat (there is no dispute-letter action in the
items API yet).
