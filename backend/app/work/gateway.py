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

post_approved() posts every APPROVED charge check of an entity and period
through post_approved_charge(); the API calls it after approvals and
`make post M=YYYY-MM` runs it from the command line:

    python -m app.work.gateway --period 2026-01 [--entity ENT-CA]

Moving an item to POSTED is a work-layer transition like any other:
transitions.transition(..., 'post') as the gateway's own actor
(`system:gateway`), so the event is hash-chained and replay rebuilds it.

post_journal() and release_batch() work inside the caller's transaction, like
append_event(), so the entry, the state change and its event commit or roll
back together. A *denied* release is the exception: its audit event is written
in a transaction of its own, so the refusal is on record even though the
caller's transaction rolls back when the error propagates.
"""

import argparse
import csv
import io
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Union

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..ledger import posting
from ..ledger.posting import PeriodClosed, PostingError  # noqa: F401  re-exported
from . import charges
from .events import append_event
from .roles import GATEWAY_ACTOR, ensure_gateway_actor, load_actor
from .transitions import transition

AP_CLERK = "ap_clerk"
CHARGE_CHECK = "CHARGE_CHECK"
RELEASABLE_STATES = ("APPROVED", "POSTED")
ACCOUNTS_PAYABLE = "Accounts payable"
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
                 entry_type: str = "standard",
                 post_evidence: Optional[Mapping] = None) -> int:
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
    _mark_posted(conn, item_id, result.entry_id, post_evidence)
    return result.entry_id


def post_approved_charge(conn: Connection, item_id: int) -> Optional[int]:
    """Post the engine's entry for an approved CHARGE_CHECK item: an approved
    January rent charge becomes Dr Lease cost / Cr Accounts payable, entry
    type `phase1_period_cost` (engine/journal.py says why that is a
    placeholder).

    How much posts is charges.payable(): what was billed for a charge the
    checker found correct; for a hold a person upheld, only the undisputed
    (`supported`) amount, under its own `|supported` key; the billed amount
    of a hold only when a controller's pay-as-billed override is on record,
    under `|as_billed`. A hold upheld on a wholly unsupported charge has
    nothing to post: the item is closed and None returned. The disputed
    dollars never reach the ledger.
    """
    item = _item(conn, item_id)
    if item["kind"] != CHARGE_CHECK or item["subject_type"] != "landlord_charge":
        raise GatewayError("work item %s is a %s on %s, not a landlord charge check"
                           % (item_id, item["kind"], item["subject_type"]))
    billed = conn.execute(text("SELECT amount FROM landlord_charge WHERE id = :id"),
                          {"id": item["subject_id"]}).scalar()
    pay = charges.payable(item, billed)
    if pay.basis == charges.PAY_AS_BILLED:
        _require_override_on_record(conn, item_id)
    if pay.basis == "supported" and pay.amount <= 0:
        return _close_unpayable(conn, item_id, pay)

    entry = posting.entry_for_charge(
        conn, item["subject_id"], amount=None if pay.basis != "supported" else pay.amount,
        key_suffix=pay.key_suffix, memo_note=_MEMO_NOTE.get(pay.basis, ""))
    _refuse_a_second_entry(conn, item_id, entry.idempotency_key)
    extra = None
    if charges.is_disputed(item):
        extra = {"resolution": charges.PAY_AS_BILLED if pay.basis == charges.PAY_AS_BILLED
                 else charges.UPHELD,
                 "posted_amount": str(pay.amount), "disputed_amount": str(pay.disputed)}
    return post_journal(
        conn, item_id, entry.lines, entry.idempotency_key, entity_id=entry.entity_id,
        date=entry.period, period=entry.period, memo=entry.memo, entry_type=entry.entry_type,
        post_evidence=extra)


_MEMO_NOTE = {"supported": " (undisputed portion; disputed amount held)",
              "pay_as_billed": " (paid as billed over a hold, controller override)"}


def _require_override_on_record(conn: Connection, item_id: int) -> None:
    """The gateway's own check of a pay-as-billed resolution: the item's last
    allowed approve must be a controller's, recording the override and a
    reason. An evidence field set any other way releases nothing."""
    row = conn.execute(text("""
        SELECT e.actor_id, e.reason, e.evidence, a.role
          FROM audit_event e LEFT JOIN actor a ON a.id = e.actor_id
         WHERE e.subject_type = 'work_item' AND e.subject_id = :sid
           AND e.action = 'approve' AND e.allowed
         ORDER BY e.seq DESC LIMIT 1
    """), {"sid": str(item_id)}).mappings().first()
    evidence = (row or {}).get("evidence") or {}
    if (row is None or row["role"] != charges.OVERRIDE_ROLE
            or evidence.get("resolution") != charges.PAY_AS_BILLED
            or not (row["reason"] or "").strip()):
        raise GatewayError("work item %s is a disputed charge with no controller's pay-as-billed "
                           "approval on record; only the undisputed amount may post" % item_id)


def _refuse_a_second_entry(conn: Connection, item_id: int, key: str) -> None:
    """One entry per item. An item that already posted under another key (its
    supported amount, say, before someone tried to pay it as billed) posts
    nothing more."""
    other = conn.execute(text("""
        SELECT id, idempotency_key FROM journal_entry
         WHERE work_item_id = :id AND idempotency_key <> :key ORDER BY id LIMIT 1
    """), {"id": item_id, "key": key}).mappings().first()
    if other is not None:
        raise GatewayError("work item %s already posted entry %s under %r; refusing to post %r too"
                           % (item_id, other["id"], other["idempotency_key"], key))


def _close_unpayable(conn: Connection, item_id: int, pay: charges.Payable) -> None:
    """An upheld hold on a charge the lease does not support at all: nothing
    is owed, so nothing posts. APPROVED -> CLOSED as system:gateway, with the
    disputed amount on the event."""
    item = _lock_item(conn, item_id)
    if item["state"] != "APPROVED":
        raise WrongState("work item %s is %s; only APPROVED items post" % (item_id, item["state"]))
    transition(conn, _gateway_actor(conn), item_id, "close",
               reason="hold upheld: nothing in this charge is supported, nothing is paid",
               evidence={"resolution": charges.UPHELD, "posted_amount": "0.00",
                         "disputed_amount": str(pay.disputed)})
    return None


def _mark_posted(conn: Connection, item_id: int, entry_id: int,
                 extra: Optional[Mapping] = None) -> None:
    """APPROVED -> POSTED through the work layer, as system:gateway. The
    item is already locked and checked APPROVED by post_journal()."""
    transition(conn, _gateway_actor(conn), item_id, "post",
               evidence=dict(extra or {}, journal_entry_id=entry_id))


def _gateway_actor(conn: Connection):
    """system:gateway as an Actor. Created if missing (a fresh or emptied
    actor table); a gateway actor someone deactivated stays refused."""
    ensure_gateway_actor(conn)
    return load_actor(conn, GATEWAY_ACTOR)


@dataclass(frozen=True)
class PostedItem:
    work_item_id: int
    journal_entry_id: Optional[int]   # None: an upheld hold with nothing to post, now CLOSED


def post_approved(conn: Connection, entity_id: str, period: date) -> List[PostedItem]:
    """Post every APPROVED CHARGE_CHECK item of one entity and period, in id
    order, inside the caller's transaction (a `lease_gateway` connection).

    Idempotent: POSTED items are no longer APPROVED, so a second call finds
    nothing, and post_approved_charge() itself returns the original entry for
    a key that already posted. Held, proposed and rejected items are never
    touched. Returns what this call did, item by item: an upheld hold with
    nothing to post comes back with journal_entry_id None (it was closed).
    """
    _require_text(entity_id, "entity_id")
    if not isinstance(period, date) or period.day != 1:
        raise GatewayError("period must be the first of a month, got %r" % (period,))
    ids = conn.execute(text("""
        SELECT w.id FROM work_item w
          JOIN landlord_charge c ON c.id = w.subject_id
          JOIN clinic k ON k.id = c.clinic_id
         WHERE w.kind = :kind AND w.subject_type = 'landlord_charge' AND w.state = 'APPROVED'
           AND c.period = :period AND coalesce(w.entity_id, k.entity_id) = :entity
         ORDER BY w.id
    """), {"kind": CHARGE_CHECK, "period": period, "entity": entity_id}).scalars().all()
    return [PostedItem(item_id, post_approved_charge(conn, item_id)) for item_id in ids]


def _replay(earlier: Mapping, item_id: int, key: str) -> int:
    if earlier["work_item_id"] is not None and earlier["work_item_id"] != item_id:
        raise GatewayError("idempotency key %r already posted entry %s for work item %s, not %s"
                           % (key, earlier["id"], earlier["work_item_id"], item_id))
    return earlier["id"]


def _item(conn: Connection, item_id: int, lock: bool = False) -> Mapping:
    if isinstance(item_id, bool) or not isinstance(item_id, int):
        raise GatewayError("work item id must be an integer, got %r" % (item_id,))
    row = conn.execute(text(
        "SELECT id, kind, state, subject_type, subject_id, entity_id, period, proposal, evidence "
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
               "lease_id", "clinic_id", "charge_type", "period", "amount", "billed")


def release_batch(conn: Connection, period: date, actor_id: str,
                  *, entity_id: Optional[str] = None) -> Batch:
    """Release one AP payment batch for an entity and period, through the outbox.

    Only an active actor with role `ap_clerk` may; anyone else is refused and
    the refusal is recorded. The batch holds every APPROVED or POSTED charge
    check of the period, each for what may be paid (see _releasable): the
    undisputed amount of an upheld hold, never the disputed part. `entity_id` defaults to the clerk's own entity.
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


def _releasable(conn: Connection, entity_id: str, period: date) -> List[Dict]:
    """The period's approved and posted charge checks, each with the amount AP
    may pay: what the gateway actually credited to Accounts payable for it,
    or, for an item approved but not yet posted, what charges.payable() says
    it will post. A disputed amount is never in it, and an item with nothing
    payable is left out. `billed` keeps what the landlord asked for."""
    rows = conn.execute(text("""
        SELECT w.id AS work_item_id, c.id AS charge_id, c.invoice_id, l.landlord_id,
               d.name AS landlord_name, c.lease_id, c.clinic_id, c.charge_type,
               c.period, c.amount AS billed, w.kind, w.proposal, w.evidence,
               (SELECT sum(jl.credit) FROM journal_entry je
                  JOIN journal_line jl ON jl.journal_entry_id = je.id
                  JOIN account a ON a.id = jl.account_id
                 WHERE je.work_item_id = w.id AND a.name = :ap) AS posted
          FROM work_item w
          JOIN landlord_charge c ON c.id = w.subject_id
          JOIN clinic k ON k.id = c.clinic_id
          JOIN lease l ON l.id = c.lease_id
          JOIN landlord d ON d.id = l.landlord_id
         WHERE w.kind = :kind AND w.subject_type = 'landlord_charge'
           AND w.state IN ('APPROVED', 'POSTED')
           AND c.period = :period AND coalesce(w.entity_id, k.entity_id) = :entity
         ORDER BY d.name, c.clinic_id, c.invoice_id, c.id
    """), {"kind": CHARGE_CHECK, "period": period, "entity": entity_id,
           "ap": ACCOUNTS_PAYABLE}).mappings().all()
    out = []
    for r in rows:
        amount = r["posted"] if r["posted"] is not None else charges.payable(r, r["billed"]).amount
        if amount > 0:
            out.append(dict(r, amount=amount))
    return out


def _batch_payload(rows: List[Dict], entity_id: str, period: date, actor_id: str) -> Dict:
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


# --------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    """`make post M=YYYY-MM`: post the period's approved charge checks, as
    lease_gateway, one transaction per entity."""
    from ..db.engine import engine
    from ..jobs.monthly import MonthlyRunError, parse_period

    parser = argparse.ArgumentParser(description="Post a period's approved charge checks")
    parser.add_argument("--period", required=True, help="YYYY-MM")
    parser.add_argument("--entity", action="append",
                        help="entity id (repeatable); default: every entity")
    args = parser.parse_args(argv)
    try:
        month = parse_period(args.period)
    except MonthlyRunError as exc:
        print("post: %s" % exc, file=sys.stderr)
        return 2

    eng = engine("lease_gateway")
    with eng.connect() as conn:
        entities = args.entity or list(conn.execute(
            text("SELECT id FROM entity ORDER BY id")).scalars())
    if not entities:
        print("post: no entities; run `make seed` first", file=sys.stderr)
        return 2
    try:
        for entity_id in entities:
            with eng.begin() as conn:
                posted = post_approved(conn, entity_id, month)
                states = conn.execute(text("""
                    SELECT state, count(*) FROM work_item
                     WHERE kind = :kind AND entity_id = :e AND period = :p
                     GROUP BY state ORDER BY state
                """), {"kind": CHARGE_CHECK, "e": entity_id, "p": month}).all()
            label = "%s %s" % (entity_id, month.strftime("%Y-%m"))
            print("  %s  posted %d item(s)%s" % (label, len(posted), "".join(
                "  #%d->entry %d" % (p.work_item_id, p.journal_entry_id)
                if p.journal_entry_id is not None else "  #%d->closed (hold upheld, nothing owed)"
                % p.work_item_id for p in posted)))
            print("  %s  items by state: %s" % (
                label, ", ".join("%s=%d" % tuple(r) for r in states) or "none"))
    except (GatewayError, PostingError) as exc:
        print("post: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
