"""jobs/clock.py: a business date stored in sync_cursor, set and advanced by
the worker's role."""

from datetime import date, datetime

import pytest
from sqlalchemy import text

from app.jobs.clock import SOURCE, ClockError, advance, set_today, stored, today


@pytest.fixture
def agent(clean):
    return clean["lease_agent"]


def test_an_unset_clock_reads_the_calendar_and_stores_nothing(agent):
    with agent.begin() as conn:
        assert stored(conn) is None
        assert today(conn) == date.today()
        assert conn.execute(text("SELECT count(*) FROM sync_cursor")).scalar_one() == 0


def test_set_today_is_stored_in_sync_cursor(agent):
    with agent.begin() as conn:
        set_today(conn, date(2026, 1, 31))
    with agent.connect() as conn:
        assert today(conn) == date(2026, 1, 31)
        assert conn.execute(text("SELECT cursor FROM sync_cursor WHERE source = :s"),
                            {"s": SOURCE}).scalar_one() == "2026-01-31"


def test_set_today_overwrites_rather_than_duplicating(agent):
    with agent.begin() as conn:
        set_today(conn, date(2026, 1, 1))
        set_today(conn, date(2025, 6, 1))           # a deliberate rewind is allowed
        assert today(conn) == date(2025, 6, 1)
        assert conn.execute(text("SELECT count(*) FROM sync_cursor")).scalar_one() == 1


def test_advance_moves_forward_across_a_month_end(agent):
    with agent.begin() as conn:
        set_today(conn, date(2026, 1, 31))
        assert advance(conn, 1) == date(2026, 2, 1)
        assert advance(conn, 0) == date(2026, 2, 1)
        assert advance(conn, 28) == date(2026, 3, 1)
        assert today(conn) == date(2026, 3, 1)


def test_the_clock_does_not_disturb_file_cursors(agent):
    with agent.begin() as conn:
        conn.execute(text("INSERT INTO sync_cursor (source, cursor) VALUES ('file:x.csv', 'abc')"))
        set_today(conn, date(2026, 1, 1))
        assert conn.execute(text("SELECT cursor FROM sync_cursor WHERE source = 'file:x.csv'")
                            ).scalar_one() == "abc"


# ---------------------------------------------------------------- bad input

@pytest.mark.parametrize("value", ["2026-01-01", datetime(2026, 1, 1, 9), None, 20260101])
def test_set_today_needs_a_date(agent, value):
    with agent.begin() as conn, pytest.raises(ClockError, match="needs a date"):
        set_today(conn, value)


@pytest.mark.parametrize("days", [1.5, "1", True, None])
def test_advance_needs_whole_days(agent, days):
    with agent.begin() as conn, pytest.raises(ClockError, match="whole number"):
        advance(conn, days)


def test_advance_refuses_to_go_backward(agent):
    with agent.begin() as conn:
        set_today(conn, date(2026, 1, 15))
        with pytest.raises(ClockError, match="backward"):
            advance(conn, -1)
        assert today(conn) == date(2026, 1, 15)


def test_a_corrupt_stored_value_is_named(agent):
    with agent.begin() as conn:
        conn.execute(text("INSERT INTO sync_cursor (source, cursor) VALUES (:s, 'soon')"),
                     {"s": SOURCE})
        with pytest.raises(ClockError, match="'soon'"):
            today(conn)
