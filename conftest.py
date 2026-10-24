"""Import paths for the suite.

The repo currently holds two trees: the original `leasedesk/` engine package
and the `backend/app/` layout the plan ports it into. Both are importable so
the engine's tests keep passing while the port happens.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent
for path in (ROOT, ROOT / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
