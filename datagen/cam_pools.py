"""What a landlord actually spends on a building, and bills back.

Operating expenses are where lease accounting gets genuinely hard, and where
the money is. Rent is one number on a schedule; CAM is a pool of vendor
invoices allocated across tenants, and every step of that allocation is a place
to be overcharged:

  - a **capital** item passed through as an operating expense,
  - a **management fee** above the cap the lease sets,
  - a **controllable** category rising faster than the lease allows,
  - a share computed on the wrong **denominator**,
  - and the one that only shows up across clinics: **the same vendor line
    billed in full to two tenants in the same center**.

That last case is why Serramonte Medical Plaza holds two Northbay suites. The
parking lot repaving below is charged at 100% to both, so neither invoice looks
wrong on its own. Only looking across the center finds it.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Categories the lease treats as outside the controllable cap.
NON_CONTROLLABLE = {"property_tax", "insurance", "utilities", "snow_removal"}
CAPITAL = "capital"


@dataclass(frozen=True)
class PoolLine:
    """One vendor invoice in a center's annual operating expense pool."""
    line_id: str
    center_id: str
    year: int
    category: str
    vendor: str
    invoice_ref: str
    amount: float
    # True where the lease's exclusions clause puts this outside recoverable
    # operating expenses entirely.
    excluded: bool = False
    exclusion_reason: str = ""
    # Clinics the landlord billed this to in full, rather than pro rata.
    billed_in_full_to: List[str] = field(default_factory=list)

    @property
    def controllable(self) -> bool:
        return self.category not in NON_CONTROLLABLE and not self.excluded


@dataclass
class Pool:
    center_id: str
    year: int
    lines: List[PoolLine]

    def total(self, include_excluded: bool = True) -> float:
        return round(sum(l.amount for l in self.lines
                         if include_excluded or not l.excluded), 2)

    def recoverable(self) -> float:
        return round(sum(l.amount for l in self.lines if not l.excluded), 2)

    def controllable(self) -> float:
        return round(sum(l.amount for l in self.lines if l.controllable), 2)

    def by_category(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for line in self.lines:
            out[line.category] = round(out.get(line.category, 0.0) + line.amount, 2)
        return out

    def excluded_lines(self) -> List[PoolLine]:
        return [l for l in self.lines if l.excluded]

    def double_billed(self) -> List[PoolLine]:
        return [l for l in self.lines if len(l.billed_in_full_to) > 1]


# Per-category annual spend as a fraction of a center's rentable area, in
# dollars per square foot. Deterministic, and in the range these actually run.
_PSF_BY_CATEGORY = {
    "janitorial": 1.85,
    "landscaping": 0.62,
    "security": 1.10,
    "utilities": 2.35,
    "repairs": 1.28,
    "property_tax": 2.90,
    "insurance": 0.95,
    "management_fee": 0.88,
}

_VENDORS = {
    "janitorial": "Meridian Facility Services",
    "landscaping": "Valleycrest Grounds Care",
    "security": "Sentinel Protective Group",
    "utilities": "Pacific Gas & Electric",
    "repairs": "Brightline Building Maintenance",
    "property_tax": "County Assessor",
    "insurance": "Carrington Commercial Insurance",
    "management_fee": "(landlord)",
}


def build_pool(center, year: int = 2025, clinics_in_center: Optional[List[str]] = None) -> Pool:
    """A center's operating expense pool for one year."""
    lines: List[PoolLine] = []
    for index, (category, psf) in enumerate(sorted(_PSF_BY_CATEGORY.items()), start=1):
        lines.append(PoolLine(
            line_id="%s-%d-%02d" % (center.center_id, year, index),
            center_id=center.center_id,
            year=year,
            category=category,
            vendor=_VENDORS[category],
            invoice_ref="%s-%d-%s" % (center.center_id[-5:], year, category[:4].upper()),
            amount=round(center.total_rsf * psf, 2),
        ))

    lines.extend(_planted(center, year, clinics_in_center or []))
    return Pool(center.center_id, year, lines)


def _planted(center, year: int, clinics: List[str]) -> List[PoolLine]:
    """The lines that are wrong, and the one that is only wrong across clinics."""
    out: List[PoolLine] = []

    # A capital item the exclusions clause puts outside operating expenses —
    # and the landlord billed it in full to every Northbay suite in the center.
    if center.center_id == "CTR-SERRA" and len(clinics) > 1:
        out.append(PoolLine(
            line_id="%s-%d-PARKING" % (center.center_id, year),
            center_id=center.center_id,
            year=year,
            category=CAPITAL,
            vendor="Granite State Paving LLC",
            invoice_ref="GSP-%d-4471" % year,
            amount=84_600.00,
            excluded=True,
            exclusion_reason=(
                "Section 4.3(a): capital improvements and capital replacements "
                "are excluded from Operating Expenses"),
            billed_in_full_to=list(clinics),
        ))

    return out


def build_pools(company, year: int = 2025) -> Dict[str, Pool]:
    return {
        center.center_id: build_pool(
            center, year, [c.clinic_id for c in company.clinics_in(center.center_id)])
        for center in company.centers
    }
