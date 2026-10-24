"""Core lease data model.

Everything downstream (schedules, reconciliation, journal entries) is derived
from these objects, so extraction only ever has to produce a `Lease`.
"""

from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import List, Optional
import json


@dataclass
class RentStep:
    """A block of months at a fixed monthly rent."""

    start: date
    end: date
    monthly_rent: float

    def months(self) -> int:
        return (self.end.year - self.start.year) * 12 + (self.end.month - self.start.month) + 1


@dataclass
class Amendment:
    """A change to a lease, discovered after the original abstraction."""

    amendment_id: str
    effective: date
    source: str
    summary: str
    new_end: Optional[date] = None
    new_steps: List[RentStep] = field(default_factory=list)
    new_discount_rate: Optional[float] = None


@dataclass
class Lease:
    lease_id: str
    location: str
    lessor: str
    commencement: date
    end: date
    discount_rate: float  # annual incremental borrowing rate, e.g. 0.072
    steps: List[RentStep]
    classification: str = "operating"
    prepaid: float = 0.0
    incentives: float = 0.0
    amendments: List[Amendment] = field(default_factory=list)

    def term_months(self) -> int:
        return (self.end.year - self.commencement.year) * 12 + (self.end.month - self.commencement.month) + 1

    def rent_for(self, period: date) -> float:
        """Contractual rent owed for the month containing `period`."""
        for step in self.steps:
            if step.start <= period <= step.end:
                return step.monthly_rent
        return 0.0

    def as_of(self, when: date) -> "Lease":
        """Apply every amendment effective on or before `when`."""
        lease = Lease(**{**asdict_shallow(self), "amendments": []})
        for amd in sorted(self.amendments, key=lambda a: a.effective):
            if amd.effective > when:
                continue
            lease = _apply(lease, amd)
            lease.amendments.append(amd)
        return lease


def asdict_shallow(lease: "Lease") -> dict:
    return {
        "lease_id": lease.lease_id,
        "location": lease.location,
        "lessor": lease.lessor,
        "commencement": lease.commencement,
        "end": lease.end,
        "discount_rate": lease.discount_rate,
        "steps": list(lease.steps),
        "classification": lease.classification,
        "prepaid": lease.prepaid,
        "incentives": lease.incentives,
    }


def _apply(lease: Lease, amd: Amendment) -> Lease:
    if amd.new_end:
        lease.end = amd.new_end
    if amd.new_discount_rate is not None:
        lease.discount_rate = amd.new_discount_rate
    if amd.new_steps:
        # Keep history before the amendment, replace everything from there on.
        kept = [s for s in lease.steps if s.end < amd.effective]
        tail = [s for s in lease.steps if s.start < amd.effective <= s.end]
        for s in tail:
            kept.append(RentStep(s.start, _prev_month_end(amd.effective), s.monthly_rent))
        lease.steps = kept + list(amd.new_steps)
    return lease


def _prev_month_end(d: date) -> date:
    """Last day of the month before the one containing `d`."""
    first_of_month = date(d.year, d.month, 1)
    return first_of_month - timedelta(days=1)


def load_lease(path: str) -> Lease:
    with open(path) as fh:
        raw = json.load(fh)
    return from_dict(raw)


def from_dict(raw: dict) -> Lease:
    steps = [RentStep(_d(s["start"]), _d(s["end"]), float(s["monthly_rent"])) for s in raw["steps"]]
    amendments = []
    for a in raw.get("amendments", []):
        amendments.append(
            Amendment(
                amendment_id=a["amendment_id"],
                effective=_d(a["effective"]),
                source=a.get("source", ""),
                summary=a.get("summary", ""),
                new_end=_d(a["new_end"]) if a.get("new_end") else None,
                new_steps=[
                    RentStep(_d(s["start"]), _d(s["end"]), float(s["monthly_rent"]))
                    for s in a.get("new_steps", [])
                ],
                new_discount_rate=a.get("new_discount_rate"),
            )
        )
    return Lease(
        lease_id=raw["lease_id"],
        location=raw["location"],
        lessor=raw["lessor"],
        commencement=_d(raw["commencement"]),
        end=_d(raw["end"]),
        discount_rate=float(raw["discount_rate"]),
        steps=steps,
        classification=raw.get("classification", "operating"),
        prepaid=float(raw.get("prepaid", 0.0)),
        incentives=float(raw.get("incentives", 0.0)),
        amendments=amendments,
    )


def _d(value: str) -> date:
    return date.fromisoformat(value)
