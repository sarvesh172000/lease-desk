"""Ingestion: source files into `source_document`, `raw_row` and `sync_cursor`.

Nothing is interpreted here. A CSV row is stored as the JSON it arrived as,
and a PDF as a pointer into the content-addressed store. Turning rows into
business records is `golden.py`'s job, so a bad standardization can always be
redone from the raw rows without re-fetching anything.

Ids are `md5(source | source_id)`, so re-ingesting the same file adds nothing.
This runs as `lease_agent`, which may insert here and nowhere in the ledger.
"""

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from ..db.models import raw_row, source_document, sync_cursor

PDF = "application/pdf"


class IngestError(ValueError):
    """The input is missing or malformed. Nothing from the run is kept."""


def stable_id(source: str, source_id: str) -> str:
    return hashlib.md5(("%s|%s" % (source, source_id)).encode()).hexdigest()


@dataclass(frozen=True)
class CsvSource:
    """One CSV export and how to name each of its rows stably."""
    source: str
    filename: str
    required: tuple
    row_key: Callable[[Dict[str, str], Dict[str, int]], str]


def _invoice_line(row: Dict[str, str], seen: Dict[str, int]) -> str:
    # AP exports have no line id. Lines are numbered within their invoice in
    # file order, matching the charge ids datagen gives them.
    seen[row["invoice_id"]] = seen.get(row["invoice_id"], 0) + 1
    return "%s-L%d" % (row["invoice_id"], seen[row["invoice_id"]])


def _payment(row: Dict[str, str], seen: Dict[str, int]) -> str:
    return row["payment_id"]


AP_COLUMNS = ("invoice_id", "vendor_id", "clinic_id", "lease_id", "period",
              "charge_type", "suite", "amount")
BANK_COLUMNS = ("payment_id", "lease_id", "clinic_id", "period", "charge_type",
                "amount", "paid_on")

CSV_SOURCES: List[CsvSource] = [
    CsvSource("ap_export", "ap_export.csv", AP_COLUMNS, _invoice_line),
    CsvSource("bank_export", "bank_export.csv", BANK_COLUMNS, _payment),
    CsvSource("ap_export", "history_2025_ap.csv", AP_COLUMNS, _invoice_line),
    CsvSource("bank_export", "history_2025_bank.csv", BANK_COLUMNS, _payment),
]


@dataclass
class IngestReport:
    documents: int = 0
    rows: int = 0
    by_source: Dict[str, int] = field(default_factory=dict)


def load_manifest(data_dir: Path) -> Dict:
    path = data_dir / "manifest.json"
    if not path.exists():
        raise IngestError("no manifest at %s; run `python -m datagen.build` first" % path)
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise IngestError("manifest %s is not valid JSON: %s" % (path, exc)) from exc


def ingest_documents(conn: Connection, manifest: Dict, report: IngestReport) -> None:
    rows = []
    for lease in manifest.get("leases", []):
        rows.append(_document("datagen.leases", lease["lease_id"], "lease",
                              lease["document_sha256"], lease.get("pages")))
    for invoice in manifest.get("invoices", []):
        rows.append(_document("datagen.invoices", invoice["invoice_id"], "invoice",
                              invoice["document_sha256"], invoice.get("pages")))
    if not rows:
        return
    conn.execute(insert(source_document).values(rows).on_conflict_do_nothing())
    report.documents += len(rows)


def ingest_csv(conn: Connection, data_dir: Path, spec: CsvSource, report: IngestReport) -> None:
    path = data_dir / spec.filename
    if not path.exists():
        raise IngestError("missing export %s" % path)
    raw = path.read_bytes()
    rows = list(_read_rows(path, raw, spec))
    if rows:
        conn.execute(insert(raw_row).values(rows).on_conflict_do_nothing())
    report.rows += len(rows)
    report.by_source[spec.filename] = len(rows)

    # The cursor records which version of the file was last taken in.
    cursor_source = "file:%s" % spec.filename
    digest = hashlib.sha256(raw).hexdigest()
    conn.execute(
        insert(sync_cursor).values(source=cursor_source, cursor=digest)
        .on_conflict_do_update(index_elements=["source"], set_={"cursor": digest}))


def ingest_all(conn: Connection, data_dir: Path) -> IngestReport:
    report = IngestReport()
    ingest_documents(conn, load_manifest(data_dir), report)
    for spec in CSV_SOURCES:
        ingest_csv(conn, data_dir, spec, report)
    return report


def _document(source: str, source_id: str, kind: str, sha: str, pages) -> Dict:
    if not isinstance(sha, str) or len(sha) != 64:
        raise IngestError("%s %s has no valid document_sha256" % (kind, source_id))
    return dict(id=stable_id(source, source_id), sha256=sha, source=source, kind=kind,
                mime=PDF, pages=pages, storage_key=sha)


def _read_rows(path: Path, raw: bytes, spec: CsvSource) -> Iterable[Dict]:
    reader = csv.DictReader(raw.decode("utf-8").splitlines())
    missing = [c for c in spec.required if c not in (reader.fieldnames or [])]
    if missing:
        raise IngestError("%s is missing column(s) %s" % (path.name, ", ".join(missing)))
    seen: Dict[str, int] = {}
    for line, row in enumerate(reader, start=2):
        blank = [c for c in spec.required if not (row.get(c) or "").strip()]
        if blank:
            raise IngestError("%s line %d: empty %s" % (path.name, line, ", ".join(blank)))
        source_id = spec.row_key(row, seen)
        yield dict(id=stable_id(spec.source, source_id), source=spec.source,
                   source_id=source_id, payload=row)
