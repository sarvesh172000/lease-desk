"""GET /api/documents/{sha}/pages and GET /api/documents/{sha}/pages/{n}.png.

The viewer draws a citation's `box` (PDF points, origin top-left) over a page
image, so it needs each page's size in points and the page itself. Both come
from the document pipeline in `docs/pipeline.py`, reading the
content-addressed store under `<data_dir>/documents`.

A sha is a lowercase 64-character hex digest or it is a 400: the store refuses
anything else, which is also what keeps a key from escaping its root.
A well-formed sha the store does not hold is a 404.
"""

import re
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi import Path as PathParam

from ..auth.deps import current_actor
from ..docs.pipeline import DEFAULT_DPI, extract, render_page_png
from ..docs.storage import LocalStorage
from .deps import get_storage
from .schemas import DocumentPages, PageSize

router = APIRouter(prefix="/api", tags=["documents"], dependencies=[Depends(current_actor)])

_SHA = re.compile(r"^[0-9a-f]{64}$")

# Content-addressed: the bytes behind a sha never change, so neither does
# anything derived from them.
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


@router.get("/documents/{sha}/pages", response_model=DocumentPages)
def document_pages(sha: str, response: Response,
                   storage: Optional[LocalStorage] = Depends(get_storage)) -> DocumentPages:
    root = _check(sha, storage)
    pages = _page_sizes(root, sha)
    response.headers.update(IMMUTABLE)
    return DocumentPages(sha256=sha, page_count=len(pages),
                         pages=[PageSize(number=n, width=w, height=h) for n, w, h in pages])


@router.get("/documents/{sha}/pages/{n}.png", response_class=Response,
            responses={200: {"content": {"image/png": {}}}})
def page_image(sha: str, n: int = PathParam(..., ge=1, le=10_000),
               storage: Optional[LocalStorage] = Depends(get_storage)) -> Response:
    root = _check(sha, storage)
    count = len(_page_sizes(root, sha))
    if n > count:
        raise HTTPException(404, "page %d not in document (%d pages)" % (n, count))
    return Response(_render(root, sha, n), media_type="image/png", headers=IMMUTABLE)


def _check(sha: str, storage: Optional[LocalStorage]) -> str:
    """The store root holding `sha`, or the right error."""
    if not _SHA.match(sha):
        raise HTTPException(400, "not a sha256 hex digest: %r" % sha)
    if storage is None or not storage.exists(sha):
        raise HTTPException(404, "no document %s" % sha)
    return str(storage.root)


# Cached by (store, sha): the key names the bytes, so the cache never holds
# them and never goes stale.

@lru_cache(maxsize=256)
def _sizes(root: str, sha: str):
    doc = extract(LocalStorage(root).get(sha), sha256=sha)
    return tuple((p.number, round(p.width, 2), round(p.height, 2)) for p in doc.pages)


def _page_sizes(root: str, sha: str):
    try:
        return _sizes(root, sha)
    except Exception:  # noqa: BLE001 — PyMuPDF raises several types for a non-PDF
        raise HTTPException(415, "document %s is not a readable PDF" % sha) from None


@lru_cache(maxsize=64)
def _render(root: str, sha: str, n: int) -> bytes:
    return render_page_png(LocalStorage(root).get(sha), n, dpi=DEFAULT_DPI)
