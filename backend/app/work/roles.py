"""Who may do what to which work item: the ROLES matrix and `can()`.

This is the first of three lines of defence. The gateway checks again, and
Postgres refuses anything the connecting role was never granted. `can()` is
the one that knows about people: their role, their region, their entity, and
what they already did to the item.

`can()` is pure. It reads an actor and an item mapping and says yes or no
with a reason a person can read. It never touches the database, so the UI can
call it to decide which buttons to draw (transitions.allowed_actions) with
the same answer transition() will give when the button is pressed.
Separation of duties needs the item's history, so `can()` reads two keys the
work_item row does not have: `proposers` and `answered_by`.
transitions.load_item() fills them in; a caller building its own mapping must
too, or the check falls back to `proposed_by` alone.
"""

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

GATEWAY_ACTOR = "system:gateway"

ANY_KIND = "*"

# role -> work item kind -> actions. ANY_KIND applies to every kind. A role
# or action that is not here is refused. 'create' is not a transition, but
# making an item is work too and is checked the same way.
ROLES = {
    "agent": {ANY_KIND: {"create", "propose", "ask", "hold"}},
    "regional_manager": {ANY_KIND: {"answer", "approve", "reject", "hold", "resume"}},
    "controller": {ANY_KIND: {"approve", "reject", "close", "hold", "resume", "answer"}},
    # The AP clerk releases payment batches and touches nothing else.
    "ap_clerk": {"PAYMENT_RELEASE": {"approve", "hold", "resume"}},
    "auditor": {},
    # Only the gateway posts. Its one other move is closing an approved item
    # that has nothing to post: a hold upheld on a wholly unsupported charge.
    "system": {ANY_KIND: {"post", "close"}},
}


class UnknownActor(LookupError):
    """No active actor has this id."""


@dataclass(frozen=True)
class Actor:
    id: str
    role: str
    region_id: Optional[str]
    entity_id: Optional[str]


def load_actor(conn: Connection, actor_id: str) -> Actor:
    """The active actor with this id. Reads only the columns every role may
    see, so it works on any connection, including lease_agent's."""
    if not isinstance(actor_id, str) or not actor_id:
        raise UnknownActor("actor id must be a non-empty string, got %r" % (actor_id,))
    row = conn.execute(text("""
        SELECT id, role, region_id, entity_id FROM actor WHERE id = :id AND active
    """), {"id": actor_id}).first()
    if row is None:
        raise UnknownActor("no active actor %r" % actor_id)
    return Actor(id=row.id, role=row.role, region_id=row.region_id, entity_id=row.entity_id)


def ensure_gateway_actor(conn: Connection) -> Actor:
    """Make sure system:gateway exists. Migration 0003 inserts it; a test that
    empties the actor table, or a seed into a fresh database, calls this."""
    conn.execute(text("""
        INSERT INTO actor (id, name, role, active) VALUES (:id, 'Gateway', 'system', true)
        ON CONFLICT (id) DO NOTHING
    """), {"id": GATEWAY_ACTOR})
    return Actor(id=GATEWAY_ACTOR, role="system", region_id=None, entity_id=None)


def can(actor: Actor, action: str, item: Mapping) -> Tuple[bool, str]:
    """(allowed, reason). Checks run from the broadest to the most specific,
    so the reason names the first rule that refused."""
    kinds = ROLES.get(actor.role)
    if kinds is None:
        return False, "unknown role %r" % actor.role
    kind = item.get("kind")
    allowed = kinds.get(ANY_KIND, set()) | kinds.get(kind, set())
    if action not in allowed:
        return False, "role %s may not %s a %s item" % (actor.role, action, kind or "work")

    if actor.entity_id is not None and item.get("entity_id") != actor.entity_id:
        return False, "item is outside %s's entity %s" % (actor.id, actor.entity_id)

    if actor.role == "regional_manager" and item.get("region_id") != actor.region_id:
        return False, "item is in region %s, not %s's region %s" % (
            item.get("region_id"), actor.id, actor.region_id)

    if action == "approve":
        proposers = set(item.get("proposers") or ()) | {item.get("proposed_by")}
        if actor.id in proposers:
            return False, "separation of duties: %s proposed this item" % actor.id
        if actor.id in set(item.get("answered_by") or ()):
            return False, "separation of duties: %s answered a question on this item" % actor.id

    return True, "allowed"
