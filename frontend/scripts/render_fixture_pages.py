"""Render every fixture PDF to page PNGs, the way the API serves them.

Fixtures mode is the offline fallback: the frontend draws document pages as
`<img>` from GET /api/documents/{sha}/pages/{n}.png, so with no API there has
to be an equivalent file on disk. These are rendered by the same
`render_page_png` at the same DPI, which is what keeps a citation box landing
in the same place in both modes.

    python frontend/scripts/render_fixture_pages.py

Writes public/fixtures/docs/<doc_id>/<n>.png, beside the PDFs they come from.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.docs.pipeline import DEFAULT_DPI, extract, render_page_png  # noqa: E402

DOCS = ROOT / "frontend" / "public" / "fixtures" / "docs"


def main() -> int:
    pdfs = sorted(DOCS.glob("*.pdf"))
    if not pdfs:
        print("no fixture PDFs under %s" % DOCS)
        return 1
    written = 0
    for pdf in pdfs:
        data = pdf.read_bytes()
        out = DOCS / pdf.stem
        out.mkdir(exist_ok=True)
        for page in extract(data).pages:
            (out / ("%d.png" % page.number)).write_bytes(
                render_page_png(data, page.number, dpi=DEFAULT_DPI))
            written += 1
        print("%s -> %d page(s)" % (pdf.name, len(extract(data).pages)))
    print("%d page images in %s" % (written, DOCS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
