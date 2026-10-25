"""The run summary of one month, for the guided stepper (PHASE_3.md group 2).

    GET /api/summary/month?period=2026-01&entity=ENT-CA

"January 2026, Northbay Coffee Company of California, Inc.: 5 stores,
12 charges checked, 0 approved, 5 held for $25,736.36, 0 disputes drafted,
0 questions out, batch ready for AP: no", as structured JSON in which every
number carries its drill-down, so the UI can make each one clickable:

    {"period": "2026-01-01", "month": "January 2026", "entity_id": "ENT-CA",
     "entity_name": "...", "headline": "...",
     "metrics": {
        "held": {"value": 5, "amount": 25736.36, "label": "held",
                 "drill": {"endpoint": "/api/summary/month/items",
                           "params": {"period": "2026-01", "entity": "ENT-CA", "metric": "held"},
                           "filter": {"kind": "CHARGE_CHECK", "period": "2026-01-01",
                                      "entity_id": "ENT-CA", "proposal": "hold",
                                      "state": ["NEW", "PROPOSED", "NEEDS_INFO", "HELD"]}}},
        ...},
     "batch": {"ready": false, "released": false, "awaiting_decision": 12, ...}}

`drill.endpoint` + `drill.params` returns exactly the rows the number counts
(month_items below); `drill.filter` says the same thing declaratively.

Read from existing tables only, with the same definitions the rest of the API
uses, so the numbers agree with the dashboard:

  clinics    clinics of the entity billed in the month (landlord_charge)
  checked    CHARGE_CHECK work items of the month
  approved   of those, signed off by a person: APPROVED or POSTED, or CLOSED
             after an allowed approve (the gateway closes an upheld hold
             with nothing payable)
  held       open holds, as /api/summary counts them: proposal `hold`, not yet
             resolved (NEW, PROPOSED, NEEDS_INFO, HELD); `amount` is the
             over-bills only, the positive variances, summed in Decimal from
             the figures /api/exceptions shows ($25,736.36 for January)
  disputes   work items of kind DISPUTE in the month (0 until disputes land)
  questions  unanswered questions on the month's work items
  batch      ready for AP when no charge check of the month awaits a decision
             and something is payable (gateway._releasable, the amounts the
             batch would pay); `released` once the outbox holds the batch

Unscoped like /api/summary: a signed-in person sees the whole month. A blank
`entity` means every entity.
"""

import calendar
import re
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..api.exceptions import exception_id, open_exceptions
from ..work import gateway

METRICS = ("clinics", "checked", "approved", "held", "disputes", "questions", "batch")
UNDECIDED = ("NEW", "PROPOSED", "NEEDS_INFO")
OPEN_HOLD_STATES = ("NEW", "PROPOSED", "NEEDS_INFO", "HELD")
APPROVED_STATES = ("APPROVED", "POSTED")
DISPUTE_KINDS = ("DISPUTE",)
ENDPOINT = "/api/summary/month/items"

_PERIOD = re.compile(r"^(\d{4})-(\d{2})(?:-01)?$")
_UNRESOLVED_STATUS = ("exception", "pending_review", "escalated")   # api/summary.py


class BadPeriod(ValueError):
    pass


def parse_month(raw: str) -> date:
    match = _PERIOD.match(raw or "")
    try:
        if match is None:
            raise ValueError
        return date(int(match.group(1)), int(match.group(2)), 1)
    except ValueError:
        raise BadPeriod("period must be YYYY-MM or YYYY-MM-01, got %r" % raw) from None


# ------------------------------------------------------------------ the rows

_ENTITY_OF_ITEM = "coalesce(w.entity_id, k.entity_id)"


def _checks(conn: Connection, period: date, entity_id: Optional[str]) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute(text("""
        SELECT w.id, w.state, w.proposal, w.clinic_id, w.title, w.amount, w.evidence,
               %s AS entity_id,
               EXISTS (SELECT 1 FROM audit_event e
                        WHERE e.subject_type = 'work_item' AND e.subject_id = w.id::text
                          AND e.action = 'approve' AND e.allowed) AS approved_ever
          FROM work_item w LEFT JOIN clinic k ON k.id = w.clinic_id
         WHERE w.kind = 'CHARGE_CHECK' AND w.period = :p
           AND (CAST(:e AS text) IS NULL OR %s = :e)
         ORDER BY w.id
    """ % (_ENTITY_OF_ITEM, _ENTITY_OF_ITEM)), {"p": period, "e": entity_id}).mappings()]


def _is_approved(row: Dict[str, Any]) -> bool:
    return row["state"] in APPROVED_STATES or (row["state"] == "CLOSED" and row["approved_ever"])


def _variance(row: Dict[str, Any]) -> Optional[float]:
    ev = row.get("evidence") or {}
    billed, supported = ev.get("billed"), ev.get("supported")
    if billed is None or supported is None:
        return None
    return float((Decimal(str(billed)) - Decimal(str(supported))).quantize(Decimal("0.01")))


def _item_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "charge_check", "item_id": row["id"], "exception_id": exception_id(row["id"]),
            "state": row["state"], "proposal": row["proposal"], "clinic_id": row["clinic_id"],
            "title": row["title"], "amount": None if row["amount"] is None else float(row["amount"]),
            "variance": _variance(row)}


def _holds(conn: Connection, period: date, checks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Open holds of the month, exactly as /api/summary and /api/exceptions see them."""
    ids = {exception_id(r["id"]) for r in checks}
    return [e for e in open_exceptions(conn)
            if e["exception_id"] in ids and e["status"] in _UNRESOLVED_STATUS]


def _clinics(conn: Connection, period: date, entity_id: Optional[str]) -> List[Dict[str, Any]]:
    return [{"type": "clinic", **dict(r)} for r in conn.execute(text("""
        SELECT k.id AS clinic_id, k.name, count(c.id) AS charges
          FROM landlord_charge c JOIN clinic k ON k.id = c.clinic_id
         WHERE c.period = :p AND (CAST(:e AS text) IS NULL OR k.entity_id = :e)
         GROUP BY k.id, k.name ORDER BY k.id
    """), {"p": period, "e": entity_id}).mappings()]


def _disputes(conn: Connection, period: date, entity_id: Optional[str]) -> List[Dict[str, Any]]:
    return [{"type": "dispute", **dict(r)} for r in conn.execute(text("""
        SELECT w.id AS item_id, w.state, w.clinic_id, w.title, w.amount::float AS amount
          FROM work_item w LEFT JOIN clinic k ON k.id = w.clinic_id
         WHERE w.kind = ANY(:kinds) AND w.period = :p
           AND (CAST(:e AS text) IS NULL OR %s = :e)
         ORDER BY w.id
    """ % _ENTITY_OF_ITEM), {"kinds": list(DISPUTE_KINDS), "p": period, "e": entity_id}).mappings()]


def _questions(conn: Connection, period: date, entity_id: Optional[str]) -> List[Dict[str, Any]]:
    rows = conn.execute(text("""
        SELECT q.id AS question_id, q.work_item_id AS item_id, w.kind, q.asked_to, q.asked_by,
               q.body, q.asked_at, q.due_at
          FROM question q JOIN work_item w ON w.id = q.work_item_id
          LEFT JOIN clinic k ON k.id = w.clinic_id
         WHERE q.answered_by IS NULL AND w.period = :p
           AND (CAST(:e AS text) IS NULL OR %s = :e)
         ORDER BY q.id
    """ % _ENTITY_OF_ITEM), {"p": period, "e": entity_id}).mappings()
    return [{"type": "question", **dict(r),
             "exception_id": exception_id(r["item_id"]) if r["kind"] == "CHARGE_CHECK" else None}
            for r in rows]


def _batch(conn: Connection, period: date, entity_id: Optional[str],
           checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    entities = [entity_id] if entity_id else sorted({r["entity_id"] for r in checks if r["entity_id"]})
    releasable: List[Dict[str, Any]] = []
    released = []
    for ent in entities:
        releasable.extend(gateway._releasable(conn, ent, period))
        key = "ap_batch:%s:%s" % (ent, period.strftime("%Y-%m"))
        if conn.execute(text("SELECT 1 FROM outbox WHERE idempotency_key = :k"), {"k": key}).first():
            released.append(ent)
    awaiting = sum(1 for r in checks if r["state"] in UNDECIDED)
    total = sum((Decimal(r["amount"]) for r in releasable), Decimal("0"))
    return {
        "ready": bool(entities) and awaiting == 0 and (bool(releasable) or len(released) == len(entities)),
        "released": bool(entities) and len(released) == len(entities),
        "awaiting_decision": awaiting,
        "releasable": len(releasable),
        "releasable_total": float(total.quantize(Decimal("0.01"))),
        "rows": [{"type": "payable", "item_id": r["work_item_id"],
                  "exception_id": exception_id(r["work_item_id"]), "clinic_id": r["clinic_id"],
                  "charge_type": r["charge_type"], "landlord_name": r["landlord_name"],
                  "billed": float(r["billed"]), "amount": float(r["amount"])} for r in releasable],
    }


# ---------------------------------------------------------------- the summary

def _entity_name(conn: Connection, entity_id: Optional[str]) -> Optional[str]:
    if entity_id:
        return conn.execute(text("SELECT name FROM entity WHERE id = :e"), {"e": entity_id}).scalar()
    names = list(conn.execute(text("SELECT name FROM entity ORDER BY id")).scalars())
    return names[0] if len(names) == 1 else "all entities"


class UnknownEntity(LookupError):
    pass


def _money(value: float) -> str:
    return "${:,.2f}".format(value)


def month_summary(conn: Connection, period: date, entity_id: Optional[str] = None) -> Dict[str, Any]:
    entity_id = entity_id or None
    name = _entity_name(conn, entity_id)
    if name is None:
        raise UnknownEntity("no entity %r" % entity_id)
    checks = _checks(conn, period, entity_id)
    holds = _holds(conn, period, checks)
    over = [Decimal(str(e["delta"])) for e in holds if e["delta"] is not None and e["delta"] > 0]
    held_amount = float(sum(over, Decimal("0")).quantize(Decimal("0.01")))
    batch = _batch(conn, period, entity_id, checks)
    batch.pop("rows")

    base = {"period": period.isoformat(), "entity_id": entity_id}
    month_param = period.strftime("%Y-%m")

    def drill(metric: str, **flt: Any) -> Dict[str, Any]:
        return {"endpoint": ENDPOINT,
                "params": {"period": month_param, "entity": entity_id or "", "metric": metric},
                "filter": dict(base, **flt)}

    metrics = {
        "clinics": {"value": len(_clinics(conn, period, entity_id)), "label": "stores",
                    "drill": drill("clinics", table="landlord_charge", distinct="clinic_id")},
        "checked": {"value": len(checks), "label": "charges checked",
                    "drill": drill("checked", kind="CHARGE_CHECK")},
        "approved": {"value": sum(1 for r in checks if _is_approved(r)), "label": "approved",
                     "drill": drill("approved", kind="CHARGE_CHECK",
                                    state=list(APPROVED_STATES) + ["CLOSED"], approved_by_person=True)},
        "held": {"value": len(holds), "amount": held_amount, "label": "held",
                 "drill": drill("held", kind="CHARGE_CHECK", proposal="hold", state=list(OPEN_HOLD_STATES))},
        "disputes": {"value": len(_disputes(conn, period, entity_id)), "label": "disputes drafted",
                     "drill": drill("disputes", kind=list(DISPUTE_KINDS))},
        "questions": {"value": len(_questions(conn, period, entity_id)), "label": "questions out",
                      "drill": drill("questions", table="question", answered=False)},
        "batch": {"value": batch["ready"], "label": "batch ready for AP",
                  "drill": drill("batch", kind="CHARGE_CHECK", state=list(APPROVED_STATES), payable=True)},
    }
    month_name = "%s %d" % (calendar.month_name[period.month], period.year)
    m = metrics
    headline = ("%s, %s: %d stores, %d charges checked, %d approved, %d held for %s, "
                "%d disputes drafted, %d questions out, batch ready for AP: %s" % (
                    month_name, name, m["clinics"]["value"], m["checked"]["value"],
                    m["approved"]["value"], m["held"]["value"], _money(held_amount),
                    m["disputes"]["value"], m["questions"]["value"], "yes" if batch["ready"] else "no"))
    return {"period": period.isoformat(), "month": month_name, "entity_id": entity_id,
            "entity_name": name, "headline": headline, "metrics": metrics, "batch": batch}


def month_items(conn: Connection, period: date, entity_id: Optional[str], metric: str) -> List[Dict[str, Any]]:
    """The rows behind one number of month_summary: len(rows) is that number
    (for `batch`, the payable rows)."""
    entity_id = entity_id or None
    if metric not in METRICS:
        raise ValueError("metric must be one of %s" % ", ".join(METRICS))
    if metric == "clinics":
        return _clinics(conn, period, entity_id)
    if metric == "disputes":
        return _disputes(conn, period, entity_id)
    if metric == "questions":
        return _questions(conn, period, entity_id)
    checks = _checks(conn, period, entity_id)
    if metric == "checked":
        return [_item_row(r) for r in checks]
    if metric == "approved":
        return [_item_row(r) for r in checks if _is_approved(r)]
    if metric == "held":
        held = {e["exception_id"]: e for e in _holds(conn, period, checks)}
        return [dict(_item_row(r), variance=held[exception_id(r["id"])]["delta"])
                for r in checks if exception_id(r["id"]) in held]
    return _batch(conn, period, entity_id, checks)["rows"]
