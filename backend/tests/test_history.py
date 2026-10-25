"""The 2025 history, and the cross-check that uses it."""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datagen.company import build_company
from datagen.history import PAST_MISTAKES, build_history, cross_check, paid_rent_by_month
from datagen.leases import build_leases


@pytest.fixture(scope="module")
def history():
    company = build_company()
    return company, build_leases(company), build_history(company)


def test_covers_the_whole_year(history):
    _, _, h = history
    assert h.months == 12


def test_every_running_lease_is_billed_every_month(history):
    _, leases, h = history
    for terms in leases:
        months = {i.period.strftime("%Y-%m") for i in h.invoices
                  if i.clinic_id == terms.clinic_id}
        running = {date(2025, m, 1).strftime("%Y-%m") for m in range(1, 13)
                   if terms.commencement <= date(2025, m, 1) <= terms.expiration}
        assert months == running, terms.lease_id


def test_a_lease_is_not_billed_before_it_commences():
    """LEASE-04 commences 2025-01-01, so 2024 must be empty for it."""
    company = build_company()
    h = build_history(company, build_leases(company), year=2024)
    assert not [i for i in h.invoices if i.clinic_id == "STORE-04"]


def test_the_year_is_mostly_but_not_entirely_correct(history):
    _, _, h = history
    assert h.total_overbilled() > 0
    assert h.total_overbilled() / h.total_billed() < 0.01


def test_past_mistakes_reach_the_invoices(history):
    _, _, h = history
    tagged = {c.error_id for i in h.invoices for c in i.charges if c.error_id}
    assert tagged == {m.error_id for m in PAST_MISTAKES}


def test_payments_follow_the_invoices(history):
    _, _, h = history
    assert round(sum(p.amount for p in h.payments), 2) == h.total_billed()


def test_cross_check_is_clean_where_billing_was_correct(history):
    _, leases, h = history
    clean = next(t for t in leases if t.lease_id == "LEASE-01")
    assert cross_check(clean, h) == []


def test_cross_check_surfaces_the_month_that_was_overbilled(history):
    _, leases, h = history
    terms = next(t for t in leases if t.lease_id == "LEASE-02")
    diffs = cross_check(terms, h)
    assert [d[0] for d in diffs] == ["2025-06"]
    period, due, paid = diffs[0]
    assert paid > due


def test_paid_rent_by_month_sums_per_period(history):
    _, _, h = history
    paid = paid_rent_by_month(h, "LEASE-01")
    assert len(paid) == 12
    assert all(v > 0 for v in paid.values())


def test_history_is_deterministic():
    assert build_history().total_billed() == build_history().total_billed()
