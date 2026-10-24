"""Standardize into the golden tables: the business truth everything checks against.

Two kinds of input:

  - **The org chart and lease register** (entity, region, landlords, centers,
    clinics, leases) come from `datagen` as structured objects. In production
    they would be an HR/property-system sync; the shape is the same.
  - **Charges and payments** come from `raw_row`, never from the generator
    directly. That is the real pipeline: a landlord charge is whatever the AP
    export said, traceable to the exact raw row (`raw_ref`) it came from.

Every write is an upsert keyed on a stable id, so re-running changes nothing
unless the source changed. This runs as `lease_gateway`: the truth model says
nothing writes to records except the gateway.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Set

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from ..db import models as m
from .ingest import IngestError, stable_id


class GoldenError(IngestError):
    """A raw row could not become a golden record. Names the row."""


def upsert(conn: Connection, table, rows: List[Dict], key: Iterable[str] = ("id",)) -> int:
    if not rows:
        return 0
    stmt = insert(table).values(rows)
    key = list(key)
    update = {c: stmt.excluded[c] for c in rows[0] if c not in key}
    conn.execute(stmt.on_conflict_do_update(index_elements=key, set_=update)
                 if update else stmt.on_conflict_do_nothing())
    return len(rows)


def load_org(conn: Connection, company) -> None:
    e = company.entity
    upsert(conn, m.entity, [dict(id=e.entity_id, name=e.name, state=e.state)])
    r = company.region
    upsert(conn, m.region, [dict(id=r.region_id, name=r.name, manager_id=r.manager_id)])
    upsert(conn, m.landlord, [dict(
        id=l.landlord_id, name=l.name, notice_address=l.notice_address,
        authorized_rep=l.authorized_rep, authorized_rep_email=l.authorized_rep_email,
        property_manager=l.property_manager, property_manager_email=l.property_manager_email,
    ) for l in company.landlords])
    upsert(conn, m.center, [dict(
        id=c.center_id, name=c.name, address=c.address, landlord_id=c.landlord_id,
        total_rsf=c.total_rsf) for c in company.centers])
    upsert(conn, m.clinic, [dict(
        id=c.clinic_id, name=c.name, entity_id=c.entity_id, region_id=c.region_id,
        center_id=c.center_id, suite=c.suite, rsf=c.rsf) for c in company.clinics])


def load_leases(conn: Connection, leases) -> int:
    return upsert(conn, m.lease, [dict(
        id=t.lease_id, clinic_id=t.clinic_id, landlord_id=t.landlord_id, status="active")
        for t in leases])


def standardize_charges(conn: Connection) -> int:
    leases = _ids(conn, m.lease)
    documents = _ids(conn, m.source_document)
    rows = []
    for raw in _raw(conn, "ap_export"):
        p = raw.payload
        lease_id = _known(raw, p, "lease_id", leases)
        invoice_doc = stable_id("datagen.invoices", p["invoice_id"])
        rows.append(dict(
            id=raw.id, lease_id=lease_id, clinic_id=p["clinic_id"],
            invoice_id=p["invoice_id"], suite=p.get("suite"),
            period=_period(raw, p["period"]), charge_type=p["charge_type"],
            description=p.get("description"), amount=_money(raw, p["amount"]),
            document_id=invoice_doc if invoice_doc in documents else None,
            page=None, raw_ref=raw.id,
        ))
    return upsert(conn, m.landlord_charge, rows)


def standardize_payments(conn: Connection) -> int:
    leases = _ids(conn, m.lease)
    rows = []
    for raw in _raw(conn, "bank_export"):
        p = raw.payload
        rows.append(dict(
            id=raw.id, lease_id=_known(raw, p, "lease_id", leases), clinic_id=p["clinic_id"],
            invoice_id=p.get("invoice_id") or None, period=_period(raw, p["period"]),
            charge_type=p["charge_type"], amount=_money(raw, p["amount"]),
            paid_on=_date(raw, p["paid_on"]), reference=p.get("reference"),
            counterparty=p.get("counterparty"), raw_ref=raw.id,
        ))
    return upsert(conn, m.payment, rows)


# --- validation: every failure names the raw row it came from -------------

def _raw(conn: Connection, source: str):
    return conn.execute(select(m.raw_row).where(m.raw_row.c.source == source)
                        .order_by(m.raw_row.c.source_id)).all()


def _ids(conn: Connection, table) -> Set[str]:
    return set(conn.execute(select(table.c.id)).scalars())


def _known(raw, payload: Dict, column: str, known: Set[str]) -> str:
    value = payload.get(column)
    if value not in known:
        raise GoldenError("raw row %s (%s): unknown %s %r" % (raw.source_id, raw.source, column, value))
    return value


def _money(raw, value: str) -> Decimal:
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError):
        raise GoldenError("raw row %s (%s): amount %r is not a number"
                          % (raw.source_id, raw.source, value)) from None
    if not amount.is_finite():
        raise GoldenError("raw row %s (%s): amount %r is not finite" % (raw.source_id, raw.source, value))
    return amount.quantize(Decimal("0.01"))


def _date(raw, value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise GoldenError("raw row %s (%s): %r is not a date"
                          % (raw.source_id, raw.source, value)) from None


def _period(raw, value: str) -> date:
    d = _date(raw, value)
    if d.day != 1:
        raise GoldenError("raw row %s (%s): period %s is not the first of a month"
                          % (raw.source_id, raw.source, value))
    return d
