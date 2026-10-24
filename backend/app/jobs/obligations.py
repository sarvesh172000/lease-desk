"""The B7 jobs: the deadline job (`obligations`) and the disputes sweep
(`disputes`). Both run as lease_agent inside the worker's per-job
transaction, like every handler in jobs/handlers.py, and both are
idempotent: a second run on the same business date writes nothing.

  obligations   refresh the lease obligations (work/obligations.refresh) and
                open the 90/60/30-business-day OBLIGATION items due on the
                business date (jobs/clock.today, or payload["today"]).
  disputes      draft a letter for every upheld hold without one, and propose
                recognising the receivable for every dispute whose letter is
                out (work/disputes.draft_disputes).

From the command line, as lease_agent:

    python -m app.jobs.obligations [--entity ENT-CA] [--today 2027-05-03] [--disputes]
"""

import argparse
import sys
from datetime import date
from typing import Any, Dict, Mapping

from sqlalchemy.engine import Connection

from ..work import disputes as dispute_work
from ..work import obligations as work
from . import clock


def obligations(conn: Connection, payload: Mapping[str, Any]) -> Dict[str, Any]:
    entity_id = payload.get("entity_id")
    today = date.fromisoformat(payload["today"]) if payload.get("today") else clock.today(conn)
    refreshed = work.refresh(conn, entity_id)
    created = work.create_alerts(conn, today, entity_id)
    return {"status": "checked", "today": today.isoformat(), "obligations": refreshed["obligations"],
            "new_or_moved": len(refreshed["new_or_moved"]), "skipped": refreshed["skipped"],
            "alerts_created": created}


def disputes(conn: Connection, payload: Mapping[str, Any]) -> Dict[str, Any]:
    result = dispute_work.draft_disputes(conn, payload.get("entity_id"))
    return dict(status="drafted", **result)


HANDLERS = {"obligations": obligations, "disputes": disputes}


def main(argv=None) -> int:
    from ..db.engine import engine

    parser = argparse.ArgumentParser(description="Run the deadline job (and the disputes sweep)")
    parser.add_argument("--entity", help="entity id; default every entity")
    parser.add_argument("--today", help="business date YYYY-MM-DD; default the business clock")
    parser.add_argument("--disputes", action="store_true", help="also run the disputes sweep")
    args = parser.parse_args(argv)
    payload = {"entity_id": args.entity, "today": args.today}
    with engine("lease_agent").begin() as conn:
        result = obligations(conn, payload)
        print("obligations: %d found, %d new or moved, alerts created %s"
              % (result["obligations"], result["new_or_moved"], result["alerts_created"]))
        if args.disputes:
            print("disputes: %s" % disputes(conn, payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
