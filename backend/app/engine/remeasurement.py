"""Remeasure a lease after an amendment and propose the adjusting entries.

Deterministic. The investigation decides *what changed*; this decides what it
costs, by handing the revised terms to the ASC 842 engine and reading back the
difference.

Operating lease, modification that is not a separate contract: the liability is
remeasured at the revised payments and rate, and the difference goes against
the ROU asset — no immediate P&L. Months already closed on the stale schedule
get a rent expense catch-up, because straight-line cost was booked at the old
figure.
"""

import json
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ProposedAmendment:
    """The revised terms an investigation concluded, before anyone approves."""
    effective: date
    new_base_rent: Optional[float] = None
    new_expiration: Optional[date] = None
    escalation_kind: str = "fixed_percent"
    escalation_amount: float = 0.0
    summary: str = ""


@dataclass
class Proposal:
    lease_id: str
    effective: date
    liability_before: float
    liability_after: float
    rou_before: float
    rou_after: float
    expense_catchup: float
    entries: List[Dict[str, float]] = field(default_factory=list)
    steps_before: List[Dict] = field(default_factory=list)
    steps_after: List[Dict] = field(default_factory=list)

    @property
    def liability_delta(self) -> float:
        return round(self.liability_after - self.liability_before, 2)

    @property
    def rou_delta(self) -> float:
        return round(self.rou_after - self.rou_before, 2)

    @property
    def total_debits(self) -> float:
        return round(sum(e["debit"] for e in self.entries), 2)

    @property
    def total_credits(self) -> float:
        return round(sum(e["credit"] for e in self.entries), 2)

    @property
    def balanced(self) -> bool:
        return abs(self.total_debits - self.total_credits) < 0.01

    def describe(self) -> str:
        return (
            "Lease liability %s by $%s, ROU asset by the same amount, "
            "plus a $%s rent expense catch-up."
            % ("rises" if self.liability_delta > 0 else "falls",
               "{:,.2f}".format(abs(self.liability_delta)),
               "{:,.2f}".format(abs(self.expense_catchup)))
        )


def propose(lease_payload: dict, amendment: ProposedAmendment,
            books_closed_through: date) -> Proposal:
    """What the amendment does to the books, as entries awaiting sign-off."""
    from leasedesk.models import load_lease
    from leasedesk.remeasure import remeasure

    amended = dict(lease_payload)
    amended["amendments"] = [{
        "amendment_id": "%s-AMD" % lease_payload["lease_id"],
        "effective": amendment.effective.isoformat(),
        "source": "investigation",
        "summary": amendment.summary,
        "new_end": (amendment.new_expiration or
                    date.fromisoformat(lease_payload["end"])).isoformat(),
        "new_steps": _steps(
            amendment.effective,
            amendment.new_expiration or date.fromisoformat(lease_payload["end"]),
            amendment.new_base_rent
            if amendment.new_base_rent is not None
            else _rent_at(lease_payload, amendment.effective),
            amendment.escalation_kind,
            amendment.escalation_amount,
        ),
    }]

    result = remeasure(load_lease(_tmp(amended)),
                       effective=amendment.effective,
                       through=books_closed_through)

    return Proposal(
        lease_id=lease_payload["lease_id"],
        effective=amendment.effective,
        liability_before=result.liability_before,
        liability_after=result.liability_after,
        rou_before=result.rou_before,
        rou_after=result.rou_after,
        expense_catchup=result.expense_catchup,
        entries=[{"account": line.account, "debit": line.debit, "credit": line.credit}
                 for line in result.entries],
        steps_before=list(lease_payload["steps"]),
        steps_after=amended["amendments"][0]["new_steps"],
    )


def _steps(start: date, end: date, rent: float, kind: str, amount: float) -> List[Dict]:
    out = []
    while start <= end:
        stop = min(_add_months(start, 12) - timedelta(days=1), end)
        rent = round(rent, 2)
        out.append({"start": start.isoformat(), "end": stop.isoformat(),
                    "monthly_rent": rent})
        start = stop + timedelta(days=1)
        # The lease escalates "the Monthly Base Rent in effect", which is the
        # stated figure — so round before compounding, not after. Compounding
        # the unrounded number drifts by cents over a long term.
        rent = rent * (1 + amount) if kind == "fixed_percent" else rent + amount
    return out


def _rent_at(payload: dict, period: date) -> float:
    for step in payload["steps"]:
        if date.fromisoformat(step["start"]) <= period <= date.fromisoformat(step["end"]):
            return float(step["monthly_rent"])
    return 0.0


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    last = 31 if month == 12 else (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))


def _tmp(payload: dict) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(payload, fh)
        return fh.name
