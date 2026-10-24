"""Match a quote back to where it sits on the page.

The abstraction agent returns a value, a page number and the verbatim sentence
it read the value from. That quote is a claim, and this module is what turns it
into a location: a page, a rectangle, and a score saying how well the words the
model reported match the words actually printed.

The score is not decoration. A field whose quote matches exactly is one a human
can check in a second by looking at the highlighted box. A field whose quote
only half-matches means the model paraphrased, misread, or invented — so the
score feeds confidence, and a weak match is flagged rather than trusted.

Exact matching (after normalizing quotes, dashes and whitespace) is tried
first. Fuzzy matching is the fallback, because real models drop a word or
normalize a number even when they have read the right sentence.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

from .pipeline import Document, Page, union

# A quote at or above this scores as verified: a human looking at the box will
# see what the model said it saw.
STRONG = 0.92
# Below this we do not claim to have located the quote at all.
WEAK = 0.70


@dataclass(frozen=True)
class Citation:
    page: int
    box: Tuple[float, float, float, float]
    score: float
    quote: str
    matched_text: str

    @property
    def is_strong(self) -> bool:
        return self.score >= STRONG

    @property
    def verdict(self) -> str:
        if self.score >= STRONG:
            return "verified"
        return "weak"

    def describe(self) -> str:
        return "page %d, %s (%.0f%%)" % (self.page, self.verdict, self.score * 100)


def locate(document: Document, quote: str, page_hint: Optional[int] = None) -> Optional[Citation]:
    """Find `quote` in `document`. Returns None if nothing matches above WEAK.

    `page_hint` is the page the model claimed. It is searched first and wins
    ties, but it is not trusted: a model that reads the right sentence and
    misnumbers the page should still get a citation, with the real page.
    """
    if not quote or not quote.strip():
        return None

    candidates: List[Citation] = []
    pages = document.pages
    if page_hint is not None:
        pages = sorted(pages, key=lambda p: (p.number != page_hint, p.number))

    for page in pages:
        found = _best_on_page(page, quote)
        if found is None:
            continue
        candidates.append(found)
        # An exact hit on the claimed page is as good as it gets; stop early.
        if found.score >= 0.999 and (page_hint is None or page.number == page_hint):
            return found

    if not candidates:
        return None

    best = max(candidates, key=lambda c: (round(c.score, 4), c.page == page_hint))
    return best if best.score >= WEAK else None


def locate_all(document: Document, quotes: List[str]) -> List[Optional[Citation]]:
    return [locate(document, q) for q in quotes]


def _best_on_page(page: Page, quote: str) -> Optional[Citation]:
    haystack, spans = page.normalized()
    needle = _norm(quote)
    if not haystack or not needle:
        return None

    # Exact first — cheap, and the common case for a model quoting properly.
    start = haystack.find(needle)
    if start != -1:
        return _build(page, spans, start, start + len(needle), 1.0, quote, needle)

    span = _best_window(haystack, needle)
    if span is None:
        return None
    start, end, score = span
    if score < WEAK:
        return None
    return _build(page, spans, start, end, score, quote, haystack[start:end])


def _best_window(haystack: str, needle: str) -> Optional[Tuple[int, int, float]]:
    """Align the quote against the page and score the window it lands on."""
    matcher = SequenceMatcher(None, haystack, needle, autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size > 0]
    if not blocks:
        return None

    best: Optional[Tuple[int, int, float]] = None
    # Anchor on the longest shared runs; a few candidates is enough and keeps
    # this linear in practice.
    for block in sorted(blocks, key=lambda b: b.size, reverse=True)[:5]:
        start = max(0, block.a - block.b)
        end = min(len(haystack), start + len(needle))
        if end <= start:
            continue
        score = SequenceMatcher(None, haystack[start:end], needle, autojunk=False).ratio()
        if best is None or score > best[2]:
            best = (start, end, score)
    return best


def _build(page: Page, spans, start: int, end: int, score: float,
           quote: str, matched: str) -> Optional[Citation]:
    covered = [
        word for word, (ws, we) in zip(page.words, spans)
        if we > start and ws < end and we > ws
    ]
    if not covered:
        return None
    return Citation(
        page=page.number,
        box=union(covered),
        score=round(score, 4),
        quote=quote,
        matched_text=matched,
    )


def _norm(value: str) -> str:
    swaps = {
        "’": "'", "‘": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", " ": " ", "−": "-",
    }
    for bad, good in swaps.items():
        value = value.replace(bad, good)
    return " ".join(value.lower().split())
