"""Versioned prompt files.

Prompts are data, not string literals buried in agent code: every call records
which prompt id and version produced it, and that reference is written into
`agent_run` and into every resulting event's `model_ref`. When a number is
questioned six months later, the exact prompt that produced it is recoverable.

Layout: `prompts/<prompt_id>/v<N>.md`. Edit a released prompt and you add a new
version; you never change v1 in place, because v1 is what the old events cite.

Variables use `$name` (not `{name}`), because prompt bodies contain JSON braces.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Dict, List, Optional, Union

PROMPTS_DIR = Path(__file__).parent / "prompts"
_VERSION_FILE = re.compile(r"^v(\d+)\.md$")


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    sha: str
    body: str

    @property
    def ref(self) -> str:
        """Short, stable reference recorded on every event."""
        return "%s@v%d+%s" % (self.id, self.version, self.sha[:8])

    def render(self, variables: Optional[Dict[str, object]] = None) -> str:
        variables = variables or {}
        try:
            return Template(self.body).substitute(variables)
        except KeyError as exc:
            raise KeyError(
                "prompt %s needs variable %s, which was not supplied" % (self.ref, exc)
            ) from None


class PromptRegistry:
    def __init__(self, root: Union[str, Path] = PROMPTS_DIR):
        self.root = Path(root)

    def get(self, prompt_id: str, version: Optional[int] = None) -> Prompt:
        """Load a prompt. Without a version, the highest on disk."""
        folder = self.root / prompt_id
        if not folder.is_dir():
            raise KeyError("no prompt %r in %s" % (prompt_id, self.root))

        available = self.versions(prompt_id)
        if not available:
            raise KeyError("prompt %r has no v<N>.md files" % prompt_id)
        chosen = max(available) if version is None else version
        if chosen not in available:
            raise KeyError(
                "prompt %r has no version %d (have %s)"
                % (prompt_id, chosen, ", ".join(str(v) for v in available))
            )

        body = (folder / ("v%d.md" % chosen)).read_text()
        return Prompt(
            id=prompt_id,
            version=chosen,
            sha=hashlib.sha256(body.encode()).hexdigest(),
            body=body,
        )

    def versions(self, prompt_id: str) -> List[int]:
        folder = self.root / prompt_id
        if not folder.is_dir():
            return []
        out = []
        for path in folder.iterdir():
            match = _VERSION_FILE.match(path.name)
            if match:
                out.append(int(match.group(1)))
        return sorted(out)

    def ids(self) -> List[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and self.versions(p.name))
