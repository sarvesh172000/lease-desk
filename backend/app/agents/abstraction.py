"""Read a lease PDF into structured terms, with every term cited.

The model's only job here is reading. It returns a value, the page it read it
from, and the verbatim sentence that states it — nothing else. The schedule,
the liability and the entries are all computed downstream by `engine/`, from
these terms, in ordinary arithmetic.

Every returned field is then checked against the page it claims to come from.
That check is what separates a term a human can verify at a glance from one
they would have to re-read the lease to trust:

  - **Verified** — the quote is on the page, boxed, score at or above 0.92.
  - **Weak** — something matched, but not closely. Flagged, confidence drops.
  - **Uncited** — nothing on any page matches. The value is not usable as-is
    and the field is routed to a human.

A model that invents a plausible number but cannot produce a sentence that
supports it gets caught here, before the number reaches a schedule.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ..docs.citations import STRONG, Citation, locate
from ..docs.pipeline import Document
from ..llm.client import LLM, RunMeta

PROMPT_ID = "lease_abstraction"


# --- what the model returns ------------------------------------------------

class CitedText(BaseModel):
    value: str
    page: int = Field(description="1-based page the value was read from")
    quote: str = Field(description="Verbatim sentence from that page, copied exactly")


class CitedNumber(BaseModel):
    value: float
    page: int
    quote: str


class CitedDate(BaseModel):
    value: str = Field(description="ISO date, YYYY-MM-DD")
    page: int
    quote: str


class AbstractedLease(BaseModel):
    commencement: CitedDate
    expiration: CitedDate
    rentable_sf: CitedNumber
    proportionate_share_pct: CitedNumber
    base_rent_monthly: CitedNumber
    escalation_kind: CitedText = Field(
        description='Exactly "fixed_percent" or "fixed_step"')
    escalation_amount: CitedNumber = Field(
        description="0.03 for 3% per annum, or 275.00 for a $275 step")
    cam_estimate_psf_annual: CitedNumber
    security_deposit: CitedNumber
    renewal_count: CitedNumber
    renewal_years: CitedNumber
    renewal_notice_days: CitedNumber
    authorized_representative: CitedText = Field(
        description="The person the notices clause names as authorized to bind the landlord")
    uncertain: List[str] = Field(
        default_factory=list,
        description="Terms the lease does not state clearly. These go to a human.")


CITED_FIELDS: Tuple[str, ...] = (
    "commencement", "expiration", "rentable_sf", "proportionate_share_pct",
    "base_rent_monthly", "escalation_kind", "escalation_amount",
    "cam_estimate_psf_annual", "security_deposit", "renewal_count",
    "renewal_years", "renewal_notice_days", "authorized_representative",
)


# --- what this module returns ----------------------------------------------

@dataclass(frozen=True)
class CheckedField:
    name: str
    value: object
    claimed_page: int
    quote: str
    citation: Optional[Citation]

    @property
    def status(self) -> str:
        if self.citation is None:
            return "uncited"
        if self.citation.score < STRONG:
            return "weak"
        return "verified"

    @property
    def page_matches(self) -> bool:
        return self.citation is not None and self.citation.page == self.claimed_page


@dataclass
class Abstraction:
    lease_id: str
    fields: List[CheckedField]
    uncertain: List[str]
    confidence: float
    flags: List[str] = field(default_factory=list)
    meta: Optional[RunMeta] = None

    def field(self, name: str) -> CheckedField:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(name)

    def value(self, name: str):
        return self.field(name).value

    @property
    def verified(self) -> List[CheckedField]:
        return [f for f in self.fields if f.status == "verified"]

    @property
    def needs_review(self) -> List[CheckedField]:
        return [f for f in self.fields if f.status != "verified"]

    @property
    def is_usable(self) -> bool:
        """Every field verified and nothing the model flagged as unclear.

        An unusable abstraction is not an error — it is a lease that a human
        confirms before the checker is allowed to run against it.
        """
        return not self.needs_review and not self.uncertain


    def to_engine_json(self, location: str, lessor: str, discount_rate: float) -> dict:
        """The abstraction as input to `engine/`.

        Only call this on a usable abstraction, or after a human has confirmed
        the fields that needed review — the whole point of the citation check
        is that an unverified term never reaches a schedule.
        """
        start = self.value("commencement")
        end = self.value("expiration")
        kind = str(self.value("escalation_kind"))
        amount = float(self.value("escalation_amount"))

        steps, rent, cursor = [], float(self.value("base_rent_monthly")), start
        while cursor <= end:
            stop = min(_add_months(cursor, 12) - timedelta(days=1), end)
            rent = round(rent, 2)
            steps.append({
                "start": cursor.isoformat(),
                "end": stop.isoformat(),
                "monthly_rent": rent,
            })
            cursor = stop + timedelta(days=1)
            # Escalate the stated figure, not the unrounded one — see
            # engine/remeasurement.py for why.
            rent = rent * (1 + amount) if kind == "fixed_percent" else rent + amount

        return {
            "lease_id": self.lease_id,
            "location": location,
            "lessor": lessor,
            "commencement": start.isoformat(),
            "end": end.isoformat(),
            "discount_rate": discount_rate,
            "classification": "operating",
            "prepaid": 0.0,
            "incentives": 0.0,
            "steps": steps,
            "amendments": [],
        }


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    if month == 12:
        last = 31
    else:
        last = (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))


def abstract_lease(
    document: Document,
    llm: LLM,
    lease_id: str,
    company: str = "Northbay Physical Therapy",
    source: str = "lease.pdf",
) -> Abstraction:
    extracted, meta = llm.structured(
        PROMPT_ID,
        AbstractedLease,
        variables={"company": company},
        documents=[(source, document.numbered_text())],
    )
    return check(extracted, document, lease_id, meta)


def check(
    extracted: AbstractedLease,
    document: Document,
    lease_id: str,
    meta: Optional[RunMeta] = None,
) -> Abstraction:
    """Verify every quote against the page it claims to come from."""
    fields: List[CheckedField] = []
    flags: List[str] = []

    for name in CITED_FIELDS:
        cited = getattr(extracted, name)
        citation = locate(document, cited.quote, page_hint=cited.page)
        checked = CheckedField(
            name=name,
            value=_coerce(name, cited.value),
            claimed_page=cited.page,
            quote=cited.quote,
            citation=citation,
        )
        fields.append(checked)

        if checked.status == "uncited":
            flags.append("%s: no sentence on any page matches the quote" % name)
        elif checked.status == "weak":
            flags.append("%s: quote only partially matches page %d (%.0f%%)"
                         % (name, citation.page, citation.score * 100))
        elif not checked.page_matches:
            flags.append("%s: quote is on page %d, not page %d as claimed"
                         % (name, citation.page, checked.claimed_page))

    for note in extracted.uncertain:
        flags.append("model unsure: %s" % note)

    return Abstraction(
        lease_id=lease_id,
        fields=fields,
        uncertain=list(extracted.uncertain),
        confidence=confidence(fields, extracted.uncertain),
        flags=flags,
        meta=meta,
    )


def confidence(fields: List[CheckedField], uncertain: List[str]) -> float:
    """How much of this abstraction is backed by the document.

    Mean citation score across every field, so an uncited field costs its whole
    share rather than being quietly skipped, then a flat penalty per term the
    model itself said it could not pin down. Stated here rather than tuned,
    because a confidence nobody can explain is worse than none.
    """
    if not fields:
        return 0.0
    total = sum(f.citation.score if f.citation else 0.0 for f in fields)
    score = total / len(fields)
    score *= max(0.0, 1.0 - 0.05 * len(uncertain))
    return round(max(0.0, min(1.0, score)), 4)


def _coerce(name: str, value):
    """Dates to `date`, counts to `int`, everything else as returned."""
    if name in ("commencement", "expiration"):
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return value
    if name in ("renewal_count", "renewal_years", "renewal_notice_days", "rentable_sf"):
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return value
    return value
