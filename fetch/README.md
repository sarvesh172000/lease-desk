# Lease Desk on ASI:One

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

The Lease Desk workflow inside an ASI:One chat: see which landlord charges are
on hold, read the lease clause behind one, have the mailbox searched for what
explains it, and approve or hold it. Four agents do the work, under the same
API, roles and audit trail as the web app.

## The agents

| Agent | Address | Does |
|---|---|---|
| `lease-desk` (coordinator) | `agent1qg2tetdj6qf5wnf744mvvtz66rzfrmvqkx5dcejzpg78q3prt9aa58j2g0g` | Talks to ASI:One (Agent Chat Protocol), reads intent with ASI:One's `asi1` model, keeps the conversation, and asks the specialists |
| `lease-desk-reconciliation` | `agent1qtqqwygy3z7uc2ypu4qsc2dklqmuadvgy23mwpl54wqccl02sp3ag4pn3ud` | What's on hold, and the evidence behind one exception |
| `lease-desk-investigation` | `agent1q2mr89mwmdn0l8wj5t5uyzpd09fhfq8mvs037zf44wsvlt0znamqqkmg0l9` | Searches the mailbox for what explains a variance; the engine remeasures the lease if it changed |
| `lease-desk-approvals` | `agent1qgfyhfmc2ngygsck8f3xllf9mqr7plc8dv82czjjn9f3gh4psjcrjczh4dg` | Approves or holds, as the configured person, under Lease Desk's role checks |

Each address comes from that agent's seed in `.env`. The addresses stay the
same as long as the seeds do.

```
ASI:One ──chat protocol──▶ lease-desk (coordinator, asi1 for intent)
                              │ DeskRequest / DeskReply (send_and_receive)
                              ├──▶ reconciliation ──┐
                              ├──▶ investigation  ──┼──▶ Lease Desk API ──▶ Postgres ledger
                              └──▶ approvals      ──┘
                 investigation + approvals ──▶ SpacetimeDB live feed (each step, as it happens)
```

- **Only the coordinator can ask a specialist.** Any agent on Agentverse can
  message any other, so a specialist refuses (403) a request from anyone else.
  Otherwise a stranger could ask the approvals agent to sign off a charge.
- **Nothing posts without a yes.** Approve and hold first show what the action
  does to the money, and wait.
- **No agent computes money.** Every figure comes from Lease Desk's engine.
  ASI:One's model only decides which question was asked.

## Run it

1. **Lease Desk itself**, with demo data, from the repo root:

   ```bash
   make demo
   ```

2. **The agents' environment.** A separate venv, so the backend doesn't need these packages:

   ```bash
   python3.13 -m venv fetch/.venv && fetch/.venv/bin/pip install -r fetch/requirements.txt
   ```

   `python -m fetch.run` reads the repo's `.env`:

   | Variable | |
   |---|---|
   | `AGENT_SEED_COORDINATOR`, `_RECONCILIATION`, `_INVESTIGATION`, `_APPROVALS` | One long random phrase per agent. Each *is* that agent's identity, so keep them secret and never change them. |
   | `LEASEDESK_EMAIL` / `LEASEDESK_PASSWORD` | The person the agents act as. With `make demo` data: `priya.raghunathan@northbaypt.example` / `demo` (the controller). |
   | `ASI_ONE_API_KEY` | From asi1.ai. Without it, a keyword reader understands simpler phrasing. |
   | `LEASEDESK_API_URL` | Default `http://localhost:8000` |
   | `AGENT_PORT` | Default `8001` |
   | `SPACETIME_DB` / `SPACETIME_TOKEN` | Optional: the live feed (`spacetime/README.md`). If unset, the feed is off. |

3. **Start all four:**

   ```bash
   fetch/.venv/bin/python -m fetch.run
   ```

   The log prints each agent's address and an **Agent inspector** link, and
   `Manifest published successfully` for each protocol.
   (`--offline` runs them without Agentverse, for local testing.)

4. **Connect each agent to Agentverse**, once. Either:

   - put an Agentverse API key (agentverse.ai → Profile → API Keys) in `.env`
     as `AGENTVERSE_API_KEY`, and with the agents running:

     ```bash
     fetch/.venv/bin/python -m fetch.connect
     ```

   - or sign in at agentverse.ai and open each agent's inspector
     (`https://agentverse.ai/inspect/?uri=http%3A//127.0.0.1%3A8001&address=<address>`)
     → **Connect** → **Mailbox**. Browsers sometimes block the inspector from
     reaching 127.0.0.1; if the log never says `Successfully registered as
     mailbox agent`, use `fetch.connect` instead.

   The descriptions and READMEs come from `profiles/`.

5. **Chat.** On the coordinator's Agentverse profile, click **Chat with Agent**,
   or ask ASI:One something like *"any problems with our leases this month?"*.
   The agents only answer while the process is running.

## Try

```
what's open?
show LEASE-03
why is it off?
approve it
yes
```

## Layout

| File | |
|---|---|
| `run.py` | Runs the four agents in one Bureau (each with its own mailbox) |
| `agents.py` | The uAgents wiring: chat protocol, specialist protocols, the coordinator→specialist calls, the sender check |
| `specialists.py` | What each specialist does with a request (no agent framework) |
| `remote.py` | The coordinator's view of the specialists, the same calls as the API |
| `desk.py` | The conversation: one message in, one markdown reply out |
| `intent.py` | ASI:One's model reads intent; a keyword reader takes over if it can't |
| `api.py` | The Lease Desk API client |
| `live.py` | The SpacetimeDB live feed |
| `profiles/` | Each agent's Agentverse README |

`tests/test_fetch_*.py` cover the conversation, the specialists and the feed
in the main suite, with no network and no uagents.

## Submission checklist (Cal Hacks, Fetch.ai track)

- [x] Agents registered on Agentverse, with the Chat Protocol on the coordinator
- [x] Multi-agent orchestration (coordinator + three specialists)
- [x] Public repo, with agent names, addresses and the Innovation Lab badges (this file)
- [ ] Each agent's mailbox connected on Agentverse (step 4)
- [ ] Whole workflow tested from ASI:One
- [ ] Demo video, 3–5 minutes
- [ ] Devpost submission
- [ ] Registered with the CalHacks ASI:One Submission Agent (asi1.ai/festival/calhacks2026/dashboard)

## Known limits

- All four agents act as one configured person, so everyone chatting acts as
  that person. Fine for a demo; a real deployment would map each ASI:One user
  to their own Lease Desk account.
- Conversation state (the last exception, a pending yes) is kept in memory and
  is lost on restart.
