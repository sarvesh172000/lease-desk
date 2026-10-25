"""The CAM engine and the shared-pool check (chunk B4).

The last section is the one that matters: a vendor line billed in full to two
tenants in the same center. Each statement is unremarkable on its own.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.engine.cam import (
    CONTROLLABLE_CAP_PCT, MANAGEMENT_FEE_CAP_PCT, CamRule,
    allowed, check_shared_pool, check_statement,
)
from datagen.cam_pools import NON_CONTROLLABLE, build_pools
from datagen.company import build_company

GROSS = 1_240_000.00


@pytest.fixture(scope="module")
def serramonte():
    company = build_company()
    pool = build_pools(company, 2025)["CTR-SERRA"]
    center = company.center("CTR-SERRA")
    rules = [
        CamRule(lease, clinic, "CTR-SERRA", company.clinic(clinic).rsf, center.total_rsf)
        for lease, clinic in (("LEASE-01", "CLINIC-01"), ("LEASE-02", "CLINIC-02"))
    ]
    return company, pool, rules


# --- the pool --------------------------------------------------------------

def test_the_pool_separates_recoverable_from_excluded(serramonte):
    _, pool, _ = serramonte
    assert pool.recoverable() < pool.total()
    assert pool.excluded_lines()


def test_taxes_and_insurance_are_not_controllable(serramonte):
    _, pool, _ = serramonte
    for line in pool.lines:
        if line.category in NON_CONTROLLABLE:
            assert not line.controllable


def test_an_excluded_line_is_never_controllable(serramonte):
    _, pool, _ = serramonte
    assert all(not l.controllable for l in pool.excluded_lines())


# --- what the lease supports ----------------------------------------------

def test_a_capital_item_is_excluded_entirely(serramonte):
    _, pool, rules = serramonte
    line = allowed(rules[0], pool, GROSS).line("capital")
    assert line.recoverable == 0.0
    assert line.share == 0.0
    assert "capital" in line.reason.lower()


def test_the_management_fee_is_capped_at_the_lease_percentage(serramonte):
    _, pool, rules = serramonte
    line = allowed(rules[0], pool, GROSS).line("management_fee")
    assert line.recoverable == round(GROSS * MANAGEMENT_FEE_CAP_PCT, 2)
    assert line.recoverable < line.pool_amount


def test_each_share_is_pro_rata_of_the_recoverable_amount(serramonte):
    _, pool, rules = serramonte
    rule = rules[0]
    for line in allowed(rule, pool, GROSS).lines:
        assert line.share == round(line.recoverable * rule.pro_rata, 2)


def test_the_lease_denominator_is_used_not_the_real_area(serramonte):
    """A lease can stipulate an area that is not the building's actual one."""
    company, pool, _ = serramonte
    stipulated = CamRule("L", "CLINIC-01", "CTR-SERRA",
                         company.clinic("CLINIC-01").rsf, 50_000)
    actual = CamRule("L", "CLINIC-01", "CTR-SERRA",
                     company.clinic("CLINIC-01").rsf,
                     company.center("CTR-SERRA").total_rsf)
    assert allowed(stipulated, pool, GROSS).total() > allowed(actual, pool, GROSS).total()


def test_the_controllable_cap_limits_year_on_year_growth(serramonte):
    _, pool, rules = serramonte
    uncapped = allowed(rules[0], pool, GROSS)
    capped = allowed(rules[0], pool, GROSS, prior_year_controllable=10_000.00)
    assert capped.total() < uncapped.total()
    assert capped.notes


def test_the_cap_does_not_touch_taxes_or_insurance(serramonte):
    _, pool, rules = serramonte
    uncapped = allowed(rules[0], pool, GROSS)
    capped = allowed(rules[0], pool, GROSS, prior_year_controllable=10_000.00)
    for category in ("property_tax", "insurance", "utilities"):
        assert capped.line(category).share == uncapped.line(category).share


def test_no_cap_applies_without_a_prior_year(serramonte):
    _, pool, rules = serramonte
    assert allowed(rules[0], pool, GROSS).notes == []


# --- checking a statement --------------------------------------------------

def test_a_statement_that_matches_raises_nothing(serramonte):
    _, pool, rules = serramonte
    due = allowed(rules[0], pool, GROSS)
    billed = {l.category: l.share for l in due.lines}
    assert check_statement(rules[0], pool, billed, GROSS) == []


def test_an_excluded_cost_passed_through_is_caught(serramonte):
    _, pool, rules = serramonte
    findings = check_statement(rules[0], pool, {"capital": 8_200.00}, GROSS)
    assert len(findings) == 1
    assert findings[0].rule == "excluded_cost"
    assert findings[0].supported == 0.0
    assert findings[0].section == "4.3"


def test_a_management_fee_above_the_cap_is_caught(serramonte):
    _, pool, rules = serramonte
    over = allowed(rules[0], pool, GROSS).line("management_fee").share + 900.00
    findings = check_statement(rules[0], pool, {"management_fee": over}, GROSS)
    assert findings[0].rule == "management_fee_cap"
    assert findings[0].section == "4.4"


def test_rounding_is_not_a_variance(serramonte):
    _, pool, rules = serramonte
    due = allowed(rules[0], pool, GROSS).line("janitorial").share
    assert check_statement(rules[0], pool, {"janitorial": due + 0.40}, GROSS) == []


def test_every_finding_cites_a_clause(serramonte):
    _, pool, rules = serramonte
    findings = check_statement(rules[0], pool, {"capital": 8_200.00,
                                                "janitorial": 99_000.00}, GROSS)
    assert findings
    for f in findings:
        assert f.section and f.quote


# --- the shared-pool check -------------------------------------------------

def test_the_parking_lot_is_billed_in_full_to_both_suites(serramonte):
    _, pool, _ = serramonte
    doubled = pool.double_billed()
    assert len(doubled) == 1
    assert set(doubled[0].billed_in_full_to) == {"CLINIC-01", "CLINIC-02"}


def test_the_shared_pool_check_catches_it(serramonte):
    _, pool, rules = serramonte
    findings = check_shared_pool(rules, pool)
    assert len(findings) == 1
    assert findings[0].rule == "shared_pool"


def test_the_landlord_recovered_more_than_it_spent(serramonte):
    _, pool, rules = serramonte
    finding = check_shared_pool(rules, pool)[0]
    line = pool.double_billed()[0]
    assert finding.billed == round(line.amount * 2, 2)
    assert finding.billed > line.amount


def test_an_excluded_double_billed_line_supports_nothing(serramonte):
    _, pool, rules = serramonte
    finding = check_shared_pool(rules, pool)[0]
    assert finding.supported == 0.0
    assert finding.variance == finding.billed


def test_the_finding_names_every_affected_clinic(serramonte):
    _, pool, rules = serramonte
    finding = check_shared_pool(rules, pool)[0]
    assert set(finding.related_clinics) == {"CLINIC-01", "CLINIC-02"}


def test_it_cites_the_no_double_allocation_clause(serramonte):
    _, pool, rules = serramonte
    finding = check_shared_pool(rules, pool)[0]
    assert finding.section == "4.8"
    assert "more than once" in finding.quote


def test_one_clinic_alone_cannot_see_it(serramonte):
    """This is the whole point: a single statement is unremarkable."""
    _, pool, rules = serramonte
    assert check_shared_pool([rules[0]], pool) == []


def test_a_center_with_no_double_billing_is_clean(serramonte):
    company, _, _ = serramonte
    pool = build_pools(company, 2025)["CTR-BAYVIEW"]
    rules = [CamRule("L", c.clinic_id, "CTR-BAYVIEW", c.rsf,
                     company.center("CTR-BAYVIEW").total_rsf)
             for c in company.clinics_in("CTR-BAYVIEW")]
    assert check_shared_pool(rules, pool) == []
