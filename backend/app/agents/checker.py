"""Compare every charge against what the lease supports.

Running the engine over January proved that an amount comparison alone catches
two of five planted errors. The three that escape it are not amount problems at
all, so this module asks three different questions, in an order that matters:

  1. **Is this charge even for our premises?** A line for a suite we do not
     lease is not a rent variance; it is an unsupported charge. Asking this
     first is what stops the stray Suite 118 line from being reported as
     CLINIC-02 *underpaying* its rent, which is what happens when every
     payment is naively compared to the month's expected rent.

  2. **Has this already been billed?** A duplicate carries the *correct*
     amount — that is exactly why it survives. Counting charges per lease,
     period and type is the only thing that finds it.

  3. **Does the amount match the lease?** Only now, and only for the one
     charge that is genuinely this month's.

The model writes none of this. It writes the one-paragraph explanation from
structured facts, and only once a finding exists.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional

from ..engine.charges import Expected, LeaseRule, Proof, expected, within_tolerance

APPROVE = "approve"
HOLD = "hold"

RULE_PREMISES = "premises"
RULE_DUPLICATE = "duplicate"
RULE_AMOUNT = "amount"
RULE_OPERATING_EXPENSE = "operating_expense"


@dataclass(frozen=True)
class Charge:
    """One billed line, as it arrives from the invoice parser."""
    charge_id: str
    invoice_id: str
    lease_id: str
    clinic_id: str
    period: date
    charge_type: str
    suite: str
    amount: float
    description: str = ""


@dataclass
class Finding:
    finding_id: str
    rule: str
    charge: Charge
    proposal: str
    reason: str
    billed: float
    supported: float
    proof: Optional[Proof] = None
    related: List[str] = field(default_factory=list)

    @property
    def variance(self) -> float:
        return round(self.billed - self.supported, 2)

    @property
    def is_hold(self) -> bool:
        return self.proposal == HOLD

    def describe(self) -> str:
        return "%s %s %s: billed $%s, lease supports $%s (%s $%s)" % (
            self.charge.clinic_id,
            self.charge.period.strftime("%b %Y"),
            self.charge.charge_type,
            _money(self.billed),
            _money(self.supported),
            "over by" if self.variance > 0 else "under by",
            _money(abs(self.variance)),
        )


def check_month(
    charges: Iterable[Charge],
    rules: Dict[str, LeaseRule],
    period: date,
) -> List[Finding]:
    """Every finding for one month, across every lease."""
    charges = [c for c in charges if c.period == period]
    findings: List[Finding] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return "F%03d" % counter

    # Rule 1 — premises. Anything not for the demised suite is set aside here
    # and never reaches the amount comparison.
    on_premises: List[Charge] = []
    for charge in charges:
        rule = rules.get(charge.lease_id)
        if rule is None:
            findings.append(Finding(
                next_id(), RULE_PREMISES, charge, HOLD,
                "No confirmed lease for %s, so nothing supports this charge." % charge.lease_id,
                charge.amount, 0.0))
            continue
        if _normalize_suite(charge.suite) != _normalize_suite(rule.suite):
            findings.append(Finding(
                next_id(), RULE_PREMISES, charge, HOLD,
                "Billed for %s. The lease demises %s, so no part of this charge is supported."
                % (charge.suite, rule.suite),
                charge.amount, 0.0, rule.proof_for("premises")))
            continue
        on_premises.append(charge)

    # Rule 2 — duplicates. Count per lease, period and charge type. The first
    # charge is this month's; every later one is unsupported regardless of
    # whether its amount is correct.
    grouped: Dict[tuple, List[Charge]] = defaultdict(list)
    for charge in on_premises:
        grouped[(charge.lease_id, charge.period, charge.charge_type)].append(charge)

    primary: List[Charge] = []
    for key, group in grouped.items():
        group = sorted(group, key=lambda c: (c.invoice_id, c.charge_id))
        primary.append(group[0])
        for extra in group[1:]:
            rule = rules[extra.lease_id]
            findings.append(Finding(
                next_id(), RULE_DUPLICATE, extra, HOLD,
                "%s for %s was already billed on %s. The lease provides for one "
                "monthly installment." % (
                    _label(extra.charge_type), extra.period.strftime("%B %Y"),
                    group[0].invoice_id),
                extra.amount, 0.0, rule.proof_for("payment_timing"),
                related=[group[0].charge_id]))

    # Rule 3 — amount, now that each charge is the only one of its kind.
    for charge in sorted(primary, key=lambda c: (c.lease_id, c.charge_type)):
        rule = rules[charge.lease_id]
        due = expected(rule, charge.period)
        supported = due.for_type(charge.charge_type)

        if within_tolerance(charge.amount, supported):
            findings.append(Finding(
                next_id(), _rule_for(charge.charge_type), charge, APPROVE,
                "Matches the lease.", charge.amount, supported,
                rule.proof_for(_proof_key(charge.charge_type))))
            continue

        findings.append(Finding(
            next_id(), _rule_for(charge.charge_type), charge, HOLD,
            _explain(charge, supported, rule), charge.amount, supported,
            rule.proof_for(_proof_key(charge.charge_type))))

    return findings


def holds(findings: Iterable[Finding]) -> List[Finding]:
    return [f for f in findings if f.is_hold]


def total_held(findings: Iterable[Finding]) -> float:
    return round(sum(f.variance for f in findings if f.is_hold), 2)


def _explain(charge: Charge, supported: float, rule: LeaseRule) -> str:
    delta = round(charge.amount - supported, 2)
    direction = "more than" if delta > 0 else "less than"
    if charge.charge_type == "cam_estimate":
        return (
            "Operating expense estimate of $%s is $%s %s the $%s the lease "
            "supports at $%.2f per rentable square foot per annum."
            % (_money(charge.amount), _money(abs(delta)), direction,
               _money(supported), rule.cam_estimate_psf_annual))
    return (
        "Base rent of $%s is $%s %s the $%s the rent schedule provides for %s."
        % (_money(charge.amount), _money(abs(delta)), direction,
           _money(supported), charge.period.strftime("%B %Y")))


def _rule_for(charge_type: str) -> str:
    return RULE_OPERATING_EXPENSE if charge_type == "cam_estimate" else RULE_AMOUNT


def _proof_key(charge_type: str) -> str:
    return "cam_estimate" if charge_type == "cam_estimate" else "base_rent"


def _label(charge_type: str) -> str:
    return {"base_rent": "Base rent", "cam_estimate": "Operating expense estimate"}.get(
        charge_type, charge_type)


def _normalize_suite(value: str) -> str:
    return " ".join(str(value).lower().replace("suite", "").split())


def _money(value: float) -> str:
    return "{:,.2f}".format(value)
