"""What each job kind does: a registry of kind -> handler(conn, payload).

A handler runs inside the worker's per-job transaction, as `lease_agent`.
Whatever it writes commits together with the job being marked done, or not
at all; a handler that raises leaves no trace but the job's `last_error`.
It returns a small JSON-able dict that is kept on the job as its result.

The three monthly steps, and what each honestly does today:

  ingest       Seeding (`make seed`) already ingests the generator's exports,
               so this checks the period's raw rows and charges are present
               and reports the counts. Nothing there is a failure, not a pass.
  abstraction  Drafts lease_version 1 for every lease that has none, each term
               cited to its page and box, and opens one LEASE_ABSTRACTION item
               per draft for a regional manager to confirm (lease_versions.py
               says which path read the terms: the agent or the generator).
  checking     The period's charges against the *confirmed* lease rules, every
               finding proposed as a CHARGE_CHECK work item. Charges on a lease
               with no confirmed version wait, and the result says why.
  reminders    Not a monthly step: one run per business date (jobs/reminders.py)
               reminds, escalates and releases undisputed amounts for open
               questions.
"""

from typing import Any, Callable, Dict, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Connection

from . import reminders
from .lease_versions import draft_versions
from .monthly import AP_SOURCE, check_period, parse_period

Handler = Callable[[Connection, Mapping[str, Any]], Dict[str, Any]]


class HandlerError(RuntimeError):
    """A job that cannot do its work. The queue retries it, then dead-letters it."""


def _scope(payload: Mapping[str, Any]):
    try:
        return payload["entity_id"], parse_period(payload["period"])
    except KeyError as exc:
        raise HandlerError("payload is missing %s" % exc) from exc


def ingest(conn: Connection, payload: Mapping[str, Any]) -> Dict[str, Any]:
    entity_id, period = _scope(payload)
    raw = conn.execute(text("""
        SELECT count(*) FROM raw_row WHERE source = :src AND payload->>'period' = :p
    """), {"src": AP_SOURCE, "p": period.isoformat()}).scalar_one()
    charges = conn.execute(text("""
        SELECT count(*) FROM landlord_charge c JOIN clinic k ON k.id = c.clinic_id
         WHERE c.period = :p AND k.entity_id = :e
    """), {"p": period, "e": entity_id}).scalar_one()
    if raw == 0 or charges == 0:
        raise HandlerError("nothing ingested for %s %s (%d raw rows, %d charges); run `make seed`"
                           % (entity_id, period.strftime("%Y-%m"), raw, charges))
    return {"status": "present", "raw_rows": raw, "charges": charges}


def abstraction(conn: Connection, payload: Mapping[str, Any]) -> Dict[str, Any]:
    entity_id, period = _scope(payload)
    # The history cross-check reads the cash paid before the month being run.
    return dict(status="drafted", **draft_versions(conn, entity_id, history_until=period))


def checking(conn: Connection, payload: Mapping[str, Any]) -> Dict[str, Any]:
    entity_id, period = _scope(payload)
    return dict(status="checked", **check_period(conn, entity_id, period))


HANDLERS: Dict[str, Handler] = {
    "ingest": ingest,
    "abstraction": abstraction,
    "checking": checking,
    "reminders": reminders.handler,     # busy approvers: remind, escalate, pay undisputed
}


def handler_for(kind: str, registry: Mapping[str, Handler] = HANDLERS) -> Handler:
    try:
        return registry[kind]
    except KeyError:
        raise HandlerError("no handler for job kind %r (known: %s)"
                           % (kind, ", ".join(sorted(registry)))) from None
