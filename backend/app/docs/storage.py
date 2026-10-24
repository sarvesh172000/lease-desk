"""Content-addressed document store.

Every file is keyed by the SHA-256 of its own bytes, so storing the same
document twice is the same write and re-syncing a source can never duplicate.
The key is what `source_document.sha256` holds and what citations point at.

Local disk now; the Protocol is here so MinIO or Azure Blob can be dropped in
behind it without touching callers.
"""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Iterator, Protocol, Union


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Storage(Protocol):
    def put(self, data: bytes) -> str:
        """Store bytes and return their sha256. Storing twice is a no-op."""

    def get(self, sha256: str) -> bytes:
        """Return the stored bytes, or raise KeyError."""

    def exists(self, sha256: str) -> bool: ...


class LocalStorage:
    """Files under `root`, fanned out two levels so one directory never holds
    every document: `ab/cd/abcd…`."""

    def __init__(self, root: Union[str, Path]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, sha256: str) -> Path:
        _validate(sha256)
        return self.root / sha256[:2] / sha256[2:4] / sha256

    def put(self, data: bytes) -> str:
        digest = sha256_of(data)
        target = self._path(digest)
        if target.exists():
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file in the same directory, then rename, so a reader
        # never sees a half-written document.
        fd, tmp = tempfile.mkstemp(dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return digest

    def put_file(self, path: Union[str, Path]) -> str:
        return self.put(Path(path).read_bytes())

    def get(self, sha256: str) -> bytes:
        target = self._path(sha256)
        if not target.exists():
            raise KeyError(sha256)
        return target.read_bytes()

    def exists(self, sha256: str) -> bool:
        return self._path(sha256).exists()

    def iter_keys(self) -> Iterator[str]:
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and len(path.name) == 64:
                yield path.name


def _validate(sha256: str) -> None:
    """Reject anything that isn't a hex digest, so a key can never escape the
    store's root via `..` or an absolute path."""
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise ValueError("not a sha256 hex digest: %r" % (sha256,))
