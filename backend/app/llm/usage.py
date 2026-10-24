"""Token and cost log.

Phase 3 reports cost per clinic per month; this is where that number comes
from. Every call appends one line, cache hits included at zero cost, so the
cache's value is visible rather than assumed.
"""

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Union

# Claude Opus 5.5, USD per million tokens.
PRICING = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.02},
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = PRICING.get(model)
    if not rates:
        return 0.0
    return round(
        input_tokens / 1_000_000 * rates["input"]
        + output_tokens / 1_000_000 * rates["output"],
        6,
    )


@dataclass
class Usage:
    prompt_ref: str
    model: str
    cache_hit: bool
    input_tokens: int
    output_tokens: int
    cost_usd: float
    clinic_id: Optional[str] = None
    period: Optional[str] = None
    run_id: Optional[str] = None


class UsageLog:
    def __init__(self, path: Optional[Union[str, Path]] = None):
        self.path = Path(path) if path else None
        self.entries: List[Usage] = []
        self._lock = threading.Lock()

    def record(self, usage: Usage) -> None:
        with self._lock:
            self.entries.append(usage)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a") as fh:
                    fh.write(json.dumps(asdict(usage)) + "\n")

    def total_cost(self) -> float:
        return round(sum(e.cost_usd for e in self.entries), 6)

    def by_clinic(self) -> dict:
        out = {}
        for e in self.entries:
            if e.clinic_id:
                out[e.clinic_id] = round(out.get(e.clinic_id, 0.0) + e.cost_usd, 6)
        return out
