"""The operating lease subledger and the period close (chunk B5)."""

import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.engine.asc842 import (
    ACCOUNTS_PAYABLE, LEASE_COST, LEASE_LIABILITY, ROU_ASSET, VARIABLE,
    balances, entries_for_month, is_variable, monthly_entry, split_liability,
)
from app.ledger.close import (
    CLOSED, DEFAULT_MATERIALITY, OPEN, Period, PeriodLocked,
    assert_open, build_checklist, sign_off,
)
from datagen.company import FULL, build_company
from datagen.leases import build_leases
from leasedesk.models import load_lease
from leasedesk.schedule import build

JUNE = date(2026, 6, 1)


@dataclass
class Question:
    amount: float


@dataclass
class Charge:
    accrued: bool = False


@pytest.fixture(scope="module")
def books():
    company = build_company(FULL)
    leases = build_leases(company)
    schedules, entity_of = {}, {}
    for terms in leases:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(terms.to_engine_json(company), fh)
            path = fh.name
        schedules[terms.lease_id] = build(load_lease(path))
        entity_of[terms.lease_id] = company.clinic(terms.clinic_id).entity_id
    return company, leases, schedules, entity_of


# --- the monthly entry -----------------------------------------------------

def test_the_entry_has_the_four_asc842_lines(books):
    _, _, schedules, _ = books
    entry = monthly_entry(schedules["LEASE-01"], JUNE, "LEASE-01", "ENT-CA")
    assert {l.account for l in entry.lines} == {
        LEASE_COST, LEASE_LIABILITY, ROU_ASSET, ACCOUNTS_PAYABLE}


def test_every_entry_balances(books):
    _, _, schedules, entity_of = books
    for entry in entries_for_month(schedules, JUNE, entity_of):
        assert entry.balanced, entry.lease_id


def test_lease_cost_is_straight_line_not_the_payment(books):
    """An operating lease expenses one constant amount; the cash moves."""
    _, _, schedules, _ = books
    schedule = schedules["LEASE-01"]
    costs = {monthly_entry(schedule, p.period, "LEASE-01", "ENT-CA").straight_line_cost
             for p in schedule.periods[:12]}
    assert len(costs) == 1


def test_the_liability_falls_by_payment_less_accretion(books):
    _, _, schedules, _ = books
    entry = monthly_entry(schedules["LEASE-01"], JUNE, "LEASE-01", "ENT-CA")
    reduction = next(l for l in entry.lines if l.account == LEASE_LIABILITY).debit
    assert reduction == round(entry.payment - entry.interest, 2)


def test_the_rou_asset_amortizes_by_the_plug(books):
    _, _, schedules, _ = books
    entry = monthly_entry(schedules["LEASE-01"], JUNE, "LEASE-01", "ENT-CA")
    amortization = next(l for l in entry.lines if l.account == ROU_ASSET).credit
    assert amortization == round(entry.straight_line_cost - entry.interest, 2)


def test_a_month_outside_the_term_produces_no_entry(books):
    _, _, schedules, _ = books
    assert monthly_entry(schedules["LEASE-01"], date(2035, 1, 1), "LEASE-01", "ENT-CA") is None


def test_posting_a_month_twice_is_the_same_key(books):
    _, _, schedules, _ = books
    a = monthly_entry(schedules["LEASE-01"], JUNE, "LEASE-01", "ENT-CA")
    b = monthly_entry(schedules["LEASE-01"], JUNE, "LEASE-01", "ENT-CA")
    assert a.idempotency_key() == b.idempotency_key()


# --- variable consideration ------------------------------------------------

def test_operating_expenses_are_not_in_the_liability():
    """Sweeping CAM into the lease liability overstates the balance sheet."""
    for charge_type in ("cam_estimate", "cam_reconciliation", "property_tax",
                        "insurance", "late_fee"):
        assert is_variable(charge_type), charge_type


def test_base_rent_is_not_variable():
    assert not is_variable("base_rent")
    assert "base_rent" not in VARIABLE


# --- the current / non-current split ---------------------------------------

def test_the_split_sums_to_the_liability(books):
    _, leases, schedules, entity_of = books
    for entity in ("ENT-CA", "ENT-NV", "ENT-AZ"):
        ids = [t.lease_id for t in leases if entity_of[t.lease_id] == entity]
        assert balances(schedules, entity, JUNE, ids).splits_correctly


def test_neither_portion_is_negative(books):
    _, _, schedules, _ = books
    current, noncurrent = split_liability(schedules["LEASE-01"], JUNE)
    assert current >= 0 and noncurrent >= 0


def test_current_never_exceeds_the_whole_liability(books):
    _, _, schedules, _ = books
    for lease_id, schedule in schedules.items():
        current, _ = split_liability(schedule, JUNE)
        assert current <= schedule.balances_at(JUNE)["liability"] + 0.01, lease_id


def test_a_lease_in_its_final_year_is_almost_all_current(books):
    _, _, schedules, _ = books
    schedule = schedules["LEASE-01"]
    near_end = date(2028, 6, 1)
    current, noncurrent = split_liability(schedule, near_end)
    assert current > noncurrent


# --- the close -------------------------------------------------------------

def clean_checklist(ids, **overrides):
    args = dict(
        entity_id="ENT-CA", period=JUNE,
        subledger_liability=1_000_000.00, gl_liability=1_000_000.00,
        subledger_rou=950_000.00, gl_rou=950_000.00,
        leases_expected=ids, leases_posted=ids,
        unresolved_charges=[], open_questions=[],
    )
    args.update(overrides)
    return build_checklist(**args)


def test_a_period_that_ties_is_ready(books):
    _, leases, _, _ = books
    ids = [t.lease_id for t in leases[:5]]
    assert clean_checklist(ids).ready


def test_a_lease_with_no_entry_blocks_the_close(books):
    _, leases, _, _ = books
    ids = [t.lease_id for t in leases[:5]]
    checklist = clean_checklist(ids, leases_posted=ids[:-1])
    assert not checklist.ready
    assert "no entry" in checklist.describe()


def test_a_subledger_that_does_not_tie_blocks_the_close(books):
    _, leases, _, _ = books
    ids = [t.lease_id for t in leases[:5]]
    checklist = clean_checklist(ids, gl_liability=999_998.75)
    assert not checklist.ready
    assert "out by $1.25" in checklist.describe()


def test_a_cent_of_difference_is_still_a_failure(books):
    """To the cent, not close enough."""
    _, leases, _, _ = books
    ids = [t.lease_id for t in leases[:5]]
    assert not clean_checklist(ids, gl_rou=949_999.99).ready


def test_an_unaccrued_charge_blocks_the_close(books):
    _, leases, _, _ = books
    ids = [t.lease_id for t in leases[:5]]
    assert not clean_checklist(ids, unresolved_charges=[Charge(accrued=False)]).ready


def test_a_held_charge_that_was_accrued_does_not_block(books):
    """The lease-supported portion is accrued; the disputed difference is not
    expensed. Both are correct, so the period can close."""
    _, leases, _, _ = books
    ids = [t.lease_id for t in leases[:5]]
    assert clean_checklist(ids, unresolved_charges=[Charge(accrued=True)]).ready


def test_a_material_open_question_blocks_the_close(books):
    _, leases, _, _ = books
    ids = [t.lease_id for t in leases[:5]]
    checklist = clean_checklist(ids, open_questions=[Question(DEFAULT_MATERIALITY + 1)])
    assert not checklist.ready


def test_an_immaterial_question_is_noted_but_does_not_block(books):
    _, leases, _, _ = books
    ids = [t.lease_id for t in leases[:5]]
    checklist = clean_checklist(ids, open_questions=[Question(100.00)])
    assert checklist.ready
    assert any("carried forward" in c.detail for c in checklist.checks)


# --- sign-off and the lock -------------------------------------------------

def test_only_a_controller_may_close(books):
    _, leases, _, _ = books
    ids = [t.lease_id for t in leases[:5]]
    with pytest.raises(PermissionError, match="only a controller"):
        sign_off(Period("ENT-CA", JUNE), clean_checklist(ids),
                 "regional_manager", "PER-RM-BAY", date(2026, 7, 9))


def test_a_failing_checklist_cannot_be_signed_off(books):
    _, leases, _, _ = books
    ids = [t.lease_id for t in leases[:5]]
    with pytest.raises(ValueError):
        sign_off(Period("ENT-CA", JUNE), clean_checklist(ids, gl_liability=1.0),
                 "controller", "PER-CTRL", date(2026, 7, 9))


def test_sign_off_records_who_and_when(books):
    _, leases, _, _ = books
    ids = [t.lease_id for t in leases[:5]]
    period = sign_off(Period("ENT-CA", JUNE), clean_checklist(ids),
                      "controller", "PER-CTRL", date(2026, 7, 9))
    assert period.status == CLOSED
    assert period.signed_off_by == "PER-CTRL"
    assert period.signed_off_at == date(2026, 7, 9)


def test_nothing_posts_into_a_closed_period(books):
    _, leases, _, _ = books
    ids = [t.lease_id for t in leases[:5]]
    period = sign_off(Period("ENT-CA", JUNE), clean_checklist(ids),
                      "controller", "PER-CTRL", date(2026, 7, 9))
    with pytest.raises(PeriodLocked):
        assert_open(period)


def test_an_open_period_accepts_postings():
    assert assert_open(Period("ENT-CA", JUNE)) is None


def test_a_period_cannot_be_closed_twice(books):
    _, leases, _, _ = books
    ids = [t.lease_id for t in leases[:5]]
    period = sign_off(Period("ENT-CA", JUNE), clean_checklist(ids),
                      "controller", "PER-CTRL", date(2026, 7, 9))
    with pytest.raises(PeriodLocked):
        sign_off(period, clean_checklist(ids), "controller", "PER-CTRL", date(2026, 7, 10))
