"""What "Approve" means on a landlord charge check, and what may reach AP.

A CHARGE_CHECK item carries the checker's proposal:

  approve   the charge matches the lease. Approving it accepts the charge and
            the gateway posts what was billed (Dr expense / Cr AP).
  hold      the checker found the charge wrong (a duplicate invoice, rent for
            a suite the lease does not demise, an escalation applied early,
            CAM above the estimate). Approving a hold means "I agree with the
            hold", never "pay it": the resolution is `upheld`, and only the
            undisputed amount, the checker's `supported`, may be posted. A
            wholly unsupported charge (supported 0) posts nothing.

Paying a disputed amount anyway is a separate, explicit decision:
`pay_as_billed`, controller-only, with a reason that goes on the record. It
is the only way a disputed dollar reaches the ledger or an AP batch.

The resolution is written into the item's `evidence` by the approve event
itself (evidence is patchable; the projection copies it), so the state
machine is unchanged and replay rebuilds it. The gateway reads it back with
payable(), and for `pay_as_billed` checks the approve event on record too, so
an evidence field set any other way cannot release money.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Mapping, Optional

from sqlalchemy.engine import Connection

from .roles import Actor
from .transitions import Denied, load_item, record_denial, transition

CHARGE_CHECK = "CHARGE_CHECK"
HOLD = "hold"

UPHELD = "upheld"                 # agree with the hold: pay only what the lease supports
PAY_AS_BILLED = "pay_as_billed"   # override: pay the billed amount despite the hold
RESOLUTIONS = (UPHELD, PAY_AS_BILLED)

OVERRIDE_ROLE = "controller"

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


class OverrideRefused(Denied):
    """A pay-as-billed override by someone who may not make it. On record."""


@dataclass(frozen=True)
class Payable:
    """What the gateway may post, and pay, for one approved charge check.

    basis:  'approved'       proposal approve: the charge as billed
            'supported'      a hold upheld: the undisputed amount only
            'pay_as_billed'  a hold overridden by a controller: as billed
    """
    amount: Decimal
    disputed: Decimal
    basis: str
    key_suffix: str      # '' keeps the engine's key; held items get their own


def is_disputed(item: Mapping) -> bool:
    return item.get("kind") == CHARGE_CHECK and item.get("proposal") == HOLD


def payable(item: Mapping, billed: Any) -> Payable:
    """The amount an approved charge check may post, from its proposal and
    the resolution its approval recorded. Never more than was billed, and a
    hold without a recorded override is always treated as upheld."""
    billed = _money(billed) or ZERO
    if not is_disputed(item):
        return Payable(billed, ZERO, "approved", "")
    evidence = item.get("evidence") if isinstance(item.get("evidence"), Mapping) else {}
    if evidence.get("resolution") == PAY_AS_BILLED:
        return Payable(billed, ZERO, PAY_AS_BILLED, "|as_billed")
    supported = _money(evidence.get("supported"))
    if supported is None or supported < 0:
        supported = ZERO
    supported = min(supported, billed)
    return Payable(supported, billed - supported, "supported", "|supported")


def approve_charge(conn: Connection, actor: Actor, item_id: Any, *,
                   resolution: Optional[str] = None, reason: Optional[str] = None) -> Dict[str, Any]:
    """Approve one charge check with the meaning its proposal gives approval.

    - proposal approve: a plain approve; `resolution` must be absent.
    - proposal hold, resolution None or 'upheld': the hold is upheld; the
      evidence records it, with the undisputed and disputed amounts.
    - proposal hold, resolution 'pay_as_billed': only a controller, and only
      with a reason. Anyone else is refused (Denied, with an allowed = false
      event on record); a missing reason is a ValueError and writes nothing.

    Runs in the caller's transaction, like transition().
    """
    if resolution is not None and resolution not in RESOLUTIONS:
        raise ValueError("resolution must be one of %s, got %r" % (", ".join(RESOLUTIONS), resolution))
    item = load_item(conn, item_id)
    if not is_disputed(item):
        if resolution is not None:
            raise ValueError("item %s is not a disputed charge (proposal %r); approve it "
                             "without a resolution" % (item["id"], item.get("proposal")))
        return transition(conn, actor, item["id"], "approve", reason=reason)

    evidence = dict(item.get("evidence") or {})
    billed = evidence.get("billed", item.get("amount"))
    if resolution == PAY_AS_BILLED:
        if actor.role != OVERRIDE_ROLE:
            why = ("only a controller may pay a disputed charge as billed; %s is %s"
                   % (actor.id, actor.role))
            event = record_denial(conn, actor, "approve", item, why,
                                  evidence={"resolution": PAY_AS_BILLED})
            raise OverrideRefused(why, event)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("paying a disputed charge as billed needs a reason")
        amount = _money(billed) or ZERO
        record = {"resolution": PAY_AS_BILLED, "resolved_by": actor.id,
                  "override_reason": reason.strip(), "payable": str(amount), "disputed_paid":
                  str(amount - min(_money(evidence.get("supported")) or ZERO, amount))}
    else:
        pay = payable(dict(item, evidence=dict(evidence, resolution=UPHELD)), billed)
        record = {"resolution": UPHELD, "resolved_by": actor.id,
                  "payable": str(pay.amount), "disputed": str(pay.disputed)}
    for stale in ("override_reason", "disputed_paid", "disputed"):
        evidence.pop(stale, None)
    evidence.update(record)
    return transition(conn, actor, item["id"], "approve", reason=reason,
                      patch={"evidence": evidence}, evidence=record)


def _money(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    return amount.quantize(CENT)
