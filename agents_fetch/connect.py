"""Create the four agents' Agentverse mailboxes from the terminal.

    python -m agents_fetch.connect          (with `python -m agents_fetch.run` already running)

This sends each running agent the request the Agent Inspector's
Connect -> Mailbox button sends, carrying an Agentverse API key
(AGENTVERSE_API_KEY, from agentverse.ai -> Profile -> API Keys) instead of the
browser's sign-in. Use it when the inspector can't reach the agents: browsers
often block a page from calling 127.0.0.1. Running it again is harmless.

Each agent proves its identity to Agentverse with its own seed; the key only
says which account the mailboxes belong to. The key is sent to the local
Bureau only, never printed.
"""

import os
import sys

import httpx

from .run import load_dotenv
from .runtime import ENV_SEED


def main() -> int:  # pragma: no cover - talks to the running agents
    load_dotenv()
    key = os.environ.get("AGENTVERSE_API_KEY", "").strip()
    if not key:
        raise SystemExit("set AGENTVERSE_API_KEY in .env (agentverse.ai -> Profile -> API Keys)")
    from uagents_core.identity import Identity

    url = "http://127.0.0.1:%s/connect" % os.environ.get("AGENT_PORT", "8001")
    failed = 0
    for role, env in ENV_SEED.items():
        seed = os.environ.get(env, "").strip()
        if not seed:
            raise SystemExit("%s is not set" % env)
        address = Identity.from_seed(seed, 0).address
        try:
            r = httpx.post(url, headers={"x-uagents-address": address},
                           json={"user_token": key, "agent_type": "mailbox"}, timeout=60)
            body = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            print("%-14s could not reach the agent at %s (%s); is `python -m agents_fetch.run` running?"
                  % (role, url, exc))
            failed += 1
            continue
        if body.get("success"):
            print("%-14s mailbox connected  %s" % (role, address))
        else:
            print("%-14s FAILED: %s" % (role, body.get("detail") or body))
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
