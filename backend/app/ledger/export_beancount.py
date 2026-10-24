"""Export the books as a Beancount v3 file, so they open in Fava.

Why bother: a judge or auditor should not have to trust our own screens to
believe the books balance. Beancount re-checks every transaction on load, and
Fava is a well-known, independent way to browse the result.

`make export-ledger` writes data/ledger/leasedesk.beancount, which the `fava`
Compose service (profile `ledger`) serves. The export connects as
`lease_reader`, the auditor's read-only role: exporting can never write.

Account names: <Type>:<CamelCasedName>:<Entity>, e.g. Expenses:LeaseCost:ENT-CA.
The entity is the leaf so that Fava rolls each account up across entities, and
Phase 2's three entities need no change here.
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

CURRENCY = "USD"
DEFAULT_OUT = Path("data/ledger/leasedesk.beancount")
ROOTS = {"asset": "Assets", "liability": "Liabilities", "equity": "Equity",
         "revenue": "Income", "expense": "Expenses"}


def beancount_account(type_: str, name: str, entity_id: str) -> str:
    """'liability', 'Accounts payable', 'ENT-CA' -> Liabilities:AccountsPayable:ENT-CA."""
    if type_ not in ROOTS:
        raise ValueError("unknown account type %r" % (type_,))
    return "%s:%s:%s" % (ROOTS[type_], _camel(name), _component(entity_id))


def render(conn: Connection) -> str:
    """The whole ledger as Beancount text."""
    accounts = conn.execute(text(
        "SELECT id, entity_id, code, name, type FROM account ORDER BY entity_id, code")
    ).mappings().all()
    names = {a["id"]: beancount_account(a["type"], a["name"], a["entity_id"]) for a in accounts}
    entries = conn.execute(text("""
        SELECT id, entity_id, date, period, memo, entry_type, idempotency_key, work_item_id
          FROM journal_entry ORDER BY date, id
    """)).mappings().all()
    lines = _lines_by_entry(conn)

    out: List[str] = [
        'option "title" "Lease Desk"',
        'option "operating_currency" "%s"' % CURRENCY,
        "",
    ]
    opened = _open_date(conn, entries)
    for a in accounts:
        out.append('%s open %s %s' % (opened.isoformat(), names[a["id"]], CURRENCY))
        out.append('  code: "%s"' % a["code"])
    for e in entries:
        out.append("")
        out.extend(_transaction(e, lines.get(e["id"], []), names))
    return "\n".join(out) + "\n"


def export(conn: Connection, path: Path = DEFAULT_OUT) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(render(conn))
    tmp.replace(path)
    return path


def _transaction(e: Mapping, lines: List[Mapping], names: Dict[int, str]) -> List[str]:
    out = ['%s * "%s"' % (e["date"].isoformat(), _quote(e["memo"])),
           '  entry_id: %d' % e["id"],
           '  entity: "%s"' % _quote(e["entity_id"]),
           '  period: "%s"' % e["period"].strftime("%Y-%m"),
           '  entry_type: "%s"' % _quote(e["entry_type"]),
           '  idempotency_key: "%s"' % _quote(e["idempotency_key"])]
    if e["work_item_id"] is not None:
        out.append('  work_item: %d' % e["work_item_id"])
    for l in lines:
        amount = l["debit"] if l["debit"] else -l["credit"]
        out.append('  %s  %s %s' % (names[l["account_id"]], amount, CURRENCY))
        if l["clinic_id"]:
            out.append('    clinic: "%s"' % _quote(l["clinic_id"]))
    return out


def _lines_by_entry(conn: Connection) -> Dict[int, List[Mapping]]:
    rows = conn.execute(text("""
        SELECT journal_entry_id, account_id, debit, credit, clinic_id
          FROM journal_line ORDER BY journal_entry_id, id
    """)).mappings().all()
    by: Dict[int, List[Mapping]] = {}
    for r in rows:
        by.setdefault(r["journal_entry_id"], []).append(r)
    return by


def _open_date(conn: Connection, entries) -> date:
    """Accounts open on the first period the books know about."""
    first: Optional[date] = conn.execute(text("SELECT min(period) FROM period")).scalar()
    dates = [d for d in [first] + [e["date"] for e in entries] if d is not None]
    return min(dates) if dates else date(2000, 1, 1)


def _camel(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        raise ValueError("account name %r has no usable characters" % (name,))
    joined = "".join(w if w.isupper() else w[:1].upper() + w[1:] for w in words)
    return joined if joined[0].isalpha() else "A" + joined


def _component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9-]+", "-", value).strip("-") or "X"
    return cleaned[0].upper() + cleaned[1:] if cleaned[0].isalpha() else "E" + cleaned


def _quote(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def main(argv=None) -> int:
    from ..db.engine import engine

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    with engine("lease_reader").connect() as conn:
        path = export(conn, args.out)
    print("wrote %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
