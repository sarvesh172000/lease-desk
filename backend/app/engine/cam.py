"""What a clinic actually owes in operating expenses. Deterministic, no model.

The landlord sends a statement. This computes what the lease supports, line by
line, in the order the lease itself sets out:

  1. **Exclusions** — a capital item, a leasing commission, a cost another
     tenant reimbursed. Removed from the pool before anything else.
  2. **Management fee cap** — a percentage of gross receipts, not of whatever
     the landlord chose to spend.
  3. **Pro rata share** — the clinic's rentable area over the *lease's own*
     denominator, which is not always the building's actual area.
  4. **Controllable cap** — the lease limits year-on-year growth in everything
     except taxes, insurance, utilities and snow.

Then there is the check no single statement can fail: **the same vendor line
billed in full to two tenants in the same center.** Each invoice looks correct
on its own. Only summing an allocation across every Northbay clinic in a center
shows the landlord recovered more than 100% of what it spent.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

TOLERANCE = 1.00

# The lease's own words for each test, cited on every finding.
PROOF = {
    "exclusion": ("4.3", "Operating Expenses shall expressly exclude: (a) capital "
                         "improvements and capital replacements"),
    "management_fee": ("4.4", "The property management fee included in Operating "
                              "Expenses shall not exceed four percent (4%) of gross "
                              "rental receipts"),
    "controllable_cap": ("4.5", "shall not increase by more than five percent (5%) "
                                "per calendar year on a cumulative, compounding basis"),
    "pro_rata": ("4.8", "No Operating Expense shall be allocated to Tenant in excess "
                        "of Tenant's Proportionate Share of the expense actually incurred"),
    "double_allocation": ("4.8", "no single expense may be allocated more than once "
                                 "among the tenants of the Building"),
}

MANAGEMENT_FEE_CAP_PCT = 0.04
CONTROLLABLE_CAP_PCT = 0.05


@dataclass(frozen=True)
class CamRule:
    """The operating-expense terms of one confirmed lease."""
    lease_id: str
    clinic_id: str
    center_id: str
    rsf: int
    # The denominator the lease stipulates, which may not be the real area.
    stipulated_building_rsf: int
    management_fee_cap_pct: float = MANAGEMENT_FEE_CAP_PCT
    controllable_cap_pct: float = CONTROLLABLE_CAP_PCT
    excluded_categories: frozenset = frozenset({"capital"})

    @property
    def pro_rata(self) -> float:
        return round(self.rsf / self.stipulated_building_rsf, 6)


@dataclass
class AllowedLine:
    category: str
    pool_amount: float
    recoverable: float
    share: float
    reason: str = ""


@dataclass
class Allowed:
    clinic_id: str
    year: int
    lines: List[AllowedLine] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def total(self) -> float:
        return round(sum(l.share for l in self.lines), 2)

    def line(self, category: str) -> Optional[AllowedLine]:
        for l in self.lines:
            if l.category == category:
                return l
        return None


@dataclass
class CamFinding:
    rule: str
    clinic_id: str
    category: str
    billed: float
    supported: float
    reason: str
    section: str
    quote: str
    related_clinics: List[str] = field(default_factory=list)

    @property
    def variance(self) -> float:
        return round(self.billed - self.supported, 2)


def allowed(rule: CamRule, pool, gross_receipts: float,
            prior_year_controllable: Optional[float] = None) -> Allowed:
    """What this clinic owes of a center's pool, under its own lease."""
    result = Allowed(rule.clinic_id, pool.year)

    for category, amount in sorted(pool.by_category().items()):
        lines = [l for l in pool.lines if l.category == category]
        excluded = [l for l in lines if l.excluded or category in rule.excluded_categories]
        recoverable = round(sum(l.amount for l in lines if l not in excluded), 2)
        reason = ""

        if excluded and recoverable == 0:
            reason = excluded[0].exclusion_reason or "excluded by the lease"

        if category == "management_fee":
            cap = round(gross_receipts * rule.management_fee_cap_pct, 2)
            if recoverable > cap:
                reason = ("capped at %.0f%% of gross receipts ($%s)"
                          % (rule.management_fee_cap_pct * 100, _money(cap)))
                recoverable = cap

        result.lines.append(AllowedLine(
            category=category,
            pool_amount=amount,
            recoverable=recoverable,
            share=round(recoverable * rule.pro_rata, 2),
            reason=reason,
        ))

    if prior_year_controllable is not None:
        cap = round(prior_year_controllable * (1 + rule.controllable_cap_pct), 2)
        current = round(sum(l.share for l in result.lines
                            if l.category not in _NON_CONTROLLABLE), 2)
        if current > cap + TOLERANCE:
            result.notes.append(
                "Controllable share $%s exceeds the %.0f%% cap on last year's "
                "$%s. Capped at $%s."
                % (_money(current), rule.controllable_cap_pct * 100,
                   _money(prior_year_controllable), _money(cap)))
            _apply_controllable_cap(result, cap, current)

    return result


def check_statement(rule: CamRule, pool, billed_by_category: Dict[str, float],
                    gross_receipts: float,
                    prior_year_controllable: Optional[float] = None) -> List[CamFinding]:
    """Compare a landlord's statement line by line against the lease."""
    due = allowed(rule, pool, gross_receipts, prior_year_controllable)
    findings: List[CamFinding] = []

    for category, billed in sorted(billed_by_category.items()):
        line = due.line(category)
        supported = line.share if line else 0.0
        if abs(billed - supported) <= TOLERANCE:
            continue

        section, quote = _proof_for(category, line)
        findings.append(CamFinding(
            rule=_rule_name(category, line),
            clinic_id=rule.clinic_id,
            category=category,
            billed=round(billed, 2),
            supported=supported,
            reason=_explain(category, billed, supported, line, rule),
            section=section,
            quote=quote,
        ))
    return findings


def check_shared_pool(rules: Iterable[CamRule], pool) -> List[CamFinding]:
    """The check a single statement cannot fail.

    Sums each vendor line's allocation across every Northbay clinic in the
    center. When the landlord has billed one expense in full to more than one
    tenant, it has recovered more than it spent — and neither invoice looks
    wrong on its own.
    """
    rules = list(rules)
    findings: List[CamFinding] = []
    section, quote = PROOF["double_allocation"]

    for line in pool.lines:
        billed_to = [r for r in rules if r.clinic_id in line.billed_in_full_to]
        if len(billed_to) < 2:
            continue

        combined_share = round(sum(r.pro_rata for r in billed_to), 6)
        recovered = round(line.amount * len(billed_to), 2)
        supported = 0.0 if line.excluded else round(line.amount * combined_share, 2)

        findings.append(CamFinding(
            rule="shared_pool",
            clinic_id=billed_to[0].clinic_id,
            category=line.category,
            billed=recovered,
            supported=supported,
            reason=(
                "%s invoice %s for $%s was billed in full to %d Northbay suites "
                "in %s, recovering $%s against a combined proportionate share of "
                "%.2f%%.%s"
                % (line.vendor, line.invoice_ref, _money(line.amount),
                   len(billed_to), line.center_id, _money(recovered),
                   combined_share * 100,
                   " The lease also excludes this cost entirely."
                   if line.excluded else "")),
            section=section,
            quote=quote,
            related_clinics=[r.clinic_id for r in billed_to],
        ))
    return findings


# --- helpers ---------------------------------------------------------------

_NON_CONTROLLABLE = {"property_tax", "insurance", "utilities", "snow_removal"}


def _apply_controllable_cap(result: Allowed, cap: float, current: float) -> None:
    if current <= 0:
        return
    factor = cap / current
    for line in result.lines:
        if line.category not in _NON_CONTROLLABLE:
            line.share = round(line.share * factor, 2)


def _proof_for(category: str, line: Optional[AllowedLine]):
    if line and line.reason and "exclude" in line.reason.lower():
        return PROOF["exclusion"]
    if category == "management_fee":
        return PROOF["management_fee"]
    return PROOF["pro_rata"]


def _rule_name(category: str, line: Optional[AllowedLine]) -> str:
    if line and line.reason and "exclude" in line.reason.lower():
        return "excluded_cost"
    if category == "management_fee":
        return "management_fee_cap"
    return "pro_rata_share"


def _explain(category: str, billed: float, supported: float,
             line: Optional[AllowedLine], rule: CamRule) -> str:
    delta = round(billed - supported, 2)
    direction = "more than" if delta > 0 else "less than"
    if line and line.reason:
        return ("%s billed at $%s. %s, so the lease supports $%s."
                % (category.replace("_", " ").title(), _money(billed),
                   line.reason[0].upper() + line.reason[1:], _money(supported)))
    return ("%s billed at $%s is $%s %s the $%s supported at a %.2f%% "
            "proportionate share."
            % (category.replace("_", " ").title(), _money(billed),
               _money(abs(delta)), direction, _money(supported), rule.pro_rata * 100))


def _money(v: float) -> str:
    return "{:,.2f}".format(v)
