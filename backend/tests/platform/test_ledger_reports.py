"""Trial balance and the Beancount export, both read as lease_reader.

The export is checked by Beancount's own loader: if Beancount accepts the file
with no errors, Fava opens it and every transaction balances by an independent
tool's arithmetic, not ours.
"""

import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import ledger_world as w
import pytest
from beancount import loader
from beancount.core import data as bc

from app.db.bootstrap import execute_raw
from app.ledger.export_beancount import beancount_account, export, render
from app.ledger.trial_balance import OutOfBalance, trial_balance
from app.work.gateway import post_approved_charge, post_journal

JAN, FEB = date(2026, 1, 1), date(2026, 2, 1)
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def posted(books):
    """January rent and CAM posted through the gateway, plus a February payment."""
    w.build(books["owner"])
    with books["owner"].begin() as conn:
        execute_raw(conn, "INSERT INTO period VALUES ('ENT-CA', '2026-02-01', 'open', NULL, NULL)")
    rent, cam = w.item(books["owner"], w.RENT), w.item(books["owner"], w.CAM)
    pay = w.item(books["owner"], "PAY-1", kind="PAYMENT", subject_type="payment", period="2026-02-01")
    with books["lease_gateway"].begin() as conn:
        post_approved_charge(conn, rent)
        post_approved_charge(conn, cam)
        post_journal(conn, pay, [("Accounts payable", "21726.65", 0), ("Cash", 0, "21726.65")],
                     "pay-feb", entity_id="ENT-CA", date=date(2026, 2, 5), period=FEB,
                     memo='Paid "Harbor Point" \\ January')
    return books


def tb(eng, first, last=None):
    with eng["lease_reader"].connect() as conn:
        return trial_balance(conn, "ENT-CA", first, last)


# ------------------------------------------------------------ trial balance

def test_trial_balance_for_one_period(posted):
    jan = tb(posted, JAN)
    assert [(r.name, r.debit, r.credit) for r in jan.rows] == [
        ("Accounts payable", Decimal("0"), Decimal("21726.65")),
        ("Lease cost", Decimal("19626.65"), Decimal("0")),
        ("CAM expense", Decimal("2100.00"), Decimal("0"))]
    assert jan.total_debits == jan.total_credits == Decimal("21726.65")


def test_trial_balance_over_a_range(posted):
    both = tb(posted, JAN, FEB)
    assert both.row("Accounts payable").balance == 0
    assert both.row("Cash").balance == Decimal("-21726.65")
    assert both.total_debits == both.total_credits == Decimal("43453.30")


def test_an_empty_range_is_an_empty_balanced_report(posted):
    report = tb(posted, date(2027, 1, 1))
    assert report.rows == [] and report.total_debits == 0


@pytest.mark.parametrize("first,last", [
    (date(2026, 1, 15), None), (FEB, JAN), ("2026-01-01", None)])
def test_a_bad_range_is_refused(posted, first, last):
    with pytest.raises(ValueError):
        tb(posted, first, last)


def test_books_edited_around_the_database_are_caught(posted):
    with posted["owner"].begin() as conn:
        execute_raw(conn, "ALTER TABLE journal_line DISABLE TRIGGER USER;"
                          "UPDATE journal_line SET debit = debit + 1 WHERE debit > 0 "
                          "AND id = (SELECT min(id) FROM journal_line);"
                          "ALTER TABLE journal_line ENABLE TRIGGER USER;")
    with pytest.raises(OutOfBalance, match="out of balance"):
        tb(posted, JAN)


# ------------------------------------------------------------------- export

def test_the_export_passes_beancounts_own_validation(posted):
    with posted["lease_reader"].connect() as conn:
        entries, errors, options = loader.load_string(render(conn))
    assert errors == []
    txns = [e for e in entries if isinstance(e, bc.Transaction)]
    opens = {e.account for e in entries if isinstance(e, bc.Open)}
    assert len(txns) == 3 and len(opens) == 12
    assert {"Assets:Cash:ENT-CA", "Liabilities:AccountsPayable:ENT-CA",
            "Expenses:LeaseCost:ENT-CA", "Expenses:CAMExpense:ENT-CA"} <= opens


def test_each_transaction_carries_its_memo_and_metadata(posted):
    with posted["lease_reader"].connect() as conn:
        entries, _, _ = loader.load_string(render(conn))
    txns = [e for e in entries if isinstance(e, bc.Transaction)]
    rent = next(t for t in txns if t.narration.startswith("Lease cost"))
    assert rent.meta["entry_type"] == "phase1_period_cost"
    assert rent.meta["work_item"] == 1 and rent.meta["entity"] == "ENT-CA"
    assert {p.account: p.units.number for p in rent.postings} == {
        "Expenses:LeaseCost:ENT-CA": Decimal("19626.65"),
        "Liabilities:AccountsPayable:ENT-CA": Decimal("-19626.65")}
    assert rent.postings[0].meta["clinic"] == "STORE-01"
    payment = next(t for t in txns if t.date == date(2026, 2, 5))
    assert payment.narration == 'Paid "Harbor Point" \\ January'       # escaped and back


def test_an_empty_ledger_still_exports_a_valid_file(books):
    with books["lease_reader"].connect() as conn:
        entries, errors, _ = loader.load_string(render(conn))
    assert errors == [] and not [e for e in entries if isinstance(e, bc.Transaction)]


def test_export_writes_the_file(posted, tmp_path):
    out = tmp_path / "ledger" / "leasedesk.beancount"
    with posted["lease_reader"].connect() as conn:
        assert export(conn, out) == out
    _, errors, _ = loader.load_file(str(out))
    assert errors == []


def test_make_export_ledger_runs_as_the_reader(posted, tmp_path):
    """The CLI behind `make export-ledger` connects as lease_reader."""
    import os

    from app.settings import get_settings

    env = dict(os.environ, PYTHONPATH="%s/backend:%s" % (ROOT, ROOT),
               LEASEDESK_DB_NAME=posted["lease_reader"].url.database,
               LEASEDESK_DB_PORT=str(get_settings().db_port))
    out = tmp_path / "out.beancount"
    done = subprocess.run([sys.executable, "-m", "app.ledger.export_beancount", "--out", str(out)],
                          cwd=ROOT, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert loader.load_file(str(out))[1] == []


@pytest.mark.parametrize("type_,name,entity,expected", [
    ("asset", "ROU asset", "ENT-CA", "Assets:ROUAsset:ENT-CA"),
    ("liability", "Lease liability, non-current", "ENT-CA",
     "Liabilities:LeaseLiabilityNonCurrent:ENT-CA"),
    ("expense", "Late fees and penalties", "ent_az", "Expenses:LateFeesAndPenalties:Ent-az"),
    ("revenue", "Sublease income", "9X", "Income:SubleaseIncome:E9X"),
])
def test_account_names_become_valid_beancount_names(type_, name, entity, expected):
    assert beancount_account(type_, name, entity) == expected


@pytest.mark.parametrize("type_,name", [("contra", "Cash"), ("asset", "!!!")])
def test_unusable_account_names_are_refused(type_, name):
    with pytest.raises(ValueError):
        beancount_account(type_, name, "ENT-CA")
