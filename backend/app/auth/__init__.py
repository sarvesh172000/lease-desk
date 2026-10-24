"""Who is asking: passwords, the signed session cookie, and login.

    passwords.py   argon2 hashes, and `set-dev-passwords` for a seeded laptop
    sessions.py    the cookie (an actor id, signed and timed) and the actor it names
    routes.py      /api/auth: login, logout, me, and the demo-only switcher
    deps.py        `current_actor` and `require_role(...)` for every other router

Login says who someone is; `work/roles.py` `can()` decides what they may do.
Agents are actors but never log in: they act through the worker as
`lease_agent`, never through the API.

This package's `__init__` imports nothing, so `python -m app.auth.passwords`
runs without loading FastAPI.
"""
