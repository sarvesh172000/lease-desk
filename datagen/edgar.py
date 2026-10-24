"""Real leases, filed with the SEC.

Everything else in `datagen` is a lease we wrote, which means the extraction
benchmark is partly a test of our own prose. These are not: they are exhibits
companies actually filed, with the clause numbering, the capitalisation, the
defined terms and the thirty-page digressions that real leases have.

They are small in number and that is the point — the synthetic corpus gives
breadth, these give a check that the extractor has not simply learned how *we*
write a lease. The eval scores them separately for the same reason.

Each label carries the sentence that supports it, located in the filed text, so
a label can be checked rather than taken on trust. Where a term genuinely is
not stated in an exhibit, it is recorded as absent rather than guessed: a
benchmark that invents an answer measures nothing.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

CORPUS = Path(__file__).resolve().parents[1] / "data" / "reference" / "edgar"
MANIFEST = CORPUS / "manifest.json"


@dataclass(frozen=True)
class Label:
    """One field of one real lease, with the sentence that states it."""
    field: str
    value: Optional[str]
    quote: Optional[str]

    @property
    def is_absent(self) -> bool:
        return self.value is None


@dataclass
class EdgarLease:
    doc_id: str
    company: str
    cik: str
    form: str
    file_date: str
    url: str
    text: str
    labels: Dict[str, Label] = field(default_factory=dict)

    @property
    def labelled(self) -> List[Label]:
        return [l for l in self.labels.values() if not l.is_absent]

    def label(self, name: str) -> Optional[Label]:
        return self.labels.get(name)


# Patterns that locate a field's supporting sentence in a real exhibit.
#
# Deliberately few. A first pass matched more fields and two of them were
# WRONG: "renewal notice days" caught an insurance-cancellation notice, and
# "annual base rent" picked up the monthly figure from the same sentence. A
# benchmark carrying wrong labels is worse than one carrying none, because it
# scores a correct extraction as a failure and sends you chasing it.
#
# What survives is only what the supporting quote actually proves. The rest is
# recorded as unlabelled and listed in NEEDS_HUMAN_LABEL — reading a
# ninety-page exhibit properly is a person's job, and pretending otherwise
# would make the EDGAR score meaningless.
_PATTERNS = {
    "monthly_base_rent": (
        r"[^.]{0,120}(?:equal )?monthly installments? of \$\s*([\d,]+(?:\.\d{2})?)[^.]{0,60}\.",
        r"[^.]{0,120}monthly (?:base )?rent (?:of|shall be) \$\s*([\d,]+(?:\.\d{2})?)[^.]{0,60}\.",
    ),
    "cam_present": (
        r"[^.]{0,120}[Cc]ommon [Aa]rea [Mm]aintenance[^.]{0,100}\.",
    ),
}

# Fields a person has to label by reading. Listed, not guessed.
NEEDS_HUMAN_LABEL = (
    "commencement", "expiration", "rentable_sf", "annual_base_rent",
    "escalation_kind", "escalation_amount", "pro_rata_share",
    "cam_cap", "cam_exclusions", "management_fee_cap", "audit_window",
    "renewal_count", "renewal_notice_days", "security_deposit",
)


def load_corpus() -> List[EdgarLease]:
    """The cached exhibits, with their labels located in the filed text."""
    if not MANIFEST.exists():
        return []
    manifest = json.loads(MANIFEST.read_text())

    out: List[EdgarLease] = []
    for entry in manifest["documents"]:
        path = CORPUS / (entry["id"] + ".txt")
        if not path.exists():
            continue
        lease = EdgarLease(
            doc_id=entry["id"], company=entry["company"], cik=entry["cik"],
            form=entry["form"], file_date=entry["file_date"], url=entry["url"],
            text=path.read_text(),
        )
        lease.labels = _label(lease.text)
        out.append(lease)
    return out


def _label(text: str) -> Dict[str, Label]:
    flat = " ".join(text.split())
    labels: Dict[str, Label] = {}

    for name, patterns in _PATTERNS.items():
        found = None
        for pattern in patterns:
            match = re.search(pattern, flat)
            if match:
                value = match.group(1) if match.groups() else "yes"
                found = Label(name, value.strip(), match.group(0).strip()[:260])
                break
        labels[name] = found or Label(name, None, None)

    return labels


def coverage(corpus: Optional[List[EdgarLease]] = None) -> Dict[str, int]:
    """How many of the real leases state each field at all.

    A field most exhibits do not state is not a field the extractor should be
    scored on.
    """
    corpus = corpus if corpus is not None else load_corpus()
    out: Dict[str, int] = {}
    for lease in corpus:
        for name, label in lease.labels.items():
            out[name] = out.get(name, 0) + (0 if label.is_absent else 1)
    return out


def write_labels(path: Optional[Path] = None) -> Path:
    """Persist the labels for the eval to score against."""
    corpus = load_corpus()
    payload = {
        "source": "SEC EDGAR",
        "note": ("Labels located in the filed text, each carrying the sentence "
                 "that supports it. Only fields whose quote actually proves the "
                 "value are labelled; the rest need a person to read the "
                 "exhibit and are listed in needs_human_label."),
        "needs_human_label": list(NEEDS_HUMAN_LABEL),
        "leases": {
            lease.doc_id: {
                "company": lease.company,
                "cik": lease.cik,
                "form": lease.form,
                "file_date": lease.file_date,
                "url": lease.url,
                "fields": {
                    name: {"value": label.value, "quote": label.quote}
                    for name, label in lease.labels.items()
                },
            }
            for lease in corpus
        },
    }
    out = Path(path or (CORPUS.parent / "edgar_labels.json"))
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return out
