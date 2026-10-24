"""Busy approvers: reminders, escalation, and paying what nobody disputes.

    python -m app.jobs.reminders [--date 2026-01-09]     # enqueue today's run
    make worker                                          # the worker runs it

A question the resolver asks is due QUESTION_DUE_BUSINESS_DAYS business days
after it was asked, on the business clock (jobs/clock.py), never the wall
clock. The `reminders` job, run by the worker as `lease_agent`, walks every
open question that has a due date and, for the business date it runs on:

  remind     every REMIND_EVERY_BUSINESS_DAYS business days after the question
             was asked, one reminder to whoever it was asked to. A clock that
             jumped ahead sends one catch-up reminder, not a burst.
  escalate   once ESCALATE_AFTER_BUSINESS_DAYS business days pass unanswered,
             the question escalates to the entity's controller (who may answer
             any item). Reminders stop; the controller sees it in
             GET /api/questions?mine=1.
  pay        if the invoice's payment due date arrives while the question is
             still open, the undisputed portion proceeds: a PAYMENT_RELEASE
             work item for exactly charges.payable()'s undisputed amount is
             proposed to the AP clerk, and the disputed rest stays held on the
             original item. Nothing undisputed (a duplicate, an unleased suite)
             means nothing proceeds, and that is on record too.

Every reminder, escalation and payment-due decision is an audit event on the
question (`subject_type = 'question'`), hash-chained like everything else and
invisible to the work-item projection, so replay is unchanged. The events are
also how the job stays idempotent: a reminder number, an escalation or a
payment-due decision already on record is never written twice, so the job can
run any number of times on the same business date.
"""

import argparse
import sys
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..work import charges
from ..work.events import append_event
from ..work.resolver import (
    CONTROLLER,
    ESCALATE_AFTER_BUSINESS_DAYS,
    QUESTION_DUE_BUSINESS_DAYS,
    REMIND_EVERY_BUSINESS_DAYS,
    RESOLVER_ACTOR,
    actor_for,
    business_days_between,
)
from ..work.roles import load_actor
from ..work.transitions import create_item, load_item, transition
from . import clock
from .queue import enqueue

KIND = "reminders"
SUBJECT = "question"
RELEASE_KIND = "PAYMENT_RELEASE"


def job_key(business_date: date) -> str:
    return "%s:%s" % (KIND, business_date.isoformat())


def schedule(conn: Connection, business_date: Optional[date] = None) -> int:
    """Enqueue the run for one business date (default: the clock's). Once per date."""
    d = business_date or clock.today(conn)
    return enqueue(conn, KIND, {"business_date": d.isoformat()}, idempotency_key=job_key(d))


def handler(conn: Connection, payload: Mapping[str, Any]) -> Dict[str, Any]:
    raw = payload.get("business_date")
    return run(conn, date.fromisoformat(raw) if raw else None)


def run(conn: Connection, today: Optional[date] = None, *,
        every: int = REMIND_EVERY_BUSINESS_DAYS,
        sla: int = ESCALATE_AFTER_BUSINESS_DAYS) -> Dict[str, Any]:
    """One pass over the open questions for `today` (default: the business clock)."""
    today = today or clock.today(conn)
    actor = load_actor(conn, RESOLVER_ACTOR)
    counts = {"business_date": today.isoformat(), "open": 0, "reminded": 0, "escalated": 0,
              "released": 0, "nothing_undisputed": 0}
    for q in open_questions(conn):
        counts["open"] += 1
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                     {"k": "question|%s" % q["id"]})
        history = _history(conn, q["id"])
        asked_on = asked_on_of(conn, q)
        elapsed = business_days_between(asked_on, today)
        asked_role = _role(conn, q["asked_to"])
        base = {"question_id": q["id"], "work_item_id": q["work_item_id"],
                "business_date": today.isoformat(), "asked_on": asked_on.isoformat(),
                "due_on": q["due_at"].date().isoformat(), "business_days_open": elapsed,
                "amount_at_stake": _stake(q)}

        if (elapsed >= sla and "escalate" not in history and asked_role != CONTROLLER):
            to = actor_for(conn, CONTROLLER, entity_id=q["entity_id"])
            if to is not None:
                append_event(conn, actor_id=actor.id, action="escalate", subject_type=SUBJECT,
                             subject_id=q["id"], reason=(
                                 "No answer from %s after %d business days (SLA %d); "
                                 "escalated to the controller %s." % (
                                     q["asked_to"], elapsed, sla, to)),
                             evidence=dict(base, escalated_to=to, escalated_from=q["asked_to"],
                                           sla_business_days=sla))
                counts["escalated"] += 1
                history["escalate"] = [to]
        elif "escalate" not in history and elapsed >= every:
            n = elapsed // every
            if n > max(history.get("remind", [0])):
                overdue = today > q["due_at"].date()
                append_event(conn, actor_id=actor.id, action="remind", subject_type=SUBJECT,
                             subject_id=q["id"], reason=(
                                 "Reminder %d to %s: %s, %d business day(s) after it was asked."
                                 % (n, q["asked_to"], "overdue since %s" % base["due_on"]
                                    if overdue else "due %s" % base["due_on"], elapsed)),
                             evidence=dict(base, n=n, to=q["asked_to"], overdue=overdue))
                counts["reminded"] += 1

        if "payment_due" not in history:
            outcome = _payment_due(conn, actor, q, today, base)
            if outcome is not None:
                counts[outcome] += 1
    return counts


def open_questions(conn: Connection) -> List[Mapping[str, Any]]:
    """Unanswered questions that have a due date: the ones with an SLA."""
    return list(conn.execute(text("""
        SELECT q.id, q.work_item_id, q.asked_to, q.asked_at, q.due_at, q.body,
               w.entity_id, w.region_id, w.clinic_id, w.period, w.state, w.title, w.evidence,
               w.subject_type, w.subject_id, w.kind, w.amount
          FROM question q JOIN work_item w ON w.id = q.work_item_id
         WHERE q.answered_by IS NULL AND q.due_at IS NOT NULL
         ORDER BY q.id
    """)).mappings())


def asked_on_of(conn: Connection, q: Mapping[str, Any]) -> date:
    """The business date the question was asked: as the ask event recorded
    it, else back-computed from the due date, else the wall-clock date."""
    recorded = conn.execute(text("""
        SELECT evidence->>'asked_on' FROM audit_event
         WHERE subject_type = 'work_item' AND subject_id = :sid AND action = 'ask' AND allowed
           AND (diff->'question'->>'id')::bigint = :qid
         ORDER BY seq DESC LIMIT 1
    """), {"sid": str(q["work_item_id"]), "qid": q["id"]}).scalar()
    if recorded:
        try:
            return date.fromisoformat(recorded)
        except ValueError:
            pass
    if q.get("due_at") is not None:
        d = q["due_at"].date()
        back = 0
        while back < QUESTION_DUE_BUSINESS_DAYS:
            d = date.fromordinal(d.toordinal() - 1)
            if d.weekday() < 5:
                back += 1
        return d
    return q["asked_at"].date()


def history_of(conn: Connection, question_id: int) -> List[Mapping[str, Any]]:
    """The reminder, escalation and payment-due events of one question, oldest first."""
    return list(conn.execute(text("""
        SELECT seq, at, actor_id, action, reason, evidence FROM audit_event
         WHERE subject_type = :st AND subject_id = :sid AND allowed
         ORDER BY seq
    """), {"st": SUBJECT, "sid": str(question_id)}).mappings())


def _history(conn: Connection, question_id: int) -> Dict[str, list]:
    out: Dict[str, list] = {}
    for e in history_of(conn, question_id):
        ev = e["evidence"] or {}
        if e["action"] == "remind":
            out.setdefault("remind", []).append(int(ev.get("n") or 0))
        elif e["action"] == "escalate":
            out.setdefault("escalate", []).append(ev.get("escalated_to"))
        elif e["action"] == "payment_due":
            out.setdefault("payment_due", []).append(ev.get("release_item_id"))
    return out


def _payment_due(conn: Connection, actor, q: Mapping[str, Any], today: date,
                 base: Mapping[str, Any]) -> Optional[str]:
    """Pay the undisputed portion once the invoice falls due, if still unanswered."""
    evidence = q["evidence"] if isinstance(q["evidence"], dict) else {}
    raw_due = evidence.get("payment_due")
    try:
        payment_due = date.fromisoformat(raw_due) if raw_due else None
    except (TypeError, ValueError):
        payment_due = None
    if payment_due is None or today < payment_due:
        return None
    if q["kind"] != charges.CHARGE_CHECK or q["subject_type"] != "landlord_charge":
        return None
    item = load_item(conn, q["work_item_id"])
    billed = conn.execute(text("SELECT amount FROM landlord_charge WHERE id = :id"),
                          {"id": item["subject_id"]}).scalar()
    # The same arithmetic an upheld hold uses: only what the lease supports.
    pay = charges.payable(dict(item, evidence=dict(evidence, resolution=charges.UPHELD),
                               proposal=charges.HOLD), billed)
    info = dict(base, payment_due=payment_due.isoformat(), billed=str(billed),
                undisputed=str(pay.amount), disputed=str(pay.disputed))
    if pay.amount <= 0:
        append_event(conn, actor_id=actor.id, action="payment_due", subject_type=SUBJECT,
                     subject_id=q["id"], reason=(
                         "Payment was due %s and the question is unanswered, but nothing in "
                         "this charge is undisputed; all %s stays held." % (
                             payment_due.isoformat(), _money(pay.disputed))),
                     evidence=dict(info, release_item_id=None))
        return "nothing_undisputed"

    release = create_item(
        conn, actor, kind=RELEASE_KIND, subject_type="landlord_charge",
        subject_id=item["subject_id"], entity_id=item["entity_id"], region_id=item["region_id"],
        clinic_id=item["clinic_id"], period=item["period"], amount=pay.amount,
        title="Release the undisputed %s of %s" % (_money(pay.amount), item["title"]),
        evidence={"charge_check_item_id": item["id"], "question_id": q["id"],
                  "charge_id": item["subject_id"], "billed": float(billed or 0),
                  "undisputed": float(pay.amount), "disputed": float(pay.disputed),
                  "payment_due": payment_due.isoformat(), "basis": pay.basis})
    reason = ("Payment was due %s and %s has not answered: the undisputed %s proceeds to AP; "
              "the disputed %s stays held on item %s." % (
                  payment_due.isoformat(), q["asked_to"], _money(pay.amount),
                  _money(pay.disputed), item["id"]))
    if release["state"] == "NEW":
        transition(conn, actor, release["id"], "propose", reason=reason,
                   patch={"proposal": "approve", "reason": reason})
    append_event(conn, actor_id=actor.id, action="payment_due", subject_type=SUBJECT,
                 subject_id=q["id"], reason=reason,
                 evidence=dict(info, release_item_id=release["id"]))
    return "released"


def _role(conn: Connection, actor_id: str) -> Optional[str]:
    return conn.execute(text("SELECT role FROM actor WHERE id = :id"), {"id": actor_id}).scalar()


def _stake(q: Mapping[str, Any]) -> Optional[float]:
    ev = q["evidence"] if isinstance(q["evidence"], dict) else {}
    route = ev.get("route") if isinstance(ev.get("route"), dict) else {}
    value = route.get("amount_at_stake")
    return float(value) if isinstance(value, (int, float)) else None


def _money(value: Any) -> str:
    return "${:,.2f}".format(Decimal(str(value)))


def main(argv=None) -> int:
    from ..db.engine import engine

    parser = argparse.ArgumentParser(description="Enqueue the reminders run for a business date")
    parser.add_argument("--date", help="YYYY-MM-DD; default: the business clock")
    args = parser.parse_args(argv)
    try:
        d = date.fromisoformat(args.date) if args.date else None
    except ValueError:
        print("reminders: --date must be YYYY-MM-DD", file=sys.stderr)
        return 2
    with engine("lease_agent").begin() as conn:
        job_id = schedule(conn, d)
    print("  reminders job #%d" % job_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
