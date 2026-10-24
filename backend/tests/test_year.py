"""The error catalog at scale and the full billing year (chunk B2)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datagen.company import FULL, build_company
from datagen.errors_v2 import (
    ERROR_TYPES, build_catalog, by_kind, odd_but_correct, real_errors,
)
from datagen.leases import build_leases
from datagen.year import build_year


@pytest.fixture(scope="module")
def year():
    company = build_company(FULL)
    leases = build_leases(company)
    return company, leases, build_year(2026, company, leases)


# --- the catalog -----------------------------------------------------------

def test_roughly_sixty_errors_are_planted(year):
    _, _, y = year
    assert 50 <= len(real_errors(y.catalog)) <= 70


def test_roughly_twenty_charges_look_wrong_and_are_right(year):
    """These matter as much as the errors: a checker that holds everything
    unusual costs a controller more time than it saves."""
    _, _, y = year
    assert 15 <= len(odd_but_correct(y.catalog)) <= 25


def test_at_least_eighteen_distinct_error_types(year):
    _, _, y = year
    assert len(by_kind(y.catalog)) >= 18


def test_errors_spread_across_the_whole_year(year):
    _, _, y = year
    assert {e.period.month for e in y.catalog} == set(range(1, 13))


def test_errors_spread_across_most_clinics(year):
    _, leases, y = year
    assert len({e.clinic_id for e in y.catalog}) >= len(leases) - 2


def test_a_duplicate_is_an_error_even_though_the_amount_is_right(year):
    """Testing on the variance would classify it as not an error at all."""
    _, _, y = year
    dupes = [e for e in y.catalog if e.kind == "duplicate_rent_invoice"]
    assert dupes
    for error in dupes:
        assert error.is_error
        assert error.billed > 0


def test_wholly_unsupported_charges_support_nothing(year):
    _, _, y = year
    for error in y.catalog:
        if error.kind in ("charge_for_unleased_suite", "late_fee_on_ontime_payment",
                          "duplicate_rent_invoice"):
            assert error.correct == 0.0, error.kind


def test_no_error_is_billed_below_what_the_lease_supports(year):
    """An overcharge is the case. A negative variance would mean the generator
    planted an undercharge and called it an error."""
    _, _, y = year
    for error in real_errors(y.catalog):
        assert error.variance >= 0, "%s %s" % (error.error_id, error.kind)


def test_correct_but_odd_charges_have_no_variance(year):
    _, _, y = year
    for error in odd_but_correct(y.catalog):
        assert error.billed == error.correct
        assert error.expected_outcome == "approve"


def test_every_error_cites_a_clause(year):
    _, _, y = year
    for error in y.catalog:
        assert error.lease_section and error.proof_quote


def test_every_error_names_where_it_should_go(year):
    _, _, y = year
    for error in y.catalog:
        assert error.expected_route in ("auto", "regional_manager", "controller")


def test_the_catalog_is_deterministic(year):
    company, leases, _ = year
    assert build_catalog(company, leases) == build_catalog(company, leases)


def test_every_error_type_is_reachable():
    kinds = {t.kind for t in ERROR_TYPES}
    assert len(kinds) == len(ERROR_TYPES), "duplicate kind in ERROR_TYPES"


# --- the year --------------------------------------------------------------

def test_the_year_bills_every_month(year):
    _, _, y = year
    assert set(y.by_month()) == set(range(1, 13))


def test_several_hundred_charges(year):
    _, _, y = year
    assert 700 <= y.charges <= 1_000


def test_more_than_rent_and_cam_is_billed(year):
    """Tax and insurance pass-throughs, reconciliations, credit memos and late
    notices — the charges a rent schedule says nothing about."""
    _, _, y = year
    types = set(y.by_charge_type())
    assert {"base_rent", "cam_estimate", "property_tax", "insurance",
            "cam_reconciliation"} <= types


def test_reconciliation_only_lands_after_the_year_it_covers(year):
    _, _, y = year
    for invoice in y.invoices:
        for charge in invoice.charges:
            if charge.charge_type == "cam_reconciliation":
                assert charge.period.month in (3, 4)


def test_a_lease_is_not_billed_outside_its_term(year):
    _, leases, y = year
    terms = {t.lease_id: t for t in leases}
    for invoice in y.invoices:
        for charge in invoice.charges:
            lease = terms[charge.lease_id]
            assert lease.commencement <= charge.period <= lease.expiration


def test_payments_follow_the_invoices(year):
    _, _, y = year
    assert round(sum(p.amount for p in y.payments), 2) == y.total_billed()


def test_charge_ids_are_unique_across_the_year(year):
    _, _, y = year
    ids = [c.charge_id for i in y.invoices for c in i.charges]
    assert len(ids) == len(set(ids))


def test_invoice_ids_are_unique_across_the_year(year):
    _, _, y = year
    ids = [i.invoice_id for i in y.invoices]
    assert len(ids) == len(set(ids))


def test_every_planted_error_reaches_a_charge(year):
    _, _, y = year
    tagged = {c.error_id for i in y.invoices for c in i.charges if c.error_id}
    expected = {e.error_id for e in y.catalog
                if e.charge_type in y.by_charge_type()}
    assert len(tagged & expected) >= len(real_errors(y.catalog)) * 0.7


def test_the_year_is_deterministic(year):
    company, leases, y = year
    again = build_year(2026, company, leases)
    assert again.charges == y.charges
    assert again.total_billed() == y.total_billed()


def test_every_error_reaches_a_charge(year):
    """An error planted in a month where that charge type is never billed is
    not a test of anything."""
    _, _, y = year
    tagged = {c.error_id for i in y.invoices for c in i.charges if c.error_id}
    planted = {e.error_id for e in real_errors(y.catalog)}
    assert planted - tagged == set()


def test_correct_but_odd_charges_are_never_tagged(year):
    """The eval finds them as the untagged line for that clinic and type."""
    _, _, y = year
    tagged = {c.error_id for i in y.invoices for c in i.charges if c.error_id}
    assert {e.error_id for e in odd_but_correct(y.catalog)} & tagged == set()
