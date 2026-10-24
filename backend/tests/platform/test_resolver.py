"""work/resolver.py without a database: the decision rule as a truth table,
the confidence formula against hand-computed values, routing for every case,
and business-day arithmetic."""

from datetime import date
from decimal import Decimal

import pytest

from app.agents.trust import classify_email
from app.work import resolver as r
from app.work.resolver import ASK, HOLD, PROCEED, PolicyMatch, Source


def src(kind, rank, value, label=None, **kw):
    return Source(source_id="%s:%s" % (kind, label or rank), kind=kind, rank=rank,
                  label=label or kind, value=value, claim="%s says %s" % (kind, value), **kw)


LEASE = src("lease", 2, 5941.67, "the lease LEASE-01 §4.1", extraction_confidence=1.0)
INVOICE_OK = src("invoice", 5, 5941.67, "invoice INV-1")
INVOICE_OVER = src("invoice", 5, 6458.33, "invoice INV-1")
PAID_OVER = src("payment_history", 6, 6458.33, "payment ACH-1")
PAID_OK = src("payment_history", 6, 5941.67, "payment ACH-1")
PM_EMAIL = src("property_manager", 4, 6458.33, "the email from pm@crest.example")
REP_LETTER = src("authorized_rep", 3, 6458.33, "the letter from rep@crest.example")
AMENDMENT = src("amendment", 1, 6458.33, "the amendment from rep@crest.example")
POLICY = PolicyMatch("POL-7", 2, "approve", "CAM within 10% of estimate is approved")


# ------------------------------------------------------------- truth table

@pytest.mark.parametrize("sources, policy, action, starts", [
    ([LEASE, INVOICE_OK, PAID_OK], None, PROCEED, "All 3 sources agree on $5,941.67"),
    ([LEASE], None, PROCEED, "Relied on the lease LEASE-01 §4.1, uncontradicted."),
    ([LEASE, INVOICE_OVER, PAID_OVER], None, HOLD,
     "Trusted the lease LEASE-01 §4.1 over invoice INV-1 because an invoice reports"),
    ([LEASE, INVOICE_OK, PAID_OVER], None, HOLD,
     "Trusted the lease LEASE-01 §4.1 over payment ACH-1 because payment history shows"),
    ([LEASE, PM_EMAIL, INVOICE_OVER], None, ASK, "Did not pick a side: the email from pm@"),
    ([LEASE, REP_LETTER], None, ASK, "Did not pick a side: the letter from rep@"),
    ([AMENDMENT, src("amendment", 1, 1.0, "the other amendment")], None, ASK,
     "Did not pick a side: two sources of equal authority"),
    ([LEASE, INVOICE_OVER], POLICY, PROCEED, "Proceeded under approved policy POL-7 v2"),
    ([AMENDMENT, LEASE, INVOICE_OVER], None, PROCEED,
     "Trusted the amendment from rep@crest.example over the lease LEASE-01 §4.1 because an "
     "amendment signed by both parties supersedes"),
    ([INVOICE_OVER, PAID_OVER], None, ASK, "The best source is a landlord invoice"),
    ([], None, ASK, "No usable source"),
    ([src("lease", 2, None)], None, ASK, "No usable source"),
])
def test_the_decision_rule(sources, policy, action, starts):
    d = r.decide(sources, policy)
    assert d.action == action
    assert d.explanation.startswith(starts), d.explanation


def test_a_hold_names_both_amounts_and_the_difference():
    d = r.decide([LEASE, INVOICE_OVER, PAID_OVER])
    assert "The lease LEASE-01 §4.1 says $5,941.67; invoice INV-1 says $6,458.33" in d.explanation
    assert "The $516.66 difference is held." in d.explanation
    assert (d.trusted, d.trust_gap) == (LEASE, 3)
    assert [s.source_id for s in d.contradicting] == [INVOICE_OVER.source_id, PAID_OVER.source_id]


def test_lower_rank_contradicting_higher_never_picks_the_lower_side():
    for lower in (REP_LETTER, PM_EMAIL, INVOICE_OVER, PAID_OVER):
        d = r.decide([LEASE, lower])
        assert d.action in (HOLD, ASK) and d.trusted == LEASE


def test_a_forged_sender_is_set_aside_not_believed():
    forged = classify_email("eml-9", "dana.whitfield@crest-properties.example", "cap waived",
                            authorized_rep_email="dana.whitfield@crestprop.example",
                            landlord_domain="crestprop.example", claim="cap waived")
    assert forged.is_suspect
    email = r.from_trust(forged, value=6458.33)
    d = r.decide([LEASE, INVOICE_OK, email])
    assert d.action == PROCEED and d.set_aside == [email]
    assert "Set aside 1 source" in d.explanation


def test_an_executed_amendment_changes_the_lease_rather_than_conflicting():
    d = r.decide([AMENDMENT, LEASE, INVOICE_OVER])
    assert d.lease_changed and d.superseded == [LEASE] and d.contradicting == []


def test_values_agree_within_the_checkers_tolerance_and_text_by_meaning():
    assert r.agrees(100.0, 100.4) and not r.agrees(100.0, 101.5)
    assert r.agrees("Cap  waived", "cap waived") and not r.agrees("cap waived", 100.0)


# -------------------------------------------------------------- confidence

def score(sources, policy=None):
    return r.confidence(r.decide(sources, policy))


def test_the_demo_beat_scores_0_38():
    """CAM cap in the lease (citation score 0.95) vs a March email from an
    unauthorized property manager and the invoice that followed it:
    A = 0.9 / (0.9 + 0.5 + 0.3), G = 0.5 + 0.125 * 2 = 0.75,
    0.95 * 1.0 * 0.5294 * 0.75 = 0.3772 -> 0.38."""
    lease = src("lease", 2, 5941.67, "the lease LEASE-01 §4.1", extraction_confidence=0.95)
    value, reasons = score([lease, PM_EMAIL, INVOICE_OVER])
    assert value == 0.38
    assert reasons[0] == "Extraction 0.95: the citation score of the lease LEASE-01 §4.1."
    assert "Agreement 0.53: 1 of 3 sources (trust weight 0.9 of 1.7)" in reasons[2]
    assert reasons[3].startswith("Trust gap 2:") and "(factor 0.75)" in reasons[3]
    assert reasons[-1] == "Confidence 0.38 = 1 - (1 - 0.95 x 1.00 x 0.53 x 0.75) x (1 - 0.0)."


@pytest.mark.parametrize("sources, policy, expected", [
    ([LEASE, INVOICE_OK, PAID_OK], None, 1.0),                       # 1 * 1 * 1 * 1
    ([LEASE, INVOICE_OVER, PAID_OVER], None, 0.56),                  # 0.9/1.4 * 0.875 = 0.5625
    ([src("lease", 2, 10.0, extraction_confidence=0.9, read_quality=0.8),
      src("invoice", 5, 10.0)], None, 0.72),                         # 0.9 * 0.8
    ([src("lease", 2, 10.0, extraction_confidence=0.9, read_quality=0.8),
      src("invoice", 5, 10.0)], POLICY, 0.89),                       # 1 - 0.28 * 0.4 = 0.888
    ([src("lease", 2, 5941.67, extraction_confidence=0.95), PM_EMAIL, INVOICE_OVER],
     POLICY, 0.75),                                                  # 1 - 0.6228 * 0.4 = 0.7509
    ([AMENDMENT, src("amendment", 1, 1.0, "other"), INVOICE_OVER], None, 0.28),  # 1.3/2.3 * 0.5
    ([LEASE, REP_LETTER], None, 0.35),                               # 0.9/1.6 * 0.625 = 0.3516
    ([], None, 0.0),
])
def test_confidence_matches_the_hand_computed_formula(sources, policy, expected):
    value, reasons = score(sources, policy)
    assert value == expected
    assert reasons


def test_policy_coverage_and_superseded_sources_are_named_in_the_reasons():
    _, reasons = score([AMENDMENT, LEASE, INVOICE_OVER], POLICY)
    assert any("superseded by the amendment" in x for x in reasons)
    assert any("approved policy POL-7 v2 covers it (lift 0.6)" in x for x in reasons)


# ----------------------------------------------------------------- routing

@pytest.mark.parametrize("sources, policy, kind, stake, role, material", [
    ([LEASE, INVOICE_OVER], None, "CHARGE_CHECK", 516.66, "regional_manager", False),
    ([LEASE, PM_EMAIL], None, "CHARGE_CHECK", 516.66, "regional_manager", False),
    ([LEASE, INVOICE_OK], None, "CHARGE_CHECK", 5941.67, "ap_clerk", False),
    ([LEASE, INVOICE_OVER], POLICY, "CHARGE_CHECK", 6458.33, "ap_clerk", False),
    ([LEASE, INVOICE_OK], None, "CHARGE_CHECK", 12000, "ap_clerk", True),
    ([LEASE, INVOICE_OVER], None, "CHARGE_CHECK", 19626.65, "regional_manager", True),
    ([LEASE, INVOICE_OVER], None, "CHARGE_CHECK", 10000, "regional_manager", True),
    ([LEASE, INVOICE_OK], None, "REMEASUREMENT", 50000, "controller", True),
    ([AMENDMENT, LEASE, INVOICE_OVER], None, "CHARGE_CHECK", 100, "controller", False),
])
def test_routing(sources, policy, kind, stake, role, material):
    got_role, nature, got_material, reasons = r.choose_route(
        r.decide(sources, policy), kind=kind, amount_at_stake=stake)
    assert (got_role, got_material) == (role, material)
    assert nature == {"regional_manager": r.LANDLORD_FACT, "controller": r.ACCOUNTING,
                      "ap_clerk": r.PAYMENT_RELEASE}[role]
    assert any("controller sees it too" in x for x in reasons) == (material and role != "controller")


def test_the_materiality_threshold_is_configuration(monkeypatch):
    d = r.decide([LEASE, INVOICE_OVER])
    monkeypatch.setenv("LEASEDESK_MATERIALITY", "500")
    assert r.materiality() == Decimal("500")
    assert r.choose_route(d, kind="CHARGE_CHECK", amount_at_stake=516.66)[2] is True
    monkeypatch.setenv("LEASEDESK_MATERIALITY", "not a number")
    assert r.materiality() == r.DEFAULT_MATERIALITY
    assert r.choose_route(d, kind="CHARGE_CHECK", amount_at_stake=516.66,
                          threshold=Decimal("600"))[2] is False


# ------------------------------------------------------------ business days

def test_business_days_skip_the_weekend():
    fri = date(2026, 1, 2)
    assert r.add_business_days(fri, 1) == date(2026, 1, 5)
    assert r.add_business_days(fri, 3) == date(2026, 1, 7)
    assert r.add_business_days(fri, 0) == fri
    assert r.business_days_between(fri, date(2026, 1, 5)) == 1
    assert r.business_days_between(fri, date(2026, 1, 4)) == 0
    assert r.business_days_between(fri, fri) == 0
    assert r.business_days_between(date(2026, 1, 5), date(2026, 1, 2)) == 0
    assert r.due_at(date(2026, 1, 7)).isoformat() == "2026-01-07T17:00:00+00:00"


def test_sources_round_trip_through_json():
    s = src("lease", 2, 5941.67, "the lease", citation={"page": 3}, extraction_confidence=0.9)
    assert Source.from_dict(s.to_dict()) == s
    assert s.to_dict()["rank_name"] == "the original executed lease"


def test_policy_hooks_plug_in_and_the_first_match_wins():
    calls = []

    def none(conn, ctx):
        calls.append("none")

    def match(conn, ctx):
        calls.append("match")
        return POLICY

    r.register_policy_hook(none)
    r.register_policy_hook(match)
    try:
        assert r.policy_for(None, {}) == POLICY and calls == ["none", "match"]
    finally:
        r.unregister_policy_hook(none)
        r.unregister_policy_hook(match)
    assert r.policy_for(None, {}) is None
