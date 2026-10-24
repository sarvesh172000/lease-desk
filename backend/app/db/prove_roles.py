"""`make prove-roles`: show, live, that the database enforces the limits.

Each line connects as one role and attempts something it must never do. Every
attempt is rolled back, so this is safe to run against the demo database.

    lease_agent   INSERT INTO journal_entry ...   denied: permission denied for table journal_entry
"""

import sys

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .engine import engine

ATTEMPTS = [
    ("lease_agent", "INSERT INTO journal_entry (entity_id, date, period, memo, idempotency_key) "
                    "VALUES ('ENT-CA', '2026-01-31', '2026-01-01', 'agent posts', 'prove-1')"),
    ("lease_agent", "INSERT INTO outbox (kind, payload, idempotency_key) "
                    "VALUES ('ap_batch', '{}', 'prove-2')"),
    ("lease_agent", "UPDATE landlord_charge SET amount = 0"),
    ("lease_api", "INSERT INTO journal_line (journal_entry_id, account_id, debit) VALUES (1, 1, 1)"),
    ("lease_reader", "INSERT INTO audit_event (actor_id, action, subject_type, subject_id, allowed) "
                     "VALUES ('auditor', 'approve', 'work_item', '1', true)"),
    ("lease_gateway", "UPDATE audit_event SET reason = 'rewritten'"),
    ("lease_gateway", "DELETE FROM audit_event"),
]


def attempt(role: str, sql: str) -> str:
    with engine(role).connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text(sql))
            return "ALLOWED"
        except DBAPIError as exc:
            return "denied: %s" % str(exc.orig).splitlines()[0]
        finally:
            tx.rollback()


def main() -> int:
    allowed = 0
    for role, sql in ATTEMPTS:
        result = attempt(role, sql)
        allowed += result == "ALLOWED"
        print("%-14s %-60.60s %s" % (role, sql, result))
    if allowed:
        print("\n%d forbidden write(s) were allowed. The roles are misconfigured." % allowed)
        return 1
    print("\nEvery forbidden write was refused by the database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
