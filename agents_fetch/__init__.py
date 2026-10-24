"""Fetch.ai / ASI:One front door for Lease Desk (PHASE_3.md group 9, C8 and S2).

    front_desk.py           "Northbay Lease Desk": Chat Protocol, pairing, routing
    rulebook_agent.py       lease questions answered with page and quote
    investigation_agent.py  why a charge is off: mailbox search, remeasurement
    approvals_agent.py      the paired person's queue, reviews, answers, actions
    understand.py           ASI:One's asi1 model, in front of the grammar, suggestions only
    grammar.py              the fixed chat grammar (chat input is untrusted)
    cards.py                ASI1 Interactive Card builders
    client.py               the Lease Desk HTTP API, the agents' only way in
    live.py                 the SpacetimeDB agent_step feed
    pairing.py              where the front desk keeps each chat user's token
    protocol.py             what the agents say to each other, as plain data
    runtime.py, wire.py     the uAgents wiring (needs agents_fetch/requirements.txt)
    run.py, connect.py      run all four in one Bureau; create their Agentverse mailboxes

Everything but runtime.py, wire.py, run.py and connect.py imports without
uagents installed. README.md has how to run and register the agents.
"""
