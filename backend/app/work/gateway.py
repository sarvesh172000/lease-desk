"""The gateway: the only code that writes back to the books and to AP.

Three doors, each on a `lease_gateway` connection, the only database role
with INSERT on journal_* and outbox:

  post_journal()   an APPROVED work item becomes a balanced journal entry,
                   then POSTED. A repeated idempotency key returns the
                   original entry and posts nothing.
  release_batch()  an AP clerk releases the period's approved charges as one
                   payment batch file, written to the outbox. The system
                   never pays: the batch is a file AP acts on.
  send_outbox()    delivers pending outbox rows exactly once, even when two
                   senders run at the same time.

post_journal() and release_batch() work inside the caller's transaction, like
append_event(), so the entry, the state change and its event commit or roll
back together. A *denied* release is the exception: its audit event is written
in a transaction of its own, so the refusal is on record even though the
caller's transaction rolls back when the error propagates.
"""

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Union

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..ledger import posting
from ..ledger.posting import PeriodClosed, PostingError  # noqa: F401  re-exported
from .events import append_event

GATEWAY_ACTOR = "system:gateway"
AP_CLERK = "ap_clerk"
CHARGE_CHECK = "CHARGE_CHECK"
RELEASABLE_STATES = ("APPROVED", "POSTED")
MAX_SEND_ATTEMPTS = 3


class GatewayError(Exception):
    """The gateway refused. Nothing was written in the caller's transaction."""


class WrongState(GatewayError):
    """The work item is not in a state this door accepts."""


class NotAllowed(GatewayError):
    """The actor may not do this. A denied event is on record."""


# ------------------------------------------------------------------ posting

def post_journal(conn: Connection, item_id: int, lines: Iterable[Any], idempotency_key: str,
                 *, entity_id: str, date: date, period: date, memo: str,
                 entry_type: str = "standard") -> int:
    """Post a balanced entry for an APPROVED work item and move it to POSTED.

    `lines` name accounts by their chart name ("Lease cost"); see
    ledger/posting.normalize_lines for the accepted shapes. Returns the
    journal entry id. A key that already posted returns that entry's id and
    changes nothing, whatever state the item is in now.
    """
    checked = posting.normalize_lines(lines)               # before touching the DB
    posting.check_dates(date, period)
    _require_text(idempotency_key, "idempotency_key")
    _require_text(memo, "memo")
    _require_text(entity_id, "entity_id")

    earlier = posting.existing_entry(conn, idempotency_key)
    if earlier is not None:
        return _replay(earlier, item_id, idempotency_key)

    item = _lock_item(conn, item_id)
    # Look again now that the lock is held: a concurrent post with the same key
    # may have committed while we waited, and READ COMMITTED now shows it. Only
    # then does a POSTED item mean the wrong state rather than "already done".
    earlier = posting.existing_entry(conn, idempotency_key)
    if earlier is not None:
        return _replay(earlier, item_id, idempotency_key)
    if item["state"] != "APPROVED":
        raise WrongState("work item %s is %s; only APPROVED items post"
                         % (item_id, item["state"]))
    if item["entity_id"] is not None and item["entity_id"] != entity_id:
        raise GatewayError("work item %s belongs to entity %s, not %s"
                           % (item_id, item["entity_id"], entity_id))
    posting.require_open_period(conn, entity_id, period)

    result = posting.write_entry(
        conn, entity_id=entity_id, entry_date=date, period=period, memo=memo,
        entry_type=entry_type, idempotency_key=idempotency_key, work_item_id=item_id,
        lines=checked)
    if not result.created:                                   # lost a race to the same key
        return _replay(posting.existing_entry(conn, idempotency_key), item_id, idempotency_key)
    _mark_posted(conn, item_id, result.entry_id)
    return result.entry_id


def post_approved_charge(conn: Connection, item_id: int) -> int:
    """Post the engine's entry for an approved CHARGE_CHECK item: an approved
    January rent charge becomes Dr Lease cost / Cr Accounts payable, entry
    type `phase1_period_cost` (engine/journal.py says why that is a
    placeholder)."""
    item = _item(conn, item_id)
    if item["kind"] != CHARGE_CHECK or item["subject_type"] != "landlord_charge":
        raise GatewayError("work item %s is a %s on %s, not a landlord charge check"
                           % (item_id, item["kind"], item["subject_type"]))
    entry = posting.entry_for_charge(conn, item["subject_id"])
    return post_journal(
        conn, item_id, entry.lines, entry.idempotency_key, entity_id=entry.entity_id,
        date=entry.period, period=entry.period, memo=entry.memo, entry_type=entry.entry_type)


def _mark_posted(conn: Connection, item_id: int, entry_id: int) -> None:
    # Integration swaps this for work.transitions.transition(item, "post", ...).
    event = append_event(
        conn, actor_id=GATEWAY_ACTOR, action="post", subject_type="work_item",
        subject_id=str(item_id), diff={"from": "APPROVED", "to": "POSTED", "set": {}},
        evidence={"journal_entry_id": entry_id})
    conn.execute(text("""
        UPDATE work_item SET state = 'POSTED', updated_at = :at, last_event_seq = :seq
         WHERE id = :id AND state = 'APPROVED'
    """), {"at": event.at, "seq": event.seq, "id": item_id})


def _replay(earlier: Mapping, item_id: int, key: str) -> int:
    if earlier["work_item_id"] is not None and earlier["work_item_id"] != item_id:
        raise GatewayError("idempotency key %r already posted entry %s for work item %s, not %s"
                           % (key, earlier["id"], earlier["work_item_id"], item_id))
    return earlier["id"]


def _item(conn: Connection, item_id: int, lock: bool = False) -> Mapping:
    if isinstance(item_id, bool) or not isinstance(item_id, int):
        raise GatewayError("work item id must be an integer, got %r" % (item_id,))
    row = conn.execute(text(
        "SELECT id, kind, state, subject_type, subject_id, entity_id, period "
        "FROM work_item WHERE id = :id" + (" FOR UPDATE" if lock else "")),
        {"id": item_id}).mappings().first()
    if row is None:
        raise GatewayError("no work item %s" % item_id)
    return row


def _lock_item(conn: Connection, item_id: int) -> Mapping:
    """Row-lock the item so two posts of different keys cannot both see APPROVED."""
    return _item(conn, item_id, lock=True)


def _require_text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PostingError("%s is required" % name)


# ------------------------------------------------------------- AP batches

@dataclass(frozen=True)
class Batch:
    outbox_id: int
    idempotency_key: str
    created: bool          # False when this period's batch was already released
    item_count: int
    total: Decimal


CSV_COLUMNS = ("work_item_id", "charge_id", "invoice_id", "landlord_id", "landlord_name",
               "lease_id", "clinic_id", "charge_type", "period", "amount")


def release_batch(conn: Connection, period: date, actor_id: str,
                  *, entity_id: Optional[str] = None) -> Batch:
    """Release one AP payment batch for an entity and period, through the outbox.

    Only an active actor with role `ap_clerk` may; anyone else is refused and
    the refusal is recorded. The batch holds every APPROVED or POSTED charge
    check of the period. `entity_id` defaults to the clerk's own entity.
    Releasing again returns the batch already released and adds nothing.
    """
    if not isinstance(period, date) or period.day != 1:
        raise GatewayError("period must be the first of a month, got %r" % (period,))
    who = _actor(conn, actor_id)
    entity_id = entity_id or (who or {}).get("entity_id")
    key = "ap_batch:%s:%s" % (entity_id or "*", period.strftime("%Y-%m"))

    refusal = _release_refusal(who, actor_id, entity_id)
    if refusal:
        _record_denial(conn, actor_id, key, refusal, period)
        raise NotAllowed(refusal)

    existing = _outbox_row(conn, key)
    if existing is not None:
        return _batch_from(existing, created=False)

    rows = _releasable(conn, entity_id, period)
    if not rows:
        raise GatewayError("nothing to release: no approved charges for %s in %s"
                           % (entity_id, period.strftime("%Y-%m")))
    payload = _batch_payload(rows, entity_id, period, actor_id)
    outbox_id = conn.execute(text("""
        INSERT INTO outbox (kind, payload, idempotency_key)
        VALUES ('ap_batch', CAST(:payload AS jsonb), :key)
        ON CONFLICT (idempotency_key) DO NOTHING RETURNING id
    """), {"payload": _json(payload), "key": key}).scalar()
    if outbox_id is None:                                   # a concurrent release won
        return _batch_from(_outbox_row(conn, key), created=False)

    append_event(conn, actor_id=actor_id, action="release_batch", subject_type="ap_batch",
                 subject_id=key, evidence={"outbox_id": outbox_id,
                                           "work_item_ids": [r["work_item_id"] for r in rows],
                                           "total": payload["total"]})
    return Batch(outbox_id=outbox_id, idempotency_key=key, created=True,
                 item_count=len(rows), total=Decimal(payload["total"]))


def _release_refusal(who: Optional[Mapping], actor_id: str,
                     entity_id: Optional[str]) -> Optional[str]:
    if who is None:
        return "unknown actor %r cannot release a payment batch" % (actor_id,)
    if not who["active"]:
        return "actor %s is inactive" % actor_id
    if who["role"] != AP_CLERK:
        return "only an AP clerk releases payment batches; %s is %s" % (actor_id, who["role"])
    if entity_id is None:
        return "name the entity: %s may release for every entity" % actor_id
    if who["entity_id"] is not None and who["entity_id"] != entity_id:
        return "%s releases for entity %s, not %s" % (actor_id, who["entity_id"], entity_id)
    return None


def _record_denial(conn: Connection, actor_id: str, key: str, reason: str, period: date) -> None:
    """On its own transaction, so the caller's rollback cannot erase it."""
    with conn.engine.begin() as own:
        append_event(own, actor_id=str(actor_id), action="release_batch",
                     subject_type="ap_batch", subject_id=key, allowed=False, reason=reason,
                     evidence={"period": period.isoformat()})


def _actor(conn: Connection, actor_id: Any) -> Optional[Dict]:
    if not isinstance(actor_id, str) or not actor_id:
        return None
    row = conn.execute(text("SELECT id, role, entity_id, active FROM actor WHERE id = :id"),
                       {"id": actor_id}).mappings().first()
    return dict(row) if row else None


def _releasable(conn: Connection, entity_id: str, period: date) -> List[Mapping]:
    return conn.execute(text("""
        SELECT w.id AS work_item_id, c.id AS charge_id, c.invoice_id, l.landlord_id,
               d.name AS landlord_name, c.lease_id, c.clinic_id, c.charge_type,
               c.period, c.amount
          FROM work_item w
          JOIN landlord_charge c ON c.id = w.subject_id
          JOIN clinic k ON k.id = c.clinic_id
          JOIN lease l ON l.id = c.lease_id
          JOIN landlord d ON d.id = l.landlord_id
         WHERE w.kind = :kind AND w.subject_type = 'landlord_charge'
           AND w.state IN ('APPROVED', 'POSTED')
           AND c.period = :period AND coalesce(w.entity_id, k.entity_id) = :entity
         ORDER BY d.name, c.clinic_id, c.invoice_id, c.id
    """), {"kind": CHARGE_CHECK, "period": period, "entity": entity_id}).mappings().all()


def _batch_payload(rows: List[Mapping], entity_id: str, period: date, actor_id: str) -> Dict:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    by_landlord: Dict[str, Decimal] = {}
    for r in rows:
        writer.writerow([r[c] if c != "period" else r[c].isoformat() for c in CSV_COLUMNS])
        by_landlord[r["landlord_id"]] = by_landlord.get(r["landlord_id"], Decimal("0")) + r["amount"]
    total = sum((r["amount"] for r in rows), Decimal("0"))
    return {"entity_id": entity_id, "period": period.isoformat(), "released_by": actor_id,
            "item_count": len(rows), "total": str(total),
            "by_landlord": {k: str(v) for k, v in sorted(by_landlord.items())},
            "csv": buf.getvalue()}


def _outbox_row(conn: Connection, key: str) -> Optional[Mapping]:
    return conn.execute(text("SELECT id, idempotency_key, payload FROM outbox "
                             "WHERE idempotency_key = :k"), {"k": key}).mappings().first()


def _batch_from(row: Mapping, created: bool) -> Batch:
    payload = row["payload"]
    return Batch(outbox_id=row["id"], idempotency_key=row["idempotency_key"], created=created,
                 item_count=payload.get("item_count", 0),
                 total=Decimal(payload.get("total", "0")))


# ------------------------------------------------------------------ outbox

def _deliver_ap_batch(row: Mapping, out_dir: Path) -> None:
    """Write the batch file atomically: a crash mid-write leaves no half file,
    and re-delivering after a crash before commit rewrites the same name."""
    target = out_dir / ("%s.csv" % safe_filename(row["idempotency_key"]))
    tmp = target.with_suffix(".csv.tmp")
    tmp.write_text(row["payload"]["csv"])
    tmp.replace(target)


DELIVERERS: Dict[str, Callable[[Mapping, Path], None]] = {"ap_batch": _deliver_ap_batch}


def safe_filename(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", key).strip("._") or "outbox"


def send_outbox(conn: Connection, out_dir: Union[str, Path],
                max_attempts: int = MAX_SEND_ATTEMPTS) -> List[int]:
    """Deliver every pending outbox row once; return the ids sent by this call.

    Each row is claimed with FOR UPDATE SKIP LOCKED, delivered, and marked in
    its own transaction, so a concurrent sender skips it rather than sending
    it again. A failed delivery counts an attempt; after `max_attempts` the row
    is marked failed. This function commits, so pass a connection with no
    work of its own in progress.
    """
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if conn.in_transaction():
        conn.commit()
    sent: List[int] = []
    tried: List[int] = []
    while True:
        row = _claim(conn, tried)
        if row is None:
            conn.commit()
            return sent
        tried.append(row["id"])
        try:
            DELIVERERS[row["kind"]](row, out)
        except Exception:                                   # noqa: BLE001  any failure counts
            _mark_failed_attempt(conn, row, max_attempts)
        else:
            conn.execute(text("UPDATE outbox SET status = 'sent', sent_at = now(), "
                              "attempts = attempts + 1 WHERE id = :id"), {"id": row["id"]})
            sent.append(row["id"])
        conn.commit()


def _claim(conn: Connection, tried: List[int]) -> Optional[Mapping]:
    return conn.execute(text("""
        SELECT id, kind, payload, idempotency_key, attempts FROM outbox
         WHERE status = 'pending' AND NOT (id = ANY(:tried))
         ORDER BY id LIMIT 1
           FOR UPDATE SKIP LOCKED
    """), {"tried": tried}).mappings().first()


def _mark_failed_attempt(conn: Connection, row: Mapping, max_attempts: int) -> None:
    status = "failed" if row["attempts"] + 1 >= max_attempts else "pending"
    conn.execute(text("UPDATE outbox SET attempts = attempts + 1, status = :s WHERE id = :id"),
                 {"s": status, "id": row["id"]})


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)
