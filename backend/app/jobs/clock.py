"""The business clock: the date the system believes it is.

A demo has to run January, then February, then a year-end, in one afternoon,
and a test has to know what "today" is. So business logic never calls
`date.today()`; it asks this module, which reads a stored date that a person
(or a test) sets and advances.

**Where it is stored, and why there.** There is no clock table, and the table
names are frozen. `sync_cursor` already exists to hold one small piece of
named, mutable state per source ("how far have we read this feed"), and the
worker's role, `lease_agent`, may INSERT and UPDATE it but cannot touch the
ledger or the golden tables. The business date is exactly that shape: one
named value the agents read and move forward. So it lives in `sync_cursor`
under the source `clock:business_date`, as an ISO date. The `clock:` prefix
keeps it apart from file cursors (`file:...`), and `at` records when it was
last moved.

Until someone sets it, `today()` falls back to the calendar date, without
storing it, so an unset clock never silently freezes.
"""

from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

SOURCE = "clock:business_date"


class ClockError(ValueError):
    """A bad date or step, or a stored value that is not a date."""


def stored(conn: Connection) -> Optional[date]:
    """The stored business date, or None if the clock was never set."""
    value = conn.execute(text("SELECT cursor FROM sync_cursor WHERE source = :s"),
                         {"s": SOURCE}).scalar()
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ClockError("sync_cursor %s holds %r, which is not an ISO date"
                         % (SOURCE, value)) from exc


def today(conn: Connection) -> date:
    """The business date: the stored one, else the calendar date."""
    return stored(conn) or date.today()


def set_today(conn: Connection, d: date) -> date:
    """Set the business date. A datetime is refused: a business day has no time."""
    if not isinstance(d, date) or isinstance(d, datetime):
        raise ClockError("set_today needs a date, got %r" % (d,))
    conn.execute(text("""
        INSERT INTO sync_cursor (source, cursor, at) VALUES (:s, :c, now())
        ON CONFLICT (source) DO UPDATE SET cursor = EXCLUDED.cursor, at = now()
    """), {"s": SOURCE, "c": d.isoformat()})
    return d


def advance(conn: Connection, days: int) -> date:
    """Move the business date forward and return the new date. The clock
    only moves forward this way; rewinding is a deliberate `set_today`."""
    if isinstance(days, bool) or not isinstance(days, int):
        raise ClockError("advance needs a whole number of days, got %r" % (days,))
    if days < 0:
        raise ClockError("advance cannot move the clock backward (%d days); "
                         "use set_today to rewind deliberately" % days)
    return set_today(conn, today(conn) + timedelta(days=days))
