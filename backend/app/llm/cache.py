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
    """JSON bodies on disk, one file per key.

    `replay` is an optional read-only directory of the same shape, consulted
    after a miss in `root` and never written. The repository commits the
    answers the demo depends on there (data/reference/llm_cache), so a fresh
    clone, a container or CI replays them with no key and no network, however
    the process was started and wherever its own cache lives.
    """

    def __init__(self, root: Union[str, Path], enabled: bool = True,
                 replay: Optional[Union[str, Path]] = None):
        self.root = Path(root)
        self.replay = Path(replay) if replay else None
        self.enabled = enabled
        if enabled:
            self.root.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[dict]:
        if not self.enabled:
            return None
        for root in (self.root, self.replay):
            value = self._read(root, key) if root else None
            if value is not None:
                self.hits += 1
                return value
        self.misses += 1
        return None

    def _read(self, root: Path, key: str) -> Optional[dict]:
        path = self._path(key, root)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            # A truncated file from an interrupted run is a miss, not a crash.
            return None

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

    def _path(self, key: str, root: Optional[Path] = None) -> Path:
        return (root or self.root) / key[:2] / (key + ".json")
