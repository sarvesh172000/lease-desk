"""Turn a stored document into pages, text and word boxes.

Three things come out of here and each has a job:

  - **Page text**, numbered, is what the abstraction agent reads. Every page is
    labelled so the model can cite a page number and be checked on it.
  - **Word boxes** are what makes a citation provable. The model returns a
    verbatim quote; Stage 3's `citations.py` matches that quote back to a run
    of words and returns their union rectangle, which the UI draws on the page.
    Without boxes a citation is an assertion; with them it is a location.
  - **Page images** at 150 dpi are what the viewer shows, and what Phase 2
    sends to vision for scanned pages that carry no text layer.

Coordinates are PDF points with the origin at the top-left of the page, which
is what PyMuPDF returns and what the frontend overlay expects. `Page.width`
and `Page.height` are included so the UI can scale boxes to any render size.
"""

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

import pymupdf

DEFAULT_DPI = 150


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    block: int
    line: int
    index: int

    def as_rect(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass
class Page:
    number: int  # 1-based, as cited
    width: float
    height: float
    text: str
    words: List[Word] = field(default_factory=list)
    _normalized_cache: Optional[Tuple[str, List[Tuple[int, int]]]] = field(
        default=None, repr=False, compare=False
    )

    @property
    def has_text_layer(self) -> bool:
        """False for a scan. Phase 2 routes these to vision."""
        return bool(self.words)

    def normalized(self) -> Tuple[str, List[Tuple[int, int]]]:
        """The page's words as one normalized string, plus the character span
        each word occupies in it.

        Matching happens on this stream rather than word by word, because a
        real quote rarely lines up with word boundaries: "$18,500.00" is one
        word but a quote may say "18,500.00", and "9.69%," carries a trailing
        comma the quote will not have.
        """
        if self._normalized_cache is None:
            parts, spans, cursor = [], [], 0
            for word in self.words:
                token = _normalize(word.text)
                if not token:
                    spans.append((cursor, cursor))
                    continue
                if parts:
                    cursor += 1  # the joining space
                spans.append((cursor, cursor + len(token)))
                parts.append(token)
                cursor += len(token)
            self._normalized_cache = (" ".join(parts), spans)
        return self._normalized_cache

    def search(self, needle: str) -> List[Tuple[float, float, float, float]]:
        """Every box where `needle` appears, matched on the character stream so
        a quote can start or end inside a word.

        Exact after normalization. Stage 3's `citations.py` layers fuzzy
        matching over this for quotes the model paraphrased slightly.
        """
        target = _normalize(needle)
        if not target:
            return []
        haystack, spans = self.normalized()
        hits, start = [], haystack.find(target)
        while start != -1:
            end = start + len(target)
            covered = [
                word for word, (ws, we) in zip(self.words, spans)
                if we > start and ws < end and we > ws
            ]
            if covered:
                hits.append(union(covered))
            start = haystack.find(target, start + 1)
        return hits


@dataclass
class Document:
    sha256: Optional[str]
    pages: List[Page]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def page(self, number: int) -> Page:
        for p in self.pages:
            if p.number == number:
                return p
        raise KeyError("page %d not in document (%d pages)" % (number, self.page_count))

    def numbered_text(self) -> str:
        """The whole document as the abstraction agent sees it: every page
        fenced with its number, so a cited page can be checked."""
        return "\n\n".join(
            "=== PAGE %d OF %d ===\n%s" % (p.number, self.page_count, p.text)
            for p in self.pages
        )

    def find(self, needle: str) -> List[Tuple[int, Tuple[float, float, float, float]]]:
        """Every (page number, box) where the text appears."""
        out = []
        for page in self.pages:
            out.extend((page.number, box) for box in page.search(needle))
        return out


def extract(pdf_bytes: bytes, sha256: Optional[str] = None) -> Document:
    pages: List[Page] = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for index, page in enumerate(doc, start=1):
            rect = page.rect
            pages.append(
                Page(
                    number=index,
                    width=rect.width,
                    height=rect.height,
                    text=page.get_text("text"),
                    words=[
                        Word(text=w[4], x0=w[0], y0=w[1], x1=w[2], y1=w[3],
                             block=int(w[5]), line=int(w[6]), index=int(w[7]))
                        for w in page.get_text("words")
                    ],
                )
            )
    return Document(sha256=sha256, pages=pages)


def render_page_png(pdf_bytes: bytes, page_number: int, dpi: int = DEFAULT_DPI) -> bytes:
    """One page as PNG. 1-based, matching the page numbers in citations."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        if not 1 <= page_number <= doc.page_count:
            raise KeyError("page %d not in document (%d pages)" % (page_number, doc.page_count))
        return doc[page_number - 1].get_pixmap(dpi=dpi).tobytes("png")


def render_all_pages(pdf_bytes: bytes, dpi: int = DEFAULT_DPI) -> List[bytes]:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]


def union(words: Sequence[Word]) -> Tuple[float, float, float, float]:
    """The rectangle covering every word — what gets drawn on the page."""
    if not words:
        raise ValueError("no words to union")
    return (
        min(w.x0 for w in words),
        min(w.y0 for w in words),
        max(w.x1 for w in words),
        max(w.y1 for w in words),
    )


def page_text_rows(document: Document) -> Iterable[dict]:
    """Rows for the `page_text` table. The tsvector column is generated in
    Postgres, so nothing here needs to know about search."""
    for page in document.pages:
        yield {
            "document_sha256": document.sha256,
            "page": page.number,
            "width": page.width,
            "height": page.height,
            "text": page.text,
            "word_count": len(page.words),
            "has_text_layer": page.has_text_layer,
        }


def _normalize(value: str) -> str:
    """Fold the differences that stop a true quote from matching: curly quotes,
    dashes, non-breaking spaces, case."""
    swaps = {
        "’": "'", "‘": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", " ": " ", "−": "-",
    }
    for bad, good in swaps.items():
        value = value.replace(bad, good)
    return " ".join(value.lower().split())
