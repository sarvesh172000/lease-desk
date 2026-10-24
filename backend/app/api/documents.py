"""A stored document, by sha256 or by its source_document id.

    GET /api/documents/{doc_id}/pages          page count and each page's size in PDF points
    GET /api/documents/{doc_id}/pages/{n}.png  one page at 150 dpi
    GET /api/documents/{doc_id}/file           the PDF itself (application/pdf)

The viewer draws a citation's `box` (PDF points, origin top-left) over a page,
so it needs each page's size in points and the page itself. Both come from
the document pipeline in `docs/pipeline.py`, reading the content-addressed
store under `<data_dir>/documents`.

`doc_id` is either the document's sha256 (64 lowercase hex: the store's key,
what citations point at) or a `source_document.id` (32 lowercase hex, what
`landlord_charge.document_id` holds), which is looked up to its sha256.
Anything else is a 400: the store refuses other keys, which is also what keeps
a key from escaping its root. A well-formed id the store or the table does not
hold is a 404.
"""

import re
from functools import lru_cache
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi import Path as PathParam
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..auth.deps import current_actor
from ..docs.pipeline import DEFAULT_DPI, extract, render_page_png
from ..docs.storage import LocalStorage
from .deps import get_engine, get_storage
from .schemas import DocumentPages, PageSize

router = APIRouter(prefix="/api", tags=["documents"], dependencies=[Depends(current_actor)])

_SHA = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID = re.compile(r"^[0-9a-f]{32}$")

# Content-addressed: the bytes behind a sha never change, so neither does
# anything derived from them.
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
# Resolved through the table: the id is stable, but which bytes it names is
# the database's answer, so revalidate.
PRIVATE = {"Cache-Control": "private, max-age=300"}


@router.get("/documents/{doc_id}/pages", response_model=DocumentPages)
def document_pages(doc_id: str, response: Response,
                   storage: Optional[LocalStorage] = Depends(get_storage),
                   eng: Engine = Depends(get_engine)) -> DocumentPages:
    sha, kind = _resolve(doc_id, eng)
    root = _check(sha, storage)
    pages = _page_sizes(root, sha)
    response.headers.update(IMMUTABLE if sha == doc_id else PRIVATE)
    return DocumentPages(sha256=sha, page_count=len(pages), doc_id=doc_id, kind=kind,
                         pages=[PageSize(number=n, page=n, width=w, height=h) for n, w, h in pages])


@router.get("/documents/{doc_id}/pages/{n}.png", response_class=Response,
            responses={200: {"content": {"image/png": {}}}})
def page_image(doc_id: str, n: int = PathParam(..., ge=1, le=10_000),
               storage: Optional[LocalStorage] = Depends(get_storage),
               eng: Engine = Depends(get_engine)) -> Response:
    sha, _ = _resolve(doc_id, eng)
    root = _check(sha, storage)
    count = len(_page_sizes(root, sha))
    if n > count:
        raise HTTPException(404, "page %d not in document (%d pages)" % (n, count))
    return Response(_render(root, sha, n), media_type="image/png",
                    headers=IMMUTABLE if sha == doc_id else PRIVATE)


@router.get("/documents/{doc_id}/file", response_class=Response,
            responses={200: {"content": {"application/pdf": {}}}})
def document_file(doc_id: str, storage: Optional[LocalStorage] = Depends(get_storage),
                  eng: Engine = Depends(get_engine)) -> Response:
    """The stored bytes, for the browser's PDF viewer. Only PDFs are served:
    anything else in the store is a 415, never sent as something it is not."""
    sha, _ = _resolve(doc_id, eng)
    root = _check(sha, storage)
    data = LocalStorage(root).get(sha)
    if not data.startswith(b"%PDF-"):
        raise HTTPException(415, "document %s is not a PDF" % sha)
    headers = dict(IMMUTABLE if sha == doc_id else PRIVATE)
    headers["Content-Disposition"] = 'inline; filename="%s.pdf"' % sha[:16]
    return Response(data, media_type="application/pdf", headers=headers)


def _resolve(doc_id: str, eng: Engine) -> Tuple[str, Optional[str]]:
    """(sha256, kind) for a sha256 or a source_document id. A sha is used as
    is (the database is not asked: the store is the authority for its own
    keys); a source_document id must be on record."""
    if _SHA.match(doc_id):
        return doc_id, None
    if not _SOURCE_ID.match(doc_id):
        raise HTTPException(400, "not a sha256 or a source document id: %r" % doc_id)
    with eng.connect() as conn:
        row = conn.execute(text("SELECT sha256, kind FROM source_document WHERE id = :id"),
                           {"id": doc_id}).first()
    if row is None:
        raise HTTPException(404, "no document %s" % doc_id)
    return row.sha256.strip(), row.kind


def _check(sha: str, storage: Optional[LocalStorage]) -> str:
    """The store root holding `sha`, or the right error."""
    if not _SHA.match(sha):
        raise HTTPException(400, "not a sha256 hex digest: %r" % sha)
    if storage is None or not storage.exists(sha):
        raise HTTPException(404, "no document %s" % sha)
    return str(storage.root)


# Cached by (store, sha): the key names the bytes, so the cache never holds
# them and never goes stale.

@lru_cache(maxsize=64)
def cached_document(root: str, sha: str):
    """The extracted document behind `sha`. Shared with the exception screen,
    which locates citation boxes in the same pages this viewer draws."""
    return extract(LocalStorage(root).get(sha), sha256=sha)


@lru_cache(maxsize=256)
def _sizes(root: str, sha: str):
    doc = cached_document(root, sha)
    return tuple((p.number, round(p.width, 2), round(p.height, 2)) for p in doc.pages)


def _page_sizes(root: str, sha: str):
    try:
        return _sizes(root, sha)
    except Exception:  # noqa: BLE001 — PyMuPDF raises several types for a non-PDF
        raise HTTPException(415, "document %s is not a readable PDF" % sha) from None


@lru_cache(maxsize=64)
def _render(root: str, sha: str, n: int) -> bytes:
    return render_page_png(LocalStorage(root).get(sha), n, dpi=DEFAULT_DPI)
