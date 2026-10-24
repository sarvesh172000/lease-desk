"""The ledger refuses bad books on its own: unbalanced entries, entries with
fewer than two lines, writes into a closed period, and double posting.

Every test posts as `lease_gateway`, the only role allowed to, so a failure
here is the database's constraint speaking, not a missing grant.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

ENTRY = text("""
    INSERT INTO journal_entry (entity_id, date, period, memo, idempotency_key)
    VALUES ('ENT-CA', :date, :period, 'test entry', :key) RETURNING id
""")
LINE = text("""
    INSERT INTO journal_line (journal_entry_id, account_id, debit, credit)
    VALUES (:entry, (SELECT id FROM account WHERE entity_id = 'ENT-CA' AND name = :account),
            :debit, :credit)
""")


def post(conn, lines, key="k1", period="2026-01-01", date="2026-01-31"):
    entry = conn.execute(ENTRY, dict(date=date, period=period, key=key)).scalar_one()
    for account, debit, credit in lines:
        conn.execute(LINE, dict(entry=entry, account=account, debit=debit, credit=credit))
    return entry


RENT = [("Lease cost", 19626.65, 0), ("Accounts payable", 0, 19626.65)]


def count(eng, table):
    with eng.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM %s" % table)).scalar_one()


def test_a_balanced_entry_posts(books):
    with books["lease_gateway"].begin() as conn:
        post(conn, RENT)
    assert count(books["lease_reader"], "journal_line") == 2


def test_an_unbalanced_entry_fails_at_commit_not_before(books):
    """Lines go in one at a time, so the check is deferred to commit: every
    insert succeeds, and the commit is what refuses."""
    conn = books["lease_gateway"].connect()
    tx = conn.begin()
    post(conn, [("Lease cost", 100, 0), ("Accounts payable", 0, 99.99)])  # no error yet
    with pytest.raises(DBAPIError, match="unbalanced"):
        tx.commit()
    conn.close()
    assert count(books["lease_reader"], "journal_entry") == 0


def test_a_single_line_entry_is_refused(books):
    with pytest.raises(DBAPIError, match="at least 2"):
        with books["lease_gateway"].begin() as conn:
            post(conn, [("Lease cost", 50, 0)])


def test_an_entry_with_no_lines_is_refused(books):
    with pytest.raises(DBAPIError, match="0 line"):
        with books["lease_gateway"].begin() as conn:
            post(conn, [])


@pytest.mark.parametrize("debit,credit", [(10, 10), (0, 0), (-5, 0)])
def test_a_line_is_exactly_one_positive_side(books, debit, credit):
    with pytest.raises(IntegrityError):
        with books["lease_gateway"].begin() as conn:
            post(conn, [("Lease cost", debit, credit), ("Accounts payable", 0, 10)])


def test_a_closed_period_refuses_new_entries(books):
    with pytest.raises(DBAPIError, match="2025-12 for entity ENT-CA is closed"):
        with books["lease_gateway"].begin() as conn:
            post(conn, RENT, period="2025-12-01", date="2025-12-31")


def test_closing_a_period_freezes_entries_already_in_it(books):
    with books["lease_gateway"].begin() as conn:
        entry = post(conn, RENT)
        conn.execute(text("UPDATE period SET status = 'closed', closed_at = now(), "
                          "closed_by = 'user:priya' WHERE period = '2026-01-01'"))
    with pytest.raises(DBAPIError, match="is closed"):
        with books["owner"].begin() as conn:
            conn.execute(text("UPDATE journal_line SET debit = debit + 1 "
                              "WHERE journal_entry_id = :e AND debit > 0"), {"e": entry})
    with pytest.raises(DBAPIError, match="is closed"):
        with books["owner"].begin() as conn:
            conn.execute(text("DELETE FROM journal_entry WHERE id = :e"), {"e": entry})


def test_a_period_that_does_not_exist_cannot_be_posted_to(books):
    with pytest.raises(IntegrityError):
        with books["lease_gateway"].begin() as conn:
            post(conn, RENT, period="2030-01-01", date="2030-01-31")


def test_a_repeated_idempotency_key_is_refused(books):
    """The gateway (A7) turns this into "return the original entry"; the
    database guarantees the second post can never land."""
    with books["lease_gateway"].begin() as conn:
        post(conn, RENT, key="rent-2026-01-LEASE-01")
    with pytest.raises(IntegrityError, match="idempotency_key"):
        with books["lease_gateway"].begin() as conn:
            post(conn, RENT, key="rent-2026-01-LEASE-01")
    assert count(books["lease_reader"], "journal_entry") == 1


def test_a_period_must_be_the_first_of_a_month(books):
    with pytest.raises(IntegrityError):
        with books["lease_gateway"].begin() as conn:
            conn.execute(text("INSERT INTO period (entity_id, period) VALUES ('ENT-CA', '2026-02-15')"))
