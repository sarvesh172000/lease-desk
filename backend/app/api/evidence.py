"""Where on the page: the boxes the money screen draws for one charge check.

    invoice_line    the billed line on the landlord's invoice
                    landlord_charge.document_id -> source_document.sha256
    lease_citation  the clause the checker cited (evidence.proof.quote)
                    lease PDF sha from <data_dir>/manifest.json

Both are located with the document pipeline the abstraction agent uses
(`docs.pipeline.extract` for words and boxes, `docs.citations.locate` for
quote -> box), over the content-addressed store. Nothing here guesses: when
the document is not on file, is not a readable PDF, or the text is not on any
page, the answer is None and the UI shows its empty state. A box is never
made up.

Boxes are `[x0, y0, x1, y1]` in PDF points, origin top-left, as §16 says.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..docs.citations import locate
from ..docs.pipeline import Document, extract
from ..docs.storage import LocalStorage

_SHA_LEN = 64


def document_for_charge(conn: Connection, charge_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The landlord charge and the sha256 of the invoice it came from."""
    if not charge_id:
        return None
    row = conn.execute(text("""
        SELECT c.id, c.description, c.amount, c.page, c.invoice_id, d.sha256
          FROM landlord_charge c
          LEFT JOIN source_document d ON d.id = c.document_id
         WHERE c.id = :id
    """), {"id": charge_id}).mappings().first()
    return dict(row) if row else None


def lease_sha(data_dir: Path, lease_id: Optional[str]) -> Optional[str]:
    """The lease PDF's sha256 from the generator's manifest, or None."""
    if not lease_id:
        return None
    manifest = _manifest(str(data_dir))
    for entry in manifest.get("leases", []) if isinstance(manifest, dict) else []:
        if isinstance(entry, dict) and entry.get("lease_id") == lease_id:
            sha = entry.get("document_sha256")
            return sha if isinstance(sha, str) and len(sha) == _SHA_LEN else None
    return None


def invoice_line(storage: Optional[LocalStorage], charge: Optional[Mapping]) -> Optional[Dict[str, Any]]:
    """{doc_id, page, box, description, amount} for the billed line, or None.

    The description is located as a quote; the box then takes in the amount
    printed on the same row (the formatted `$4,820.00`), when there is one,
    so the reviewer sees the line and its figure together."""
    if charge is None or not charge.get("sha256") or not charge.get("description"):
        return None
    doc = load_document(storage, charge["sha256"])
    if doc is None:
        return None
    found = locate(doc, charge["description"], page_hint=charge.get("page"))
    if found is None:
        return None
    box = list(found.box)
    amount = float(charge["amount"])
    page = doc.page(found.page)
    printed = "${:,.2f}".format(abs(amount))
    for word in page.words:
        mid = (word.y0 + word.y1) / 2
        if word.text.strip("()-") == printed and box[1] <= mid <= box[3]:
            box = [min(box[0], word.x0), min(box[1], word.y0),
                   max(box[2], word.x1), max(box[3], word.y1)]
            break
    return {"doc_id": charge["sha256"], "page": found.page, "box": _round(box),
            "description": charge["description"], "amount": round(amount, 2)}


def lease_citation(storage: Optional[LocalStorage], sha: Optional[str], lease_id: Optional[str],
                   proof: Any) -> Optional[Dict[str, Any]]:
    """{doc_id, page, box, label, quote} for the clause the checker cited."""
    if not sha or not isinstance(proof, dict):
        return None
    quote = proof.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        return None
    section = proof.get("section")
    label = "%s · §%s" % (lease_id, section) if section else "%s · lease" % lease_id
    page, box = proof.get("page"), proof.get("box")
    if isinstance(page, int) and _is_box(box):          # the checker located it already
        return {"doc_id": sha, "page": page, "box": _round(box), "label": label, "quote": quote}
    doc = load_document(storage, sha)
    if doc is None:
        return None
    found = locate(doc, quote, page_hint=page if isinstance(page, int) else None)
    if found is None:
        return None
    return {"doc_id": sha, "page": found.page, "box": _round(found.box), "label": label,
            "quote": quote, "match_score": found.score}


def load_document(storage: Optional[LocalStorage], sha: str) -> Optional[Document]:
    if storage is None or not storage.exists(sha):
        return None
    try:
        return _extract(str(storage.root), sha)
    except Exception:  # noqa: BLE001 — PyMuPDF raises several types for a non-PDF
        return None


# Content-addressed: the bytes behind a sha never change, so neither do the
# words extracted from them.
@lru_cache(maxsize=64)
def _extract(root: str, sha: str) -> Document:
    return extract(LocalStorage(root).get(sha), sha256=sha)


def _manifest(data_dir: str) -> Any:
    path = Path(data_dir) / "manifest.json"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return {}
    return _read_manifest(str(path), stamp)


@lru_cache(maxsize=4)
def _read_manifest(path: str, _stamp: int) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def _is_box(value: Any) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value))


def _round(box) -> list:
    return [round(float(v), 2) for v in box]
