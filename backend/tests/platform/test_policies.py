"""The policy rule format and its evaluation: pure, no database.

work/policies.py: a rule is validated with a readable error, and evaluation
is deterministic: the most specific scope wins, then the most conditions,
then the latest effective date, then the lowest id. Unknown facts never match.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.work.backtest import PastCharge, _dollars
from app.work.policies import (
    ChargeFacts,
    PolicyFormatError,
    StoredPolicy,
    apply_match,
    conditions_hold,
    evaluate,
    policy_ref,
    unapply,
    validate_rule,
)
from app.work.policy_learner import verdict

JAN = date(2026, 1, 1)


def rule(**over):
    base = {
        "name": "test:LEASE-01:cam_estimate:approve",
        "description": "Pay LEASE-01's estimate up to $6,458.33.",
        "scope": {"lease_id": "LEASE-01"},
        "when": {"charge_types": ["cam_estimate"], "max_amount": "6458.33"},
        "then": {"action": "approve"},
        "effective_from": "2026-01-01",
        "evidence_ids": ["question:1", "work_item:2"],
    }
    base.update(over)
    return base


def stored(pid, **over):
    r = validate_rule(rule(**over))
    return StoredPolicy(id=pid, name=r.name, version=r.version, status="approved", rule=r)


def facts(**over):
    base = dict(charge_id="c1", period=JAN, charge_type="cam_estimate",
                amount=Decimal("6458.33"), lease_id="LEASE-01", clinic_id="STORE-01",
                landlord_id="LL-SERRA", entity_id="ENT-CA", prior_paid=Decimal("5941.67"),
                supported=Decimal("5941.67"), checker_rule="operating_expense",
                checker_proposal="hold")
    base.update(over)
    return ChargeFacts(**base)


# --- format -----------------------------------------------------------------------

def test_a_well_formed_rule_parses_and_round_trips():
    r = validate_rule(rule())
    assert r.version == 1 and r.origin == "manual"
    assert r.when.max_amount == Decimal("6458.33")
    assert r.when.checker_rules == ["amount", "operating_expense"]   # the default
    again = validate_rule(r.to_json())
    assert again == r and again.fingerprint == r.fingerprint


def test_a_rule_given_as_a_json_string_parses():
    import json
    assert validate_rule(json.dumps(rule())).name == rule()["name"]


def test_the_fingerprint_ignores_words_and_evidence_but_not_behaviour():
    a = validate_rule(rule())
    assert validate_rule(rule(description="other words", evidence_ids=["x:1"])).fingerprint \
        == a.fingerprint
    assert validate_rule(rule(then={"action": "dispute"})).fingerprint != a.fingerprint


@pytest.mark.parametrize("bad, message", [
    (dict(colour="red"), "colour: Extra inputs are not permitted"),
    (dict(scope={}), "scope must name at least one"),
    (dict(scope={"lease": "LEASE-01"}), "scope.lease: Extra inputs"),
    (dict(when={"charge_types": []}), "when.charge_types"),
    (dict(when={"charge_types": ["base_rent"], "min_amount": "10", "max_amount": "5"}),
     "min_amount 10.00 is above max_amount 5.00"),
    (dict(when={"charge_types": ["base_rent"], "max_amount": "-1"}), "must not be negative"),
    (dict(when={"charge_types": ["base_rent"], "max_amount": "NaN"}), "finite"),
    (dict(then={}), "then must set an action"),
    (dict(then={"action": "pay_twice"}), "then.action"),
    (dict(effective_from="2026-02-01", effective_to="2026-01-01"), "is before effective_from"),
    (dict(name=""), "name"),
    (dict(name="drop table; --"), "name must be"),
    (dict(version=0), "version"),
    (dict(evidence_ids=["no-colon"]), "evidence ids look like"),
    (dict(when={"charge_types": ["base_rent", "base_rent"]}), "duplicates"),
])
def test_a_malformed_rule_is_refused_with_a_clear_error(bad, message):
    with pytest.raises(PolicyFormatError) as exc:
        validate_rule(rule(**bad))
    assert message in str(exc.value)
    assert str(exc.value).startswith("malformed policy rule: ")


@pytest.mark.parametrize("value", ["not json", "[1, 2]", 42, None])
def test_something_that_is_not_a_rule_object_is_refused(value):
    with pytest.raises(PolicyFormatError):
        validate_rule(value)


# --- evaluation -------------------------------------------------------------------

def test_a_rule_matches_inside_its_scope_dates_and_conditions():
    r = validate_rule(rule())
    assert conditions_hold(r, facts()) is True
    assert conditions_hold(r, facts(lease_id="LEASE-02")) is False
    assert conditions_hold(r, facts(charge_type="base_rent")) is False
    assert conditions_hold(r, facts(amount=Decimal("6458.34"))) is False
    assert conditions_hold(r, facts(period=date(2025, 12, 1))) is False
    assert conditions_hold(r, facts(period=date(2025, 12, 1)), ignore_dates=True) is True


def test_unknown_facts_never_match():
    prior = validate_rule(rule(when={"charge_types": ["cam_estimate"], "same_as_prior_paid": True}))
    assert conditions_hold(prior, facts(amount=Decimal("5941.67"))) is True
    assert conditions_hold(prior, facts(amount=Decimal("5941.67"), prior_paid=None)) is None
    lease = validate_rule(rule(when={"charge_types": ["cam_estimate"], "matches_lease": True}))
    assert conditions_hold(lease, facts(supported=None)) is None
    assert conditions_hold(validate_rule(rule()), facts(checker_rule=None)) is None
    assert evaluate([stored(1)], facts(checker_rule=None)) is None


def test_a_policy_never_decides_a_duplicate_or_premises_hold_unless_it_says_so():
    assert evaluate([stored(1)], facts(checker_rule="duplicate")) is None
    assert evaluate([stored(1)], facts(checker_rule="premises")) is None
    explicit = stored(2, when={"charge_types": ["cam_estimate"], "checker_rules": ["duplicate"]})
    assert evaluate([explicit], facts(checker_rule="duplicate")).policy.id == 2


def test_variance_and_lease_conditions():
    over = validate_rule(rule(when={"charge_types": ["cam_estimate"], "min_variance": "0.01"}))
    assert conditions_hold(over, facts()) is True                      # 516.66 over
    assert conditions_hold(over, facts(amount=Decimal("5941.67"))) is False
    matches = validate_rule(rule(when={"charge_types": ["cam_estimate"], "matches_lease": True}))
    assert conditions_hold(matches, facts(amount=Decimal("5942.50"))) is True   # within $1
    assert conditions_hold(matches, facts()) is False


def test_the_most_specific_scope_wins_then_conditions_then_date_then_id():
    landlord = stored(1, scope={"landlord_id": "LL-SERRA"}, then={"action": "hold"})
    lease = stored(2, then={"action": "approve"})
    entity = stored(3, scope={"entity_id": "ENT-CA"}, then={"action": "dispute"})
    m = evaluate([landlord, entity, lease], facts())
    assert m.policy.id == 2 and m.ref == policy_ref(2, 1) == "policy:2@v1"
    assert [p.id for p in m.conflicts] == [1, 3]

    narrower = stored(4, when={"charge_types": ["cam_estimate"], "max_amount": "7000",
                               "min_variance": "0.01"})
    assert evaluate([lease, narrower], facts()).policy.id == 4          # more conditions
    later = stored(5, effective_from="2026-01-01")
    earlier = stored(6, effective_from="2025-06-01")
    assert evaluate([earlier, later], facts()).policy.id == 5           # later start
    twin_a, twin_b = stored(8), stored(7)
    assert evaluate([twin_a, twin_b], facts()).policy.id == 7           # lowest id
    assert evaluate([twin_a, twin_b], facts()).conflicts == []          # same `then`


def test_evaluation_is_deterministic_whatever_the_order():
    ps = [stored(i, scope=s) for i, s in enumerate(
        [{"lease_id": "LEASE-01"}, {"clinic_id": "STORE-01"}, {"landlord_id": "LL-SERRA"},
         {"entity_id": "ENT-CA"}, {"lease_id": "LEASE-01", "clinic_id": "STORE-01"}], start=1)]
    import itertools
    winners = {evaluate(list(order), facts()).policy.id for order in itertools.permutations(ps)}
    assert winners == {5}


def test_applying_a_match_keeps_what_the_checker_said_and_unapply_restores_it():
    m = evaluate([stored(9, then={"action": "dispute", "account": "6150"})], facts())
    proposal, reason, ev = apply_match(m, "approve", "Matches the lease.", {"billed": 1})
    assert proposal == "hold" and ev["dispute"] is True and ev["account"] == "6150"
    assert ev["checker_proposal"] == "approve" and ev["policy"]["ref"] == "policy:9@v1"
    assert reason.startswith("Policy test:LEASE-01:cam_estimate:approve v1 (policy:9@v1)")
    back = unapply(ev, proposal, reason)
    assert back == ("approve", "Matches the lease.", {"billed": 1})


def test_a_then_without_an_action_keeps_the_checkers_proposal():
    m = evaluate([stored(3, then={"trust_source": "executed_amendment"})], facts())
    proposal, _, ev = apply_match(m, "hold", "over", {})
    assert proposal == "hold" and ev["trusted_source"] == "executed_amendment"


# --- answers ----------------------------------------------------------------------

@pytest.mark.parametrize("answer, expected", [
    ("Confirmed with Serramonte, the 2026 estimate is correct. Pay it.", "approve"),
    ("Yes, approved.", "approve"),
    ("That is not correct, dispute it.", "dispute"),
    ("Don't pay this, Suite 118 was handed back.", "dispute"),
    ("The estimate was never renegotiated.", "dispute"),
    ("I'll look into it next week.", None),
    ("", None),
    (None, None),
])
def test_an_answer_is_read_for_a_verdict_negations_first(answer, expected):
    assert verdict(answer) == expected


# --- backtest dollars -------------------------------------------------------------

def test_dollars_moved_by_a_change_of_decision():
    held = PastCharge(facts=facts(), source_id="X-L1", invoice_id="X", item_id=1)
    assert _dollars(held, "hold", "approve") == (Decimal("516.66"), "released")
    paid = PastCharge(facts=facts(supported=None), source_id="X-L1", invoice_id="X",
                      paid=Decimal("6458.33"))
    assert _dollars(paid, "approve", "dispute") == (Decimal("6458.33"), "withheld")
    assert _dollars(held, "hold", "dispute") == (Decimal("0.00"), "none")
