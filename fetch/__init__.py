"""Lease Desk on ASI:One: four agents that put the desk inside a chat.

    run.py          runs the four agents in one Bureau
    agents.py       the uAgents wiring: chat protocol, specialist protocols, sender checks
    specialists.py  what the reconciliation, investigation and approvals agents do
    remote.py       the coordinator's view of the specialists
    desk.py         the conversation: one message in, one reply out
    intent.py       what the person asked for (ASI:One's model, with a fallback)
    api.py          the Lease Desk HTTP API, as the agents see it
    live.py         the SpacetimeDB live feed

Only agents.py and run.py import uagents, so everything else is tested in the
main suite without the agent framework installed (tests/test_fetch_*.py).

The agents never compute money. Every figure they show comes from the API,
which reads it off the engine and the checker, and every action they take is
the same transition the web app sends, under the same permissions.
"""
