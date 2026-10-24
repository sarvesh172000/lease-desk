"""Closing a period, and proving it closed.

A close is not "we finished the entries". It is a checklist, and every item has
to be answerable with a number:

  1. **Every charge is resolved or accrued.** A charge still under review is
     not ignored — the lease-supported portion is accrued and the disputed
     difference is recorded as disputed. Expensing money we believe is not owed
     would be as wrong as paying it.
  2. **Every schedule is posted.** A lease with no entry this month is a lease
     nobody looked at.
  3. **The subledger ties to the general ledger, to the cent.** Not "close
     enough" — the lease liability in the subledger and the balance in the GL
     are the same number, or the period does not close.
  4. **No open question above materiality.** Small unknowns can wait; a
     material one cannot be closed over.

Only then may a controller sign off, and only a controller. After sign-off the
period locks and nothing may post into it.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional

OPEN = "open"
READY = "ready_to_close"
CLOSED = "closed"

DEFAULT_MATERIALITY = 5_000.00
TIE_OUT_TOLERANCE = 0.01


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    blocking: bool = True


@dataclass
class CloseChecklist:
    entity_id: str
    period: date
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def blocking_failures(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.passed and c.blocking]

    @property
    def ready(self) -> bool:
        return not self.blocking_failures

    @property
    def status(self) -> str:
        return READY if self.ready else OPEN

    def describe(self) -> str:
        if self.ready:
            return "%s %s is ready to close." % (
                self.entity_id, self.period.strftime("%B %Y"))
        return "%s %s cannot close: %s" % (
            self.entity_id, self.period.strftime("%B %Y"),
            "; ".join(c.detail for c in self.blocking_failures))


@dataclass
class Period:
    entity_id: str
    period: date
    status: str = OPEN
    signed_off_by: Optional[str] = None
    signed_off_at: Optional[date] = None

    @property
    def locked(self) -> bool:
        return self.status == CLOSED


class PeriodLocked(Exception):
    """Raised when something tries to post into a closed period."""


def build_checklist(
    entity_id: str,
    period: date,
    subledger_liability: float,
    gl_liability: float,
    subledger_rou: float,
    gl_rou: float,
    leases_expected: Iterable[str],
    leases_posted: Iterable[str],
    unresolved_charges: Iterable,
    open_questions: Iterable,
    materiality: float = DEFAULT_MATERIALITY,
) -> CloseChecklist:
    """Every check a period has to pass, with the number behind each."""
    checklist = CloseChecklist(entity_id, period)
    expected, posted = set(leases_expected), set(leases_posted)
    unresolved = list(unresolved_charges)
    questions = list(open_questions)

    missing = sorted(expected - posted)
    checklist.checks.append(CheckResult(
        "schedules_posted", not missing,
        "every lease has a posted entry" if not missing
        else "%d lease(s) have no entry: %s" % (len(missing), ", ".join(missing[:5]))))

    unaccrued = [c for c in unresolved if not _is_accrued(c)]
    checklist.checks.append(CheckResult(
        "charges_resolved_or_accrued", not unaccrued,
        "all charges resolved or accrued" if not unaccrued
        else "%d charge(s) neither resolved nor accrued" % len(unaccrued)))

    liability_gap = round(subledger_liability - gl_liability, 2)
    checklist.checks.append(CheckResult(
        "liability_ties_to_gl", abs(liability_gap) < TIE_OUT_TOLERANCE,
        "lease liability ties to the GL" if abs(liability_gap) < TIE_OUT_TOLERANCE
        else "lease liability is out by $%s (subledger %s, GL %s)" % (
            _money(liability_gap), _money(subledger_liability), _money(gl_liability))))

    rou_gap = round(subledger_rou - gl_rou, 2)
    checklist.checks.append(CheckResult(
        "rou_ties_to_gl", abs(rou_gap) < TIE_OUT_TOLERANCE,
        "ROU asset ties to the GL" if abs(rou_gap) < TIE_OUT_TOLERANCE
        else "ROU asset is out by $%s" % _money(rou_gap)))

    material = [q for q in questions if _amount_of(q) >= materiality]
    checklist.checks.append(CheckResult(
        "no_material_open_questions", not material,
        "no open question above $%s" % _money(materiality) if not material
        else "%d open question(s) above materiality, totalling $%s" % (
            len(material), _money(sum(_amount_of(q) for q in material)))))

    immaterial = [q for q in questions if _amount_of(q) < materiality]
    checklist.checks.append(CheckResult(
        "immaterial_questions_noted", True,
        "%d open question(s) below materiality, carried forward" % len(immaterial),
        blocking=False))

    return checklist


def sign_off(period: Period, checklist: CloseChecklist, actor_role: str,
             actor_id: str, on: date) -> Period:
    """Close the period. Only a controller, and only when every check passes."""
    if actor_role != "controller":
        raise PermissionError(
            "only a controller may close a period; %s is a %s" % (actor_id, actor_role))
    if not checklist.ready:
        raise ValueError(checklist.describe())
    if period.locked:
        raise PeriodLocked("%s %s is already closed"
                           % (period.entity_id, period.period.isoformat()))

    period.status = CLOSED
    period.signed_off_by = actor_id
    period.signed_off_at = on
    return period


def assert_open(period: Period) -> None:
    """Called before anything posts. A closed period takes no more entries."""
    if period.locked:
        raise PeriodLocked(
            "%s %s was closed by %s on %s; nothing may post into it"
            % (period.entity_id, period.period.strftime("%B %Y"),
               period.signed_off_by, period.signed_off_at))


def _is_accrued(charge) -> bool:
    return bool(getattr(charge, "accrued", False))


def _amount_of(question) -> float:
    return float(getattr(question, "amount", getattr(question, "variance", 0.0)) or 0.0)


def _money(v: float) -> str:
    return "{:,.2f}".format(abs(v))
