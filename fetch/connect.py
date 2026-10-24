"""Create the four agents' Agentverse mailboxes from the terminal.

    python -m fetch.connect          (with `python -m fetch.run` already running)

This sends each running agent the request the Agent Inspector's
Connect → Mailbox button sends, carrying an Agentverse API key
(AGENTVERSE_API_KEY, from agentverse.ai → Profile → API Keys) instead of the
browser's sign-in. Use it when the inspector can't reach the agents: browsers
often block a page from calling 127.0.0.1. Running it again is harmless.

Each agent proves its identity to Agentverse with its own seed; the key
only says which account the mailboxes belong to.
"""

import os
import sys
from pathlib import Path

import httpx

from .run import _load_dotenv

AGENTS = ("coordinator", "reconciliation", "investigation", "approvals")


def main() -> int:
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    key = os.environ.get("AGENTVERSE_API_KEY")
    if not key:
        raise SystemExit("set AGENTVERSE_API_KEY in .env (agentverse.ai → Profile → API Keys)")
    from uagents_core.identity import Identity

    url = "http://127.0.0.1:%s/connect" % os.environ.get("AGENT_PORT", "8001")
    failed = 0
    for name in AGENTS:
        seed = os.environ.get("AGENT_SEED_%s" % name.upper())
        if not seed:
            raise SystemExit("AGENT_SEED_%s is not set" % name.upper())
        address = Identity.from_seed(seed, 0).address
        try:
            r = httpx.post(url, headers={"x-uagents-address": address},
                           json={"user_token": key, "agent_type": "mailbox"}, timeout=60)
            body = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            print("%-15s could not reach the agent at %s (%s); is `python -m fetch.run` running?" % (name, url, exc))
            failed += 1
            continue
        if body.get("success"):
            print("%-15s mailbox connected  %s" % (name, address))
        else:
            print("%-15s FAILED: %s" % (name, body.get("detail") or body))
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
