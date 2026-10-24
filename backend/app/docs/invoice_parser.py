"""Read line items out of a landlord's statement, whatever shape it arrives in.

Three formats, one output. A PDF with a table, a letter with the amounts in
sentences, and a CSV export from a tenant portal with its own column names and
charge codes.

One rule runs through all three: **the line items must sum to the stated
total.** When they do not, the parse is wrong or the statement is — and either
way a human has to look, so a work item opens rather than a number quietly
entering the ledger. A parser that silently drops a line it could not read is
worse than one that fails loudly.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from .pipeline import Document, extract

FORMAT_TABLE = "pdf_table"
FORMAT_LETTER = "pdf_letter"
FORMAT_PORTAL = "portal_csv"

# The portal's charge codes, mapped once, here, where they can be seen.
PORTAL_CODES = {
    "RNT": "base_rent", "OPX": "cam_estimate", "RET": "property_tax",
    "INS": "insurance", "REC": "cam_reconciliation", "LTE": "late_fee",
    "CRD": "credit_memo",
}

# Phrases a letter uses for each charge type, in the order they are tried.
LETTER_PHRASES = [
    ("base_rent", re.compile(r"base rent[^.$]*?\$\s*([\d,]+\.\d{2})", re.I)),
    ("base_rent", re.compile(r"base rent of \$\s*([\d,]+\.\d{2})[^.]*?for (Suite|Unit) \S+", re.I)),
    ("cam_estimate", re.compile(r"operating expenses[^.$]*?\$\s*([\d,]+\.\d{2})", re.I)),
    ("property_tax", re.compile(r"(?:real property )?tax[^.$]*?\$\s*([\d,]+\.\d{2})", re.I)),
    ("insurance", re.compile(r"insurance[^.$]*?\$\s*([\d,]+\.\d{2})", re.I)),
]

_ALSO_BILLING = re.compile(
    r"billing \$\s*([\d,]+\.\d{2})\s+in respect of\s+([^.]+)", re.I)

TOTAL_PATTERNS = [
    re.compile(r"total amount now due is \$\s*([\d,]+\.\d{2})", re.I),
    re.compile(r"total due[^\d$]*\$?\s*([\d,]+\.\d{2})", re.I),
]

TOLERANCE = 0.01

# A statement is a page or two. Anything far larger is either not a statement
# or is meant to exhaust us, and either way it does not get parsed.
MAX_BYTES = 16 * 1024 * 1024


class UnreadableDocument(ValueError):
    """The bytes are not a document this parser can read.

    Raised rather than returning an empty result, because an empty parse is
    indistinguishable from a statement with no charges — and that one gets
    approved.
    """


@dataclass
class ParsedLine:
    charge_type: str
    description: str
    amount: float
    suite: Optional[str] = None
    page: Optional[int] = None
    raw: str = ""


@dataclass
class ParsedInvoice:
    invoice_id: Optional[str]
    source_format: str
    lines: List[ParsedLine] = field(default_factory=list)
    stated_total: Optional[float] = None
    issues: List[str] = field(default_factory=list)

    @property
    def line_total(self) -> float:
        return round(sum(l.amount for l in self.lines), 2)

    @property
    def foots(self) -> bool:
        """Do the line items sum to the total the statement states?"""
        if self.stated_total is None:
            return False
        return abs(self.line_total - self.stated_total) <= TOLERANCE

    @property
    def needs_review(self) -> bool:
        return bool(self.issues) or not self.foots

    def of(self, charge_type: str) -> Optional[ParsedLine]:
        for line in self.lines:
            if line.charge_type == charge_type:
                return line
        return None


def parse(data, source_format: Optional[str] = None,
          invoice_id: Optional[str] = None) -> ParsedInvoice:
    """Parse a statement. The format is detected unless given.

    Anything that is not a readable statement raises `UnreadableDocument`.
    Earlier this fell through to the CSV parser for *any* non-PDF bytes, so a
    corrupt PDF or a stray HTML page came back as a portal export with zero
    line items and no total — which reads exactly like a statement that
    charges nothing.
    """
    if data is None:
        raise UnreadableDocument("no document supplied")
    if len(data) > MAX_BYTES:
        raise UnreadableDocument(
            "document is %.1f MB; the limit is %d MB"
            % (len(data) / 1e6, MAX_BYTES // (1024 * 1024)))

    if isinstance(data, bytes):
        if data[:4] == b"%PDF":
            try:
                document = extract(data)
            except Exception as exc:
                raise UnreadableDocument("the PDF could not be opened: %s" % exc) from exc
            if not document.pages:
                raise UnreadableDocument("the PDF has no pages")
            detected = source_format or _detect_pdf(document)
            return (_parse_table(document, invoice_id) if detected == FORMAT_TABLE
                    else _parse_letter(document, invoice_id))

        if data[:5].lower() in (b"<html", b"<!doc") or b"\x00" in data[:1024]:
            raise UnreadableDocument(
                "not a statement: the bytes look like %s"
                % ("HTML" if data[:1].lower() == b"<" else "binary data"))
        data = data.decode("utf-8", "replace")

    if not data.strip():
        raise UnreadableDocument("the document is empty")
    return _parse_portal(data, invoice_id)


def _detect_pdf(document: Document) -> str:
    text = document.pages[0].text.lower()
    if "invoice" in text and "description" in text and "amount" in text:
        return FORMAT_TABLE
    return FORMAT_LETTER


# --- format A: the PDF table ----------------------------------------------

_AMOUNT_ONLY = re.compile(r"^\$\s*([\d,]+\.\d{2})$")
_SUITE = re.compile(r"^(Suite|Unit)\s+\S+$", re.I)
_TABLE_HEADER = ("description", "suite", "period", "amount")


def _parse_table(document: Document, invoice_id) -> ParsedInvoice:
    """Read the table.

    A PDF table does not come out of extraction as rows. Each cell is its own
    line, in reading order, so a row is a run of lines ending in an amount —
    not a single line a regex can match. Grouping on the amount is what makes
    this robust to a description that wraps onto two lines.
    """
    result = ParsedInvoice(invoice_id, FORMAT_TABLE)
    text = "\n".join(p.text for p in document.pages)
    lines = [l.strip() for l in text.splitlines()]

    start = _header_index(lines)
    if start is None:
        result.issues.append("no line-item table found")
        result.stated_total = _find_total(text)
        _flag(result)
        return result

    cells: List[str] = []
    for line in lines[start:]:
        if not line:
            continue
        if line.upper().startswith("TOTAL"):
            break

        match = _AMOUNT_ONLY.match(line)
        if not match:
            cells.append(line)
            continue

        # The amount closes a row. Everything gathered since the last one is
        # the description, the suite and the period, in that order.
        description = " ".join(c for c in cells
                               if not _SUITE.match(c) and not _is_period(c)).strip()
        suite = next((c for c in cells if _SUITE.match(c)), None)
        if description:
            result.lines.append(ParsedLine(
                charge_type=_classify(description),
                description=description,
                amount=_number(match.group(1)),
                suite=suite,
                page=1,
                raw=" | ".join(cells + [line]),
            ))
        cells = []

    result.stated_total = _find_total(text)
    result.invoice_id = invoice_id or _find_invoice_id(text)
    _flag(result)
    return result


def _header_index(lines: List[str]) -> Optional[int]:
    lowered = [l.lower() for l in lines]
    for index in range(len(lowered) - len(_TABLE_HEADER) + 1):
        if tuple(lowered[index:index + len(_TABLE_HEADER)]) == _TABLE_HEADER:
            return index + len(_TABLE_HEADER)
    return None


def _is_period(cell: str) -> bool:
    return bool(re.match(r"^[A-Z][a-z]+ \d{4}$", cell))


# --- format B: the letter --------------------------------------------------

def _parse_letter(document: Document, invoice_id) -> ParsedInvoice:
    """Read the amounts out of the prose.

    Two traps here, both of which produced a wrong parse before the footing
    check caught them. A statement with a single charge states the same figure
    as the line and as the total, so excluding anything equal to the total
    loses the only line — the total sentence has to be removed by *position*,
    not by value. And a letter can mention the same charge type twice, as it
    does when a landlord bills rent for a suite we do not lease, so each
    pattern is scanned for every occurrence rather than the first.
    """
    result = ParsedInvoice(invoice_id, FORMAT_LETTER)
    text = " ".join(" ".join(p.text.split()) for p in document.pages)

    total, body = _split_off_total(text)

    seen = set()
    for charge_type, pattern in LETTER_PHRASES:
        for match in pattern.finditer(body):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in seen):
                continue
            seen.add(span)
            result.lines.append(ParsedLine(
                charge_type=charge_type,
                description=match.group(0).strip()[:90],
                amount=_number(match.group(1)),
                raw=match.group(0).strip(),
            ))

    # Anything the landlord described loosely — "we are also billing $X in
    # respect of ..." — that the typed patterns did not already claim.
    for match in _ALSO_BILLING.finditer(body):
        span = match.span()
        if any(span[0] < end and start < span[1] for start, end in seen):
            continue
        seen.add(span)
        result.lines.append(ParsedLine(
            charge_type=_classify(match.group(2)),
            description=match.group(0).strip()[:90],
            amount=_number(match.group(1)),
            raw=match.group(0).strip(),
        ))

    result.lines.sort(key=lambda l: -l.amount)
    result.stated_total = total
    result.invoice_id = invoice_id or _find_invoice_id(text)
    _flag(result)
    return result


def _split_off_total(text: str):
    """The stated total, and the text with that sentence removed.

    Removing it by position rather than filtering on the value is what lets a
    single-charge statement parse, where the line and the total are the same
    number.
    """
    for pattern in TOTAL_PATTERNS:
        match = pattern.search(text)
        if match:
            return _number(match.group(1)), text[:match.start()] + " " + text[match.end():]
    return None, text


# --- format C: the portal CSV ---------------------------------------------

def _parse_portal(text: str, invoice_id) -> ParsedInvoice:
    result = ParsedInvoice(invoice_id, FORMAT_PORTAL)
    rows = list(csv.DictReader(io.StringIO(text)))

    for row in rows:
        code = (row.get("ChargeCode") or "").strip().upper()
        amount = _number(row.get("ChargeAmt") or "0")
        if code == "TOT":
            # A total row that looks like a line item. It is not one.
            result.stated_total = amount
            continue
        if code not in PORTAL_CODES:
            result.issues.append("unknown charge code %r" % code)
            continue
        suite = (row.get("UnitRef") or "").strip()
        result.lines.append(ParsedLine(
            charge_type=PORTAL_CODES[code],
            description=(row.get("ChargeDesc") or "").strip(),
            amount=amount,
            suite="Suite %s" % suite if suite else None,
            raw=",".join(row.values()),
        ))
        result.invoice_id = result.invoice_id or (row.get("DocNo") or "").strip() or None

    _flag(result)
    return result


# --- shared ----------------------------------------------------------------

def _flag(result: ParsedInvoice) -> None:
    if not result.lines:
        result.issues.append("no line items could be read")
    if result.stated_total is None:
        result.issues.append("no stated total found, so the parse cannot be checked")
    elif not result.foots:
        result.issues.append(
            "line items sum to $%s but the statement states $%s"
            % (_money(result.line_total), _money(result.stated_total)))


def _classify(description: str) -> str:
    lowered = description.lower()
    if "base rent" in lowered or lowered.startswith("rent"):
        return "base_rent"
    if "operating expense" in lowered or "cam" in lowered:
        return "cam_estimate"
    if "tax" in lowered:
        return "property_tax"
    if "insurance" in lowered:
        return "insurance"
    if "reconcil" in lowered:
        return "cam_reconciliation"
    if "late" in lowered:
        return "late_fee"
    if "credit" in lowered:
        return "credit_memo"
    return "other"


def _find_total(text: str) -> Optional[float]:
    for pattern in TOTAL_PATTERNS:
        match = pattern.search(text)
        if match:
            return _number(match.group(1))
    return None


def _find_invoice_id(text: str) -> Optional[str]:
    match = re.search(r"\b([A-Z]{4,6}-\d{6}(?:-[A-Z0-9]+)*(?:-\d{4})?)\b", text)
    return match.group(1) if match else None


def _number(value: str) -> float:
    return round(float(str(value).replace(",", "").replace("$", "").strip() or 0), 2)


def _money(v: float) -> str:
    return "{:,.2f}".format(v)
