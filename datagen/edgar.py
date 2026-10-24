"""Real leases, filed with the SEC, hand-labelled by reading them.

Everything else in `datagen` is a lease we wrote, so an extraction benchmark
built only on it is partly a test of our own prose. These are not. They have
the clause numbering, the defined terms, the thirty-page digressions and the
internal contradictions that real leases have.

Three of them, which is few — breadth comes from the synthetic corpus. What
these give is a check that the extractor has not simply learned how *we* write
a lease, which is why the eval scores them separately.

**The labels were produced by reading the exhibits, not by pattern-matching
them.** An earlier pass did pattern-match and produced labels that were wrong:
"renewal notice days" caught an insurance-cancellation notice, and "annual base
rent" lifted the monthly figure from the same sentence. A benchmark carrying
wrong labels is worse than one carrying none, because it scores a correct
extraction as a failure. Every value here carries the sentence it was read
from, so any label can be checked against the filed document.

Three things reading them turned up that writing a generator would never have:

  - **Two exhibits are the same lease.** Inuvo is the renamed FindWhat.com and
    both filings attach the identical Colonial Bank Plaza lease. Scoring both
    would double-weight one lease's quirks, so one is marked a duplicate and
    excluded.
  - **One lease carries two different proportionate shares** — 38.55% for taxes
    and insurance on total leasable area, 33.08% for CAM on ground-floor area.
    A system assuming one share per lease gets that lease wrong.
  - **One lease contradicts itself**, giving the premises as 32,820 rentable
    square feet in one sub-paragraph and 32,823 in the next.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

CORPUS = Path(__file__).resolve().parents[1] / "data" / "reference" / "edgar"
MANIFEST = CORPUS / "manifest.json"
LABELS = CORPUS.parent / "edgar_labels.json"

# The fields a lease abstractor is scored on here. Narrower than the synthetic
# schema, because these are what real exhibits actually state.
SCORED_FIELDS = (
    "term_years", "commencement", "rentable_sf", "building_rsf",
    "monthly_base_rent", "annual_base_rent", "escalation_kind",
    "escalation_amount", "pro_rata_share", "pro_rata_share_cam", "cam_present",
    "cam_cap", "management_fee_cap", "audit_window_days", "renewal_count",
    "renewal_years", "renewal_notice_days", "security_deposit",
)


@dataclass(frozen=True)
class Label:
    field: str
    value: Optional[str]
    quote: Optional[str]
    note: Optional[str] = None
    absent_reason: Optional[str] = None
    # True where the value is a normalised or computed form of what the quote
    # states — "0.03" for "Three (3%) percent" — rather than the words. Still
    # correct, but it tests inference rather than reading.
    derived: bool = False

    @property
    def is_absent(self) -> bool:
        return self.value is None

    @property
    def is_stated(self) -> bool:
        return not self.is_absent and not self.derived


@dataclass
class EdgarLease:
    doc_id: str
    company: str
    document: str
    cik: str
    form: str
    file_date: str
    url: str
    text: str
    labels: Dict[str, Label] = field(default_factory=dict)
    duplicate_of: Optional[str] = None

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of is not None

    @property
    def labelled(self) -> List[Label]:
        return [l for l in self.labels.values() if not l.is_absent]

    def label(self, name: str) -> Optional[Label]:
        return self.labels.get(name)

    def quote_is_in_text(self, name: str) -> bool:
        """Whether the label's supporting sentence really is in the filing."""
        label = self.labels.get(name)
        if label is None or not label.quote:
            return False
        return _flat(label.quote)[:60] in _flat(self.text)


def load_corpus(include_duplicates: bool = False) -> List[EdgarLease]:
    """The cached exhibits with their hand-written labels."""
    if not MANIFEST.exists() or not LABELS.exists():
        return []

    manifest = {d["id"]: d for d in json.loads(MANIFEST.read_text())["documents"]}
    labelled = json.loads(LABELS.read_text())["leases"]

    out: List[EdgarLease] = []
    for doc_id, entry in labelled.items():
        meta = manifest.get(doc_id)
        path = CORPUS / (doc_id + ".txt")
        if meta is None or not path.exists():
            continue
        if entry.get("duplicate_of") and not include_duplicates:
            continue

        out.append(EdgarLease(
            doc_id=doc_id,
            company=entry["company"],
            document=entry.get("document", ""),
            cik=meta["cik"], form=meta["form"], file_date=meta["file_date"],
            url=meta["url"], text=path.read_text(),
            duplicate_of=entry.get("duplicate_of"),
            labels={
                name: Label(name, spec.get("value"), spec.get("quote"),
                            spec.get("label_note"), spec.get("absent_reason"),
                            bool(spec.get("derived")))
                for name, spec in entry["fields"].items()
            },
        ))
    return out


def coverage(corpus: Optional[List[EdgarLease]] = None) -> Dict[str, int]:
    """How many of the real leases state each field at all.

    A field most exhibits do not state is not a field to score an extractor on.
    """
    corpus = corpus if corpus is not None else load_corpus()
    out = {name: 0 for name in SCORED_FIELDS}
    for lease in corpus:
        for name, label in lease.labels.items():
            if not label.is_absent:
                out[name] = out.get(name, 0) + 1
    return out


def score(extracted: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    """Score an extractor against the hand labels.

    `extracted` maps doc_id to {field: value}. Only fields the exhibit actually
    states are scored — claiming a value for a term the lease is silent on is
    counted separately as a fabrication, because inventing a number is a
    different failure from misreading one.
    """
    corpus = load_corpus()
    right = wrong = fabricated = missed = 0
    detail: Dict[str, Dict[str, str]] = {}

    for lease in corpus:
        got = extracted.get(lease.doc_id, {})
        per_lease: Dict[str, str] = {}
        for name, label in lease.labels.items():
            value = got.get(name)
            if label.is_absent:
                if value not in (None, ""):
                    fabricated += 1
                    per_lease[name] = "fabricated"
                continue
            if value in (None, ""):
                missed += 1
                per_lease[name] = "missed"
            elif _same(value, label.value):
                right += 1
                per_lease[name] = "right"
            else:
                wrong += 1
                per_lease[name] = "wrong"
        detail[lease.doc_id] = per_lease

    scorable = right + wrong + missed
    return {
        "leases": len(corpus),
        "right": right, "wrong": wrong, "missed": missed,
        "fabricated": fabricated,
        "scorable": scorable,
        "accuracy": round(right / scorable, 4) if scorable else 0.0,
        "detail": detail,
    }


def _same(got, expected) -> bool:
    a, b = str(got).strip().lower(), str(expected).strip().lower()
    if a == b:
        return True
    try:
        return abs(float(a.replace(",", "")) - float(b.replace(",", ""))) < 0.01
    except ValueError:
        return False


def _flat(text: str) -> str:
    return " ".join(text.split())
