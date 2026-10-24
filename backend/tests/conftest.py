import sys
from pathlib import Path

# `backend/` for `app.*`, and this directory for test helpers like `fakes`.
for path in (Path(__file__).resolve().parents[1], Path(__file__).resolve().parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
