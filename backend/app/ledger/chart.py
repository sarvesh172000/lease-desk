"""Chart of accounts and accounting periods, per entity.

Account *names* are the join key with the engine: `engine/journal.py` emits
lines against "Lease cost", "CAM expense" and "Accounts payable", and the
gateway resolves those names to this entity's account ids. Rename one here and
posting fails loudly rather than landing in the wrong account.
"""

from dataclasses import dataclass
from datetime import date
from typing import Iterator, List

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from ..db.models import account, period


@dataclass(frozen=True)
class AccountSpec:
    code: str
    name: str
    type: str


# Phase 1 group 4. Codes follow the usual 1xxx assets, 2xxx liabilities,
# 6xxx expenses layout so the Beancount export sorts sensibly.
CHART: List[AccountSpec] = [
    AccountSpec("1000", "Cash", "asset"),
    AccountSpec("1300", "Prepaid rent", "asset"),
    AccountSpec("1400", "Landlord receivable", "asset"),       # disputes
    AccountSpec("1700", "ROU asset", "asset"),                  # operating
    AccountSpec("2000", "Accounts payable", "liability"),
    AccountSpec("2300", "Lease liability, current", "liability"),
    AccountSpec("2700", "Lease liability, non-current", "liability"),
    AccountSpec("6100", "Lease cost", "expense"),
    AccountSpec("6200", "CAM expense", "expense"),
    AccountSpec("6300", "Property tax expense", "expense"),
    AccountSpec("6400", "Insurance expense", "expense"),
    AccountSpec("6900", "Late fees and penalties", "expense"),
]


def months(first: date, last: date) -> Iterator[date]:
    """First-of-month dates from `first` to `last`, inclusive."""
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        yield date(year, month, 1)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def install_chart(conn: Connection, entity_id: str) -> None:
    """Create any missing accounts for one entity."""
    rows = [dict(entity_id=entity_id, code=a.code, name=a.name, type=a.type) for a in CHART]
    conn.execute(
        insert(account).values(rows).on_conflict_do_nothing(index_elements=["entity_id", "code"]))


def open_periods(conn: Connection, entity_id: str, first: date, last: date) -> None:
    """Open every month in the range that does not exist yet. A period that
    already exists keeps its status: re-seeding never reopens a closed month."""
    rows = [dict(entity_id=entity_id, period=p, status="open") for p in months(first, last)]
    conn.execute(insert(period).values(rows).on_conflict_do_nothing())

