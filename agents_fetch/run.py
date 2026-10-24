"""Run the four Lease Desk agents together, in one uAgents Bureau.

    python -m agents_fetch.run              all four on Agentverse (mailboxes), Bureau on AGENT_PORT (8001)
    python -m agents_fetch.run --offline    local endpoints only, for testing on a laptop

The repo's .env is read first (without overriding what the shell already
set), so the four seeds, the API URL and the optional keys live in one place.
Variables: README.md and .env.example. Messages between the four agents are
delivered in-process by the Bureau; each agent still has its own seed,
address and mailbox, and the specialists still answer only the front desk.
"""

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """KEY=VALUE lines into the environment, without overriding what is already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip().strip('"').strip("'")
        if value:       # an empty line from .env.example must not blank a variable set elsewhere
            os.environ.setdefault(key, value)


def main(argv=None) -> None:  # pragma: no cover - long-running, needs uagents
    argv = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.INFO)
    load_dotenv()
    os.environ["LEASEDESK_AGENT_MAILBOX"] = "0" if "--offline" in argv else "1"
    from .runtime import build_bureau  # after the environment is loaded

    build_bureau().run()


if __name__ == "__main__":  # pragma: no cover
    main()
