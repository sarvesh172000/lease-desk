"""Import paths for the suite, and an early check on the interpreter.

The repo holds two trees: the original `leasedesk/` engine package and the
`backend/app/` layout the plan ports it into. Both are importable so the
engine's tests keep passing while the port happens.
"""

import sys
from pathlib import Path

MINIMUM = (3, 11)

if sys.version_info < MINIMUM:
    raise SystemExit(
        "\nLeaseDesk needs Python %d.%d or newer; this is %d.%d.%d at %s.\n"
        "macOS ships 3.9, which ReportLab refuses to run on.\n\n"
        "    python3.13 -m venv .venv        # or python3.11\n"
        "    ./.venv/bin/pip install -r requirements.txt\n"
        "    ./.venv/bin/python -m pytest\n"
        % (MINIMUM[0], MINIMUM[1],
           sys.version_info[0], sys.version_info[1], sys.version_info[2],
           sys.executable)
    )

ROOT = Path(__file__).parent
for path in (ROOT, ROOT / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
