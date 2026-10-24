# Lease Desk on ASI:One

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

The Lease Desk workflow inside an ASI:One chat: see what's on hold, read the
lease clause behind it, have the mailbox searched for what explains it, and
approve or hold. All of it runs through the same API, roles and audit trail
as the web app.

| Agent | Address | Does |
|---|---|---|
| `lease-desk` (coordinator) | *fill in after first run* | Talks to ASI:One (Agent Chat Protocol), reads intent with ASI:One's `asi1` model, calls the Lease Desk API |

More agents (abstraction, reconciliation, investigation) and the Payment
Protocol come next; see `docs/SPONSOR_PLAN.md`.

## Run it

1. **Lease Desk itself**, with demo data (from the repo root):

   ```bash
   make demo
   ```

   That serves the API on `:8000`. Any running API works; set
   `LEASEDESK_API_URL` to point at it.

2. **The agent's environment.** Use a fresh venv; the backend does not need these packages.

   ```bash
   python3.13 -m venv fetch/.venv && fetch/.venv/bin/pip install -r fetch/requirements.txt
   ```

   | Variable | |
   |---|---|
   | `AGENT_SEED_COORDINATOR` | A long random phrase. It *is* the agent's identity: same seed, same address. Keep it secret. |
   | `LEASEDESK_EMAIL` / `LEASEDESK_PASSWORD` | The person the agent acts as. With `make demo` data: `priya.raghunathan@northbaypt.example` / `demo` (the controller). |
   | `ASI_ONE_API_KEY` | From asi1.ai. Without it, a keyword reader understands simpler phrasing. |
   | `LEASEDESK_API_URL` | Default `http://localhost:8000` |
   | `AGENT_PORT` | Default `8001` |
   | `SPACETIME_DB` / `SPACETIME_TOKEN` | Optional: the live feed of every step to SpacetimeDB (`spacetime/README.md`). Unset, the feed is off. |

3. **Start it:**

   ```bash
   fetch/.venv/bin/python -m fetch.coordinator
   ```

   The log prints the agent's address, an **Agent inspector** link, and
   `Manifest published successfully: AgentChatProtocol`.

4. **Connect it to Agentverse.** Open the inspector link → **Connect** →
   **Mailbox**. Then open the agent's profile on Agentverse; the description
   and README come from `AGENT_PROFILE.md`.

5. **Chat.** Click **Chat with Agent** on Agentverse, or ask ASI:One something
   like *"any problems with our leases this month?"*. The agent only answers
   while the process is running.

## Try

```
what's open?
show LEASE-03
why is it off?
approve it
yes
```

Approve and hold always show what the action does to the money first and wait
for a **yes**. If the signed-in person's role can't make the change, Lease
Desk refuses it, the refusal is recorded, and the agent says so.

## Layout

| File | |
|---|---|
| `coordinator.py` | The uAgent: chat protocol, acknowledgements, and the start and end of each session |
| `desk.py` | The conversation: one message in, one markdown reply out |
| `intent.py` | ASI:One's model reads intent; a keyword reader takes over if it can't |
| `api.py` | The Lease Desk API client (signs in, signs in again if the session expires) |
| `live.py` | The SpacetimeDB live feed: each step, sent in order on a background thread, never blocking a reply |

`tests/test_fetch_desk.py` covers the conversation in the main suite, with no
network and no uagents.

## Known limits

- The agent acts as one configured person, so everyone chatting with it acts
  as that person. Fine for a demo; a real deployment would map each ASI:One
  user to their own Lease Desk account.
- Conversation state (the last exception, a pending yes) is kept in memory and
  is lost on restart.
