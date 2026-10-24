"""CPI escalation, the EDGAR corpus, counterfactual replay, personas."""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.checker import check_month
from app.engine.counterfactual import (
    AMOUNT_CHANGED, NOW_APPROVED, learning_curve, replay,
)
from app.engine.from_datagen import charges_from_invoices, rules_from_terms
from app.engine.rent import (
    US_CITY_AVERAGE, WEST_REGION, CpiSeries, CpiTerms, IndexUnavailable,
    escalate, escalate_cpi,
)
from app.personas.people import (
    AGREE, PERSONAS, REFUSE, UNAVAILABLE, UNKNOWN, answer, route,
)
from datagen.company import build_company
from datagen.edgar import NEEDS_HUMAN_LABEL, coverage, load_corpus
from datagen.leases import SECOND_AMENDMENT, amended, build_leases
from datagen.month import build_month

JULY = date(2026, 7, 1)


@pytest.fixture(scope="module")
def series():
    return CpiSeries.load()


# --- CPI escalation --------------------------------------------------------

def test_the_snapshot_holds_both_published_series(series):
    assert series.has(US_CITY_AVERAGE, 2024, 1)
    assert series.has(WEST_REGION, 2024, 1)


def test_an_escalation_uses_the_published_index(series):
    result = escalate_cpi(10_000.00, JULY, CpiTerms(US_CITY_AVERAGE, 2024, 1, 2), series)
    assert result.base[2] == series.value(US_CITY_AVERAGE, 2024, 1)
    assert result.new_rent > result.prior_rent


def test_the_lookback_measures_an_earlier_month(series):
    """The index for a month is published weeks later."""
    result = escalate_cpi(10_000.00, JULY, CpiTerms(US_CITY_AVERAGE, 2024, 1, 2), series)
    assert (result.current[0], result.current[1]) == (2026, 5)


def test_a_cap_limits_the_increase(series):
    uncapped = escalate_cpi(10_000.00, JULY, CpiTerms(US_CITY_AVERAGE, 2024, 1, 2), series)
    capped = escalate_cpi(10_000.00, JULY,
                          CpiTerms(US_CITY_AVERAGE, 2024, 1, 2, cap_pct=0.03), series)
    assert capped.new_rent < uncapped.new_rent
    assert capped.applied_pct == 0.03
    assert capped.adjustment == "cap"
    assert capped.was_collared


def test_a_floor_raises_a_small_increase(series):
    result = escalate_cpi(10_000.00, JULY,
                          CpiTerms(US_CITY_AVERAGE, 2026, 1, 2, floor_pct=0.04), series)
    assert result.applied_pct == 0.04
    assert result.adjustment == "floor"


def test_a_collar_applies_both_ends(series):
    terms = CpiTerms(WEST_REGION, 2023, 6, 2, floor_pct=0.02, cap_pct=0.05)
    result = escalate_cpi(10_000.00, JULY, terms, series)
    assert 0.02 <= result.applied_pct <= 0.05


def test_the_raw_move_is_reported_even_when_collared(series):
    """A controller has to see what the index actually did."""
    result = escalate_cpi(10_000.00, JULY,
                          CpiTerms(US_CITY_AVERAGE, 2024, 1, 2, cap_pct=0.03), series)
    assert result.raw_pct > result.applied_pct


def test_the_evidence_names_the_series_and_both_months(series):
    result = escalate_cpi(10_000.00, JULY, CpiTerms(US_CITY_AVERAGE, 2024, 1, 2), series)
    description = result.describe()
    assert US_CITY_AVERAGE in description
    assert "2024-01" in description and "2026-05" in description


def test_the_two_series_give_different_answers(series):
    us = escalate_cpi(10_000.00, JULY, CpiTerms(US_CITY_AVERAGE, 2024, 1, 2), series)
    west = escalate_cpi(10_000.00, JULY, CpiTerms(WEST_REGION, 2024, 1, 2), series)
    assert us.new_rent != west.new_rent


def test_an_unpublished_month_refuses_rather_than_approximates(series):
    """Substituting a nearby month silently changes the rent."""
    with pytest.raises(IndexUnavailable):
        escalate_cpi(10_000.00, date(2031, 1, 1),
                     CpiTerms(US_CITY_AVERAGE, 2024, 1, 2), series)


def test_fixed_escalations_still_work():
    assert escalate(10_000.00, "fixed_percent", 0.03) == 10_300.00
    assert escalate(10_000.00, "fixed_step", 275.00) == 10_275.00


def test_a_cpi_escalation_needs_its_inputs():
    with pytest.raises(ValueError):
        escalate(10_000.00, "cpi", 0.0)


def test_an_unknown_kind_is_an_error():
    with pytest.raises(ValueError, match="unknown escalation"):
        escalate(10_000.00, "vibes", 0.0)


# --- the EDGAR corpus ------------------------------------------------------

def test_real_leases_are_cached():
    corpus = load_corpus()
    assert len(corpus) >= 3
    assert all(len(lease.text) > 20_000 for lease in corpus)


def test_every_lease_records_where_it_came_from():
    for lease in load_corpus():
        assert lease.cik and lease.url.startswith("https://www.sec.gov/")
        assert lease.file_date


def test_every_label_carries_the_sentence_that_proves_it():
    for lease in load_corpus():
        for label in lease.labelled:
            assert label.quote
            if label.value != "yes":
                assert label.value.replace(",", "") in label.quote.replace(",", "")


def test_unstated_terms_are_absent_not_guessed():
    """A benchmark that invents an answer measures nothing."""
    corpus = load_corpus()
    absent = [l for lease in corpus for l in lease.labels.values() if l.is_absent]
    assert absent
    assert all(l.value is None and l.quote is None for l in absent)


def test_the_fields_needing_a_person_are_listed():
    """Reading a ninety-page exhibit properly is a person's job, and
    pretending otherwise would make the EDGAR score meaningless."""
    assert len(NEEDS_HUMAN_LABEL) >= 10
    assert "rentable_sf" in NEEDS_HUMAN_LABEL


def test_coverage_is_reported_honestly():
    numbers = coverage()
    assert numbers["cam_present"] == len(load_corpus())
    assert numbers["monthly_base_rent"] < len(load_corpus())


# --- counterfactual replay -------------------------------------------------

@pytest.fixture(scope="module")
def july_replay():
    company = build_company()
    base = build_leases(company)
    after = [amended(t, SECOND_AMENDMENT) if t.lease_id == "LEASE-01" else t
             for t in base]
    charges = charges_from_invoices(build_month(JULY, company, after))
    return replay(
        check_month(charges, rules_from_terms(base, company), JULY),
        check_month(charges, rules_from_terms(after, company), JULY),
        JULY, date(2026, 10, 24))


def test_the_amendment_removes_the_july_hold(july_replay):
    assert july_replay.questions_avoided == 1
    assert july_replay.held_then > july_replay.held_now


def test_the_change_is_attributed_to_the_right_charge(july_replay):
    change = next(c for c in july_replay.changes if c.kind == NOW_APPROVED)
    assert change.clinic_id == "CLINIC-01"
    assert change.then_supported == 19_626.65
    assert change.now_supported == 17_400.00


def test_dollars_moved_is_the_variance(july_replay):
    assert july_replay.dollars_moved == 2_226.65


def test_unchanged_charges_are_not_reported(july_replay):
    assert july_replay.unchanged == july_replay.charges_compared - len(july_replay.changes)
    assert july_replay.unchanged > 0


def test_replaying_against_itself_changes_nothing():
    company = build_company()
    leases = build_leases(company)
    rules = rules_from_terms(leases, company)
    charges = charges_from_invoices(build_month(JULY, company, leases))
    findings = check_month(charges, rules, JULY)
    result = replay(findings, findings, JULY, date(2026, 10, 24))
    assert result.changes == []
    assert "unchanged" in result.describe()


def test_the_learning_curve_reports_holds_then_and_now(july_replay):
    curve = learning_curve([july_replay])
    assert curve == [("2026-07", july_replay.held_then, july_replay.held_now)]


# --- personas --------------------------------------------------------------

ASKED = date(2026, 8, 3)
# Availability is a separate behaviour with its own tests below. Pinning the
# slot keeps the fact and refusal tests about facts and refusals.
AVAILABLE = 9


def test_a_persona_answers_from_its_own_facts():
    result = answer(PERSONAS["PER-RM-BAY"], "Q1",
                    "Did Serramonte agree to reduce the rent on Suite 210?",
                    ASKED, sequence=AVAILABLE)
    assert result.verdict == AGREE
    assert "17,400" in result.basis


def test_a_persona_refuses_what_it_would_refuse():
    result = answer(PERSONAS["PER-RM-BAY"], "Q2",
                    "Should we pay the parking lot repaving charge?",
                    ASKED, sequence=AVAILABLE)
    assert result.verdict == REFUSE


def test_a_specific_fact_beats_a_general_objection():
    """"May we post the remeasurement entries?" is answered by a fact, and must
    not be caught by a standing refusal about posting without a document."""
    result = answer(PERSONAS["PER-CTRL"], "Q3",
                    "May we post the remeasurement entries?", ASKED)
    assert result.verdict == AGREE


def test_the_controller_still_refuses_an_untied_close():
    result = answer(PERSONAS["PER-CTRL"], "Q4",
                    "Can we close while the subledger does not tie?", ASKED)
    assert result.verdict == REFUSE


def test_a_question_outside_the_facts_stays_open():
    """Asked something its facts do not cover, a persona says so."""
    result = answer(PERSONAS["PER-AP"], "Q5",
                    "What is the cap rate on the Phoenix building?",
                    ASKED, sequence=AVAILABLE)
    assert result.verdict == UNKNOWN
    assert not result.settles


def test_every_answer_is_tagged_simulated():
    """So no demo can pass a generated approval off as a human one."""
    for persona in PERSONAS.values():
        assert answer(persona, "Q", "anything at all", ASKED,
                      sequence=AVAILABLE).simulated


def test_someone_is_sometimes_unavailable():
    verdicts = {answer(PERSONAS["PER-RM-DESERT"], "Q%03d" % i,
                       "the Sahara escalation", ASKED).verdict
                for i in range(40)}
    assert UNAVAILABLE in verdicts


def test_but_not_always_unavailable():
    """Defaulting the counter to zero made anyone with any unavailability
    unavailable every single time."""
    verdicts = [answer(PERSONAS["PER-RM-BAY"], "Q%03d" % i,
                       "rent on Suite 210", ASKED).verdict for i in range(40)]
    assert verdicts.count(AGREE) > verdicts.count(UNAVAILABLE)


def test_the_controller_is_always_available():
    verdicts = {answer(PERSONAS["PER-CTRL"], "Q%03d" % i, "materiality", ASKED).verdict
                for i in range(20)}
    assert UNAVAILABLE not in verdicts


def test_answers_are_deterministic():
    a = answer(PERSONAS["PER-CTRL"], "Q9", "materiality for the close", ASKED)
    b = answer(PERSONAS["PER-CTRL"], "Q9", "materiality for the close", ASKED)
    assert a.body == b.body and a.answered_on == b.answered_on


def test_routing_finds_the_manager_for_a_region():
    assert route("regional_manager", "REG-SOCAL").person_id == "PER-RM-SOCAL"
    assert route("controller").person_id == "PER-CTRL"
    assert route("regional_manager", "REG-NOWHERE") is None
