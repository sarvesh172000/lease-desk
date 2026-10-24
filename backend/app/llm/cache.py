"""Response cache keyed on everything that could change an answer.

Two reasons this exists. The demo must run with zero fresh model calls, so a
rehearsal is fast and a dead venue wifi is survivable. And the eval has to be
reproducible — the same month re-run must score the same, which it cannot do if
the model is re-sampled each time.

The key covers the model, the prompt id, its version AND its content hash, the
inputs, and the name of the output schema. Change any of them and you get a
miss, which is the point: a silently reused answer from an older prompt would
be worse than a slow one.
"""

import hashlib
import json
from pathlib import Path
from typing import Optional, Union


def cache_key(model: str, prompt_ref: str, payload: object, schema: str) -> str:
    canonical = json.dumps(
        {"model": model, "prompt": prompt_ref, "payload": payload, "schema": schema},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class ResponseCache:
    """JSON bodies on disk, one file per key."""

    def __init__(self, root: Union[str, Path], enabled: bool = True):
        self.root = Path(root)
        self.enabled = enabled
        if enabled:
            self.root.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[dict]:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.exists():
            self.misses += 1
            return None
        try:
            value = json.loads(path.read_text())
        except json.JSONDecodeError:
            # A truncated file from an interrupted run is a miss, not a crash.
            self.misses += 1
            return None
        self.hits += 1
        return value

    def put(self, key: str, value: dict) -> None:
        if not self.enabled:
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, sort_keys=True))
        tmp.replace(path)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / (key + ".json")
