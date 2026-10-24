"""Fetch.ai / ASI:One front door for Lease Desk (PHASE_3.md group 9, chunk C8).

    front_desk.py       "Northbay Lease Desk": Chat Protocol, pairing, routing
    rulebook_agent.py   lease questions answered with page and quote
    approvals_agent.py  the paired person's queue, reviews, answers, actions
    cards.py            ASI1 Interactive Card builders
    grammar.py          the fixed chat grammar (chat input is untrusted)
    client.py           the Lease Desk HTTP API, the agents' only way in
    pairing.py          where the front desk keeps each chat user's token
    protocol.py         what the agents say to each other, as plain data
    runtime.py, wire.py the uAgents wiring (needs agents_fetch/requirements.txt)

Everything but runtime.py and wire.py imports without uagents installed.
README.md has how to run and register the agents.
"""
