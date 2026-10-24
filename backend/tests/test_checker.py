"""The checker, scored against the answer key.

The three rule-order tests are regressions for real defects found by running
the old reconciler over January: a stray-suite line reported as an
underpayment, and a duplicate that carried the correct amount and so matched.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.checker import (
    APPROVE, HOLD, RULE_AMOUNT, RULE_DUPLICATE, RULE_OPERATING_EXPENSE,
    RULE_PREMISES, Charge, check_month, holds, total_held,
)
from app.engine.charges import TOLERANCE, expected
from app.engine.from_datagen import charges_from_invoices, rules_from_terms
from datagen.company import build_company
from datagen.errors import JANUARY_2026, real_errors
from datagen.leases import build_leases
from datagen.month import build_month

PERIOD = date(2026, 1, 1)


@pytest.fixture(scope="module")
def january():
    company = build_company()
    leases = build_leases(company)
    rules = rules_from_terms(leases, company)
    charges = charges_from_invoices(build_month(PERIOD, company, leases))
    return rules, charges, check_month(charges, rules, PERIOD)


# --- the acceptance criterion ----------------------------------------------

def test_catches_every_planted_error(january):
    _, _, findings = january
    held = {(f.charge.clinic_id, f.charge.charge_type) for f in holds(findings)}
    missed = [e.error_id for e in real_errors()
              if (e.clinic_id, e.charge_type) not in held]
    assert missed == [], "missed %s" % missed


def test_no_false_holds(january):
    """CLINIC-04's $400 step looks like an unexplained 3% jump and is correct."""
    _, _, findings = january
    odd = next(e for e in JANUARY_2026 if not e.is_error)
    held = {(f.charge.clinic_id, f.charge.charge_type) for f in holds(findings)}
    assert (odd.clinic_id, odd.charge_type) not in held


def test_amount_held_matches_the_answer_key(january):
    _, _, findings = january
    assert total_held(findings) == round(sum(e.variance for e in real_errors()), 2)
    assert total_held(findings) == 25_736.36


def test_every_charge_gets_exactly_one_finding(january):
    _, charges, findings = january
    assert len(findings) == len(charges)


def test_five_of_twelve_charges_are_held(january):
    _, _, findings = january
    assert len(holds(findings)) == 5


# --- rule order: the three regressions -------------------------------------

def test_a_stray_suite_is_a_premises_finding_not_a_rent_variance(january):
    """The old reconciler reported CLINIC-02 as UNDERpaying $4,880 when it had
    been overbilled $4,820. Asking about premises first is what fixes it."""
    _, _, findings = january
    stray = next(f for f in findings if f.charge.suite == "Suite 118")
    assert stray.rule == RULE_PREMISES
    assert stray.proposal == HOLD
    assert stray.supported == 0.0
    assert stray.variance == 4_820.00  # over, not under


def test_the_correct_rent_alongside_a_stray_line_is_still_approved(january):
    """CLINIC-02's real rent is right. One bad line must not condemn it."""
    _, _, findings = january
    real_rent = next(
        f for f in findings
        if f.charge.clinic_id == "CLINIC-02"
        and f.charge.charge_type == "base_rent"
        and f.charge.suite == "Suite 115"
    )
    assert real_rent.proposal == APPROVE


def test_a_duplicate_is_held_even_though_its_amount_is_correct(january):
    """This is why counting matters: both copies match the schedule exactly."""
    rules, _, findings = january
    dupe = next(f for f in findings if f.rule == RULE_DUPLICATE)
    assert dupe.proposal == HOLD
    assert dupe.billed == expected(rules["LEASE-01"], PERIOD).base_rent
    assert dupe.supported == 0.0
    assert dupe.related  # names the invoice that already billed it


def test_the_first_of_a_duplicate_pair_is_approved(january):
    _, _, findings = january
    first = next(
        f for f in findings
        if f.charge.clinic_id == "CLINIC-01"
        and f.charge.charge_type == "base_rent"
        and f.rule == RULE_AMOUNT
    )
    assert first.proposal == APPROVE


def test_an_operating_expense_error_is_its_own_rule(january):
    """E1 is invisible to a rent schedule; it needs the lease's psf estimate."""
    _, _, findings = january
    cam = next(f for f in holds(findings) if f.charge.charge_type == "cam_estimate")
    assert cam.rule == RULE_OPERATING_EXPENSE
    assert "per rentable square foot" in cam.reason


# --- reasons and evidence --------------------------------------------------

def test_every_hold_explains_itself_with_numbers(january):
    _, _, findings = january
    for f in holds(findings):
        assert len(f.reason) > 30
        assert any(ch.isdigit() for ch in f.reason)


def test_holds_cite_the_clause_that_proves_them(january):
    _, _, findings = january
    for f in holds(findings):
        assert f.proof is not None, f.rule
        assert f.proof.section and f.proof.quote


def test_describe_states_the_direction(january):
    _, _, findings = january
    over = next(f for f in holds(findings) if f.variance > 0)
    assert "over by" in over.describe()


# --- edges -----------------------------------------------------------------

def test_a_charge_with_no_confirmed_lease_is_held(january):
    rules, _, _ = january
    orphan = Charge("C1", "INV-1", "LEASE-99", "CLINIC-99", PERIOD,
                    "base_rent", "Suite 1", 5_000.00)
    findings = check_month([orphan], rules, PERIOD)
    assert findings[0].rule == RULE_PREMISES
    assert findings[0].proposal == HOLD
    assert "No confirmed lease" in findings[0].reason


def test_rounding_is_not_a_variance(january):
    rules, _, _ = january
    due = expected(rules["LEASE-03"], PERIOD).base_rent
    charge = Charge("C1", "INV-1", "LEASE-03", "CLINIC-03", PERIOD,
                    "base_rent", "Suite 100", due + TOLERANCE / 2)
    assert check_month([charge], rules, PERIOD)[0].proposal == APPROVE


def test_a_difference_above_tolerance_is_a_variance(january):
    rules, _, _ = january
    due = expected(rules["LEASE-03"], PERIOD).base_rent
    charge = Charge("C1", "INV-1", "LEASE-03", "CLINIC-03", PERIOD,
                    "base_rent", "Suite 100", due + TOLERANCE + 0.01)
    assert check_month([charge], rules, PERIOD)[0].proposal == HOLD


def test_charges_from_another_month_are_ignored(january):
    rules, charges, _ = january
    assert check_month(charges, rules, date(2026, 2, 1)) == []


def test_suite_matching_ignores_formatting(january):
    rules, _, _ = january
    charge = Charge("C1", "INV-1", "LEASE-03", "CLINIC-03", PERIOD,
                    "base_rent", "suite  100", expected(rules["LEASE-03"], PERIOD).base_rent)
    assert check_month([charge], rules, PERIOD)[0].proposal == APPROVE


def test_result_does_not_depend_on_charge_order(january):
    rules, charges, findings = january
    shuffled = list(reversed(charges))
    again = check_month(shuffled, rules, PERIOD)
    assert total_held(again) == total_held(findings)
    assert len(holds(again)) == len(holds(findings))
