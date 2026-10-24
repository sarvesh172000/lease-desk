"""Journal lines for approved charges (Phase 1 group 10)."""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.checker import check_month
from app.engine.from_datagen import charges_from_invoices, rules_from_terms
from app.engine.journal import (
    ACCOUNTS_PAYABLE, CAM_EXPENSE, LEASE_COST, PLACEHOLDER,
    all_balanced, entries_for, totals_by_account,
)
from datagen.company import build_company
from datagen.leases import build_leases
from datagen.month import build_month

PERIOD = date(2026, 1, 1)


@pytest.fixture(scope="module")
def january():
    company = build_company()
    leases = build_leases(company)
    findings = check_month(
        charges_from_invoices(build_month(PERIOD, company, leases)),
        rules_from_terms(leases, company), PERIOD)
    return findings, entries_for(findings)


def test_one_entry_per_approved_charge(january):
    findings, entries = january
    assert len(entries) == sum(1 for f in findings if f.proposal == "approve")


def test_held_charges_produce_nothing(january):
    """A charge under review has not been agreed. Accruing it would put a
    number in the books the next conversation may change."""
    findings, entries = january
    held_ids = {f.charge.charge_id for f in findings if f.proposal == "hold"}
    posted_ids = {cid for e in entries for cid in e.source_charge_ids}
    assert held_ids & posted_ids == set()


def test_every_entry_balances(january):
    _, entries = january
    assert all_balanced(entries)


def test_rent_goes_to_lease_cost_against_payables(january):
    _, entries = january
    rent = next(e for e in entries if e.lines[0].account == LEASE_COST)
    assert rent.lines[0].debit > 0
    assert rent.lines[1].account == ACCOUNTS_PAYABLE
    assert rent.lines[1].credit == rent.lines[0].debit


def test_operating_expense_goes_to_its_own_account(january):
    _, entries = january
    assert any(e.lines[0].account == CAM_EXPENSE for e in entries)


def test_entries_are_marked_as_provisional(january):
    """An accountant seeing Dr Lease cost on an operating lease must be told
    this is superseded by the ASC 842 subledger."""
    _, entries = january
    assert all(e.is_placeholder for e in entries)
    assert all(e.entry_type == PLACEHOLDER for e in entries)


def test_payables_equal_the_expense_booked(january):
    _, entries = january
    totals = totals_by_account(entries)
    expense = totals[LEASE_COST] + totals[CAM_EXPENSE]
    assert round(expense + totals[ACCOUNTS_PAYABLE], 2) == 0.0


def test_posting_the_same_month_twice_is_the_same_key(january):
    _, entries = january
    again = entries_for(january[0])
    assert [e.idempotency_key() for e in entries] == [e.idempotency_key() for e in again]


def test_idempotency_keys_are_unique_within_a_month(january):
    _, entries = january
    keys = [e.idempotency_key() for e in entries]
    assert len(keys) == len(set(keys))
