"""What March would look like if we knew then what we know now.

A month is checked against the rulebook as it stood at the time. Then an
amendment turns up, a policy is approved, a landlord concedes a disputed
charge — and the question a controller actually asks is not "was March right?"
but **"how much of what we held in March would we still hold today?"**

That is the measure of whether the system is learning. Questions asked once and
answered become policies; a month replayed with later knowledge should raise
fewer of them. If it raises the same number, nothing was learned.

Nothing here posts. A replay is a view, never a correction: the books for a
closed period stay as they were signed off, and a difference is a finding for a
human, not an entry.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

UNCHANGED = "unchanged"
NOW_APPROVED = "now_approved"
NOW_HELD = "now_held"
AMOUNT_CHANGED = "amount_changed"


@dataclass(frozen=True)
class Change:
    charge_id: str
    clinic_id: str
    kind: str
    then_proposal: str
    now_proposal: str
    then_supported: float
    now_supported: float
    reason: str

    @property
    def dollars(self) -> float:
        return round(abs(self.now_supported - self.then_supported), 2)


@dataclass
class Replay:
    period: date
    as_known_on: date
    changes: List[Change] = field(default_factory=list)
    charges_compared: int = 0
    held_then: int = 0
    held_now: int = 0

    @property
    def unchanged(self) -> int:
        return self.charges_compared - len(self.changes)

    @property
    def questions_avoided(self) -> int:
        """Holds that later knowledge resolves. The learning measure."""
        return sum(1 for c in self.changes if c.kind == NOW_APPROVED)

    @property
    def newly_raised(self) -> int:
        return sum(1 for c in self.changes if c.kind == NOW_HELD)

    @property
    def dollars_moved(self) -> float:
        return round(sum(c.dollars for c in self.changes), 2)

    def describe(self) -> str:
        if not self.changes:
            return ("%s is unchanged by everything learned since."
                    % self.period.strftime("%B %Y"))
        return (
            "%s replayed as known on %s: %d of %d charges decided differently. "
            "%d holds would not be raised today; %d would now be raised. "
            "$%s of supported amounts moved."
            % (self.period.strftime("%B %Y"), self.as_known_on.isoformat(),
               len(self.changes), self.charges_compared,
               self.questions_avoided, self.newly_raised,
               "{:,.2f}".format(self.dollars_moved))
        )


def replay(findings_then: Iterable, findings_now: Iterable,
           period: date, as_known_on: date) -> Replay:
    """Compare a month's decisions then against the same month decided now.

    Both sets come from the same checker; only the rulebook differs. That is
    deliberate — a diff caused by a code change would say nothing about what
    was learned.
    """
    then = {f.charge.charge_id: f for f in findings_then}
    now = {f.charge.charge_id: f for f in findings_now}

    result = Replay(period=period, as_known_on=as_known_on)
    result.charges_compared = len(set(then) | set(now))
    result.held_then = sum(1 for f in then.values() if f.proposal == "hold")
    result.held_now = sum(1 for f in now.values() if f.proposal == "hold")

    for charge_id in sorted(set(then) | set(now)):
        before, after = then.get(charge_id), now.get(charge_id)
        change = _compare(charge_id, before, after)
        if change is not None:
            result.changes.append(change)

    return result


def _compare(charge_id: str, before, after) -> Optional[Change]:
    if before is None or after is None:
        return None

    if before.proposal != after.proposal:
        kind = NOW_APPROVED if after.proposal == "approve" else NOW_HELD
        return Change(
            charge_id=charge_id,
            clinic_id=after.charge.clinic_id,
            kind=kind,
            then_proposal=before.proposal,
            now_proposal=after.proposal,
            then_supported=before.supported,
            now_supported=after.supported,
            reason=after.reason,
        )

    if abs(before.supported - after.supported) > 0.01:
        return Change(
            charge_id=charge_id,
            clinic_id=after.charge.clinic_id,
            kind=AMOUNT_CHANGED,
            then_proposal=before.proposal,
            now_proposal=after.proposal,
            then_supported=before.supported,
            now_supported=after.supported,
            reason="The lease now supports a different amount for this month.",
        )

    return None


def learning_curve(replays: Iterable[Replay]) -> List[Tuple[str, int, int]]:
    """Holds then versus holds now, month by month.

    The number that has to fall over a year for "it improves" to be true.
    """
    return [(r.period.strftime("%Y-%m"), r.held_then, r.held_now)
            for r in sorted(replays, key=lambda r: r.period)]
