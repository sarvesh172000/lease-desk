"""Lease Desk on ASI:One: the agents that put the desk inside a chat.

    api.py          the Lease Desk HTTP API, as the agents see it
    intent.py       what the person asked for (ASI:One's model, with a fallback)
    desk.py         the conversation: one message in, one reply out
    coordinator.py  the uAgent ASI:One talks to (Agent Chat Protocol)

Only coordinator.py imports uagents, so everything else is tested in the
main suite without the agent framework installed (tests/test_fetch_desk.py).

The agents never compute money. Every figure they show comes from the API,
which reads it off the engine and the checker, and every action they take is
the same transition the web app sends, under the same permissions.
"""
