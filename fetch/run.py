"""Run the four Lease Desk agents together.

    python -m fetch.run              all four on Agentverse (mailboxes), port 8001
    python -m fetch.run --offline    no Agentverse: local testing only

Environment: fetch/README.md. The repo's .env is read if present.
"""

import os
import sys
from pathlib import Path

from uagents import Bureau


def _load_dotenv(path: Path) -> None:
    """KEY=VALUE lines into the environment, without overriding what is already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    from .agents import build  # after the environment is loaded

    offline = "--offline" in sys.argv[1:]
    bureau = Bureau(port=int(os.environ.get("AGENT_PORT", "8001")))
    for agent in build(offline=offline).values():
        bureau.add(agent)
    bureau.run()


if __name__ == "__main__":
    main()
