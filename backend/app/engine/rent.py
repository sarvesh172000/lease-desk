"""Rent escalation, including the kind that depends on the outside world.

Fixed percent and fixed step are arithmetic. CPI is not: the increase depends
on a published index, and the lease says exactly which one, measured when, with
what floor and cap. Getting any of those wrong produces a number that looks
reasonable and is wrong — which is why every CPI calculation here returns the
series, the two months, both index values and the raw ratio, so a controller
can check it against the BLS website in thirty seconds.

The traps the lease language creates, each of which this handles explicitly:

  - **The base month is not the commencement month.** Leases usually measure
    from a stated base, often a month or two before the term began.
  - **The lookback.** The index for a month is published weeks later, so a
    lease measures against the most recent month *available*, not the current
    one.
  - **Floor and cap.** "Not less than 2% nor more than 5%" is a collar, and a
    CPI move of 7% becomes 5%. A cap ignored is one of the planted errors.
  - **The index can fall.** Without a floor, a deflationary year means no
    increase — and a lease that says "not less than zero" is not the same as
    one that is silent.
"""

import csv
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

US_CITY_AVERAGE = "CUUR0000SA0"
WEST_REGION = "CUUR0400SA0"

# The repository's reference data; LEASEDESK_REFERENCE_DIR moves it. The image
# keeps it at /app/reference, because the generated data is mounted (or baked)
# at /app/data, where a reference copy would be hidden.
DEFAULT_SNAPSHOT = Path(os.environ.get("LEASEDESK_REFERENCE_DIR")
                        or Path(__file__).resolve().parents[3] / "data" / "reference") / "cpi_bls.csv"


class IndexUnavailable(LookupError):
    """The lease asks for a month the published series does not carry.

    Raised rather than approximated: substituting a nearby month silently
    changes the rent.
    """


@dataclass(frozen=True)
class CpiTerms:
    """The escalation clause, as the lease states it."""
    series_id: str = US_CITY_AVERAGE
    base_year: int = 2024
    base_month: int = 1
    # Months between the anniversary and the index month it is measured against.
    lookback_months: int = 2
    floor_pct: Optional[float] = None     # 0.02 for "not less than 2%"
    cap_pct: Optional[float] = None       # 0.05 for "not more than 5%"
    rounding: int = 2


@dataclass
class CpiResult:
    """An escalation, with everything needed to check it."""
    new_rent: float
    prior_rent: float
    applied_pct: float
    raw_pct: float
    series_id: str
    base: Tuple[int, int, float]       # year, month, index
    current: Tuple[int, int, float]
    adjustment: Optional[str] = None   # "floor" | "cap" | None

    @property
    def increase(self) -> float:
        return round(self.new_rent - self.prior_rent, 2)

    @property
    def was_collared(self) -> bool:
        return self.adjustment is not None

    def describe(self) -> str:
        detail = (
            "%s rose from %.3f (%d-%02d) to %.3f (%d-%02d), %.3f%%"
            % (self.series_id, self.base[2], self.base[0], self.base[1],
               self.current[2], self.current[0], self.current[1], self.raw_pct * 100)
        )
        if self.adjustment == "cap":
            return detail + ", capped at %.2f%% by the lease." % (self.applied_pct * 100)
        if self.adjustment == "floor":
            return detail + ", raised to the %.2f%% floor." % (self.applied_pct * 100)
        return detail + "."


class CpiSeries:
    """The published index, as snapshotted from BLS."""

    def __init__(self, values: Dict[Tuple[str, int, int], float],
                 source: str = "BLS Public Data API v2"):
        self._values = values
        self.source = source

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "CpiSeries":
        path = Path(path or DEFAULT_SNAPSHOT)
        values: Dict[Tuple[str, int, int], float] = {}
        with open(path) as fh:
            for row in csv.DictReader(fh):
                values[(row["series_id"], int(row["year"]), int(row["month"]))] = \
                    float(row["value"])
        return cls(values)

    def value(self, series_id: str, year: int, month: int) -> float:
        try:
            return self._values[(series_id, year, month)]
        except KeyError:
            raise IndexUnavailable(
                "%s has no published value for %d-%02d" % (series_id, year, month)
            ) from None

    def has(self, series_id: str, year: int, month: int) -> bool:
        return (series_id, year, month) in self._values

    def latest(self, series_id: str) -> Tuple[int, int, float]:
        keys = [k for k in self._values if k[0] == series_id]
        if not keys:
            raise IndexUnavailable("no values for %s" % series_id)
        year, month = max((k[1], k[2]) for k in keys)
        return year, month, self._values[(series_id, year, month)]


def escalate_cpi(prior_rent: float, anniversary: date, terms: CpiTerms,
                 series: CpiSeries) -> CpiResult:
    """The rent after a CPI escalation on `anniversary`."""
    measure_year, measure_month = _back(anniversary, terms.lookback_months)

    base_index = series.value(terms.series_id, terms.base_year, terms.base_month)
    current_index = series.value(terms.series_id, measure_year, measure_month)

    raw = (current_index - base_index) / base_index if base_index else 0.0
    applied, adjustment = _collar(raw, terms)

    return CpiResult(
        new_rent=round(prior_rent * (1 + applied), terms.rounding),
        prior_rent=round(prior_rent, 2),
        applied_pct=round(applied, 6),
        raw_pct=round(raw, 6),
        series_id=terms.series_id,
        base=(terms.base_year, terms.base_month, base_index),
        current=(measure_year, measure_month, current_index),
        adjustment=adjustment,
    )


def escalate(prior_rent: float, kind: str, amount: float,
             anniversary: Optional[date] = None,
             cpi_terms: Optional[CpiTerms] = None,
             series: Optional[CpiSeries] = None,
             rounding: int = 2) -> float:
    """One escalation, whichever kind the lease uses.

    The rounded figure is what escalates next time, because the lease raises
    "the Monthly Base Rent in effect" — the stated amount.
    """
    if kind == "fixed_percent":
        return round(round(prior_rent, rounding) * (1 + amount), rounding)
    if kind == "fixed_step":
        return round(round(prior_rent, rounding) + amount, rounding)
    if kind == "cpi":
        if anniversary is None or cpi_terms is None or series is None:
            raise ValueError("a CPI escalation needs an anniversary, terms and a series")
        return escalate_cpi(prior_rent, anniversary, cpi_terms, series).new_rent
    raise ValueError("unknown escalation kind %r" % kind)


def _collar(raw: float, terms: CpiTerms) -> Tuple[float, Optional[str]]:
    applied, adjustment = raw, None
    if terms.floor_pct is not None and applied < terms.floor_pct:
        applied, adjustment = terms.floor_pct, "floor"
    if terms.cap_pct is not None and applied > terms.cap_pct:
        applied, adjustment = terms.cap_pct, "cap"
    return applied, adjustment


def _back(when: date, months: int) -> Tuple[int, int]:
    month = when.month - 1 - months
    year = when.year + month // 12
    return year, month % 12 + 1
