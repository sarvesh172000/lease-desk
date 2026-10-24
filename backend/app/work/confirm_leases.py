"""Confirm drafted lease versions as a named regional manager (demo only).

    LEASEDESK_DEMO_MODE=1 python -m app.work.confirm_leases --as PER-RM-BAY

In the product a regional manager confirms a lease by approving its
LEASE_ABSTRACTION work item (POST /api/items/{id}/actions/approve, or the
Confirm button on the lease page). `make demo-data` uses this to do the same
thing for the seeded manager, so the demo opens on checked charges: it is
exactly that approve, through transition() on `lease_api`, so every
confirmation is a hash-chained event naming the person, can() still decides
(region, separation of duties), and replay rebuilds it like any other.

It acts in a person's name without them, so it refuses unless
LEASEDESK_DEMO_MODE=1, like `make dev-passwords`. Idempotent: only PROPOSED
items are approved, so a second run confirms nothing.
"""

import argparse
import sys
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .roles import Actor
from .transitions import Denied, transition

ITEM_KIND = "LEASE_ABSTRACTION"


class ConfirmRefused(RuntimeError):
    """Demo mode is off."""


def pending(conn: Connection, entity_id: Optional[str] = None) -> List[Tuple[int, str]]:
    """(work item id, lease id) of every lease version still awaiting confirmation."""
    return [tuple(r) for r in conn.execute(text("""
        SELECT w.id, v.lease_id FROM work_item w
          JOIN lease_version v ON v.id::text = w.subject_id
         WHERE w.kind = :k AND w.subject_type = 'lease_version' AND w.state = 'PROPOSED'
           AND (CAST(:e AS text) IS NULL OR w.entity_id = :e)
         ORDER BY v.lease_id
    """), {"k": ITEM_KIND, "e": entity_id})]


def confirm_all(conn: Connection, actor: Actor,
                entity_id: Optional[str] = None) -> List[str]:
    """Approve every pending LEASE_ABSTRACTION item this actor may approve.
    Returns the confirmed lease ids; items can() refuses are left (and the
    refusal is on record, as for any denied press)."""
    done = []
    for item_id, lease_id in pending(conn, entity_id):
        try:
            transition(conn, actor, item_id, "approve",
                       reason="Lease terms checked against the cited pages.")
        except Denied:
            continue
        done.append(lease_id)
    return done


def main(argv=None) -> int:
    from ..db.engine import engine
    from ..settings import get_settings
    from .roles import load_actor

    parser = argparse.ArgumentParser(description="Confirm drafted lease versions (demo only)")
    parser.add_argument("--as", dest="actor", required=True, help="regional manager actor id")
    parser.add_argument("--entity", default=None)
    args = parser.parse_args(argv)
    if not get_settings().demo_mode:
        print("refusing to confirm leases on someone's behalf with LEASEDESK_DEMO_MODE off",
              file=sys.stderr)
        return 1
    with engine("lease_api").begin() as conn:
        actor = load_actor(conn, args.actor)
        done = confirm_all(conn, actor, args.entity)
    print("confirm-leases: %d lease version(s) confirmed as %s%s" % (
        len(done), args.actor, (": " + ", ".join(done)) if done else " (none pending)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
