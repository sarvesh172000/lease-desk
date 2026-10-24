"""Journal lines for charges a human approved.

Phase 1 posts rent and operating expense as period cost against accounts
payable. That is **a placeholder**, marked as one: the real ASC 842 treatment —
straight-line lease cost, liability accretion, ROU amortization — arrives with
the subledger in Phase 2, and these entries are superseded when it does.

Saying so in the entry type matters. An accountant who sees `Dr Lease cost,
Cr Accounts payable` on an operating lease and is not told it is provisional
will reasonably conclude the system does not know ASC 842.

Nothing here posts. The gateway posts, and only for items in APPROVED.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List

# Chart of accounts, per Phase 1 group 4.
LEASE_COST = "Lease cost"
CAM_EXPENSE = "CAM expense"
ACCOUNTS_PAYABLE = "Accounts payable"

PLACEHOLDER = "phase1_period_cost"

EXPENSE_ACCOUNT = {
    "base_rent": LEASE_COST,
    "cam_estimate": CAM_EXPENSE,
}


@dataclass(frozen=True)
class Line:
    account: str
    debit: float = 0.0
    credit: float = 0.0
    clinic_id: str = ""


@dataclass
class Entry:
    lease_id: str
    clinic_id: str
    period: date
    memo: str
    entry_type: str
    lines: List[Line] = field(default_factory=list)
    source_charge_ids: List[str] = field(default_factory=list)

    @property
    def total_debits(self) -> float:
        return round(sum(l.debit for l in self.lines), 2)

    @property
    def total_credits(self) -> float:
        return round(sum(l.credit for l in self.lines), 2)

    @property
    def balanced(self) -> bool:
        return abs(self.total_debits - self.total_credits) < 0.01

    @property
    def is_placeholder(self) -> bool:
        return self.entry_type == PLACEHOLDER

    def idempotency_key(self) -> str:
        """Posting the same month twice must not double the books."""
        return "%s|%s|%s|%s" % (
            self.lease_id, self.period.isoformat(), self.entry_type,
            ",".join(sorted(self.source_charge_ids)),
        )


def entries_for(findings: Iterable) -> List[Entry]:
    """One entry per approved charge. Held charges produce nothing.

    A charge under review has not been agreed with the landlord, so accruing it
    would put a number in the books that the next conversation may change.
    """
    entries: List[Entry] = []
    for finding in findings:
        if finding.proposal != "approve":
            continue
        charge = finding.charge
        account = EXPENSE_ACCOUNT.get(charge.charge_type)
        if account is None:
            continue
        entries.append(Entry(
            lease_id=charge.lease_id,
            clinic_id=charge.clinic_id,
            period=charge.period,
            memo="%s — %s %s" % (
                account, charge.clinic_id, charge.period.strftime("%B %Y")),
            entry_type=PLACEHOLDER,
            lines=[
                Line(account, debit=round(charge.amount, 2), clinic_id=charge.clinic_id),
                Line(ACCOUNTS_PAYABLE, credit=round(charge.amount, 2),
                     clinic_id=charge.clinic_id),
            ],
            source_charge_ids=[charge.charge_id],
        ))
    return entries


def totals_by_account(entries: Iterable[Entry]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for entry in entries:
        for line in entry.lines:
            out[line.account] = round(
                out.get(line.account, 0.0) + line.debit - line.credit, 2)
    return out


def all_balanced(entries: Iterable[Entry]) -> bool:
    return all(e.balanced for e in entries)
