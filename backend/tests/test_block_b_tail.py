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
from datagen.edgar import coverage, load_corpus, require_corpus, score
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


# --- the EDGAR corpus -----------------------------------------------------

@pytest.fixture(scope="module")
def edgar():
    """The cached SEC exhibits, or one clear failure saying they are gone.

    Every test below takes this rather than calling `load_corpus()` itself. An
    absent corpus used to fail ten of them on arithmetic while the ones that
    loop over each lease passed having checked nothing; now it fails here, for
    the stated reason. It is never skipped: the benchmark is part of the suite,
    and a green run with no benchmark in it is the thing worth avoiding.
    """
    return require_corpus()


def test_three_distinct_real_leases_are_cached(edgar):
    corpus = edgar
    assert len(corpus) == 3
    assert all(len(lease.text) > 20_000 for lease in corpus)


def test_the_duplicate_lease_is_excluded_from_scoring(edgar):
    """Inuvo is the renamed FindWhat.com and both filings attach the identical
    Colonial Bank Plaza lease. Scoring both double-weights one lease."""
    assert all(not lease.is_duplicate for lease in edgar)
    with_dupes = load_corpus(include_duplicates=True)
    assert len(with_dupes) == 4
    assert sum(1 for l in with_dupes if l.is_duplicate) == 1


def test_every_lease_records_where_it_came_from(edgar):
    for lease in edgar:
        assert lease.cik and lease.url.startswith("https://www.sec.gov/")
        assert lease.file_date and lease.document


def test_every_label_quote_really_is_in_the_filing(edgar):
    """The check that makes a hand label verifiable rather than asserted."""
    for lease in edgar:
        for name, label in lease.labels.items():
            if not label.is_absent:
                assert lease.quote_is_in_text(name), "%s/%s" % (lease.doc_id, name)


def test_a_stated_numeric_label_appears_verbatim_in_its_quote(edgar):
    """Stated labels are read off the page. Derived ones — "0.03" for "Three
    (3%) percent", a monthly figure computed from an annual — are correct but
    are not in the words, so they are marked and excused."""
    for lease in edgar:
        for label in lease.labelled:
            if not label.is_stated:
                continue
            if label.value.replace(".", "").replace("-", "").isdigit():
                head = label.value.rstrip("0").rstrip(".").split(".")[0]
                assert head in label.quote.replace(",", ""), \
                    "%s %s" % (lease.doc_id, label.field)


def test_every_derived_label_explains_its_derivation(edgar):
    for lease in edgar:
        for label in lease.labelled:
            if label.derived:
                assert label.note, "%s/%s" % (lease.doc_id, label.field)


def test_most_labels_are_read_rather_than_inferred(edgar):
    """A benchmark made mostly of inference is not testing reading."""
    labels = [l for lease in edgar for l in lease.labelled]
    stated = [l for l in labels if l.is_stated]
    assert len(stated) > len(labels) / 2


def test_an_absent_field_says_why(edgar):
    """Absent means the exhibit does not state the term, not that labelling
    gave up."""
    for lease in edgar:
        for label in lease.labels.values():
            if label.is_absent:
                assert label.absent_reason, "%s/%s" % (lease.doc_id, label.field)
                assert label.quote is None


def test_one_lease_carries_two_different_proportionate_shares(edgar):
    """38.55% for taxes and insurance, 33.08% for CAM on ground-floor area. A
    system assuming one share per lease gets this lease wrong."""
    lease = next(l for l in edgar if "sportsmans" in l.doc_id)
    assert lease.label("pro_rata_share").value == "38.55"
    assert lease.label("pro_rata_share_cam").value == "33.08"


def test_a_lease_that_contradicts_itself_is_labelled_with_a_note(edgar):
    lease = next(l for l in edgar if "findwhat" in l.doc_id)
    assert lease.label("rentable_sf").note
    assert "32,823" in lease.label("rentable_sf").note


def test_coverage_is_reported_per_field(edgar):
    numbers = coverage()
    assert numbers["cam_present"] == 3
    assert numbers["cam_cap"] == 0          # none of the three caps CAM
    assert numbers["rentable_sf"] == 3


def test_a_perfect_extractor_scores_one(edgar):
    corpus = edgar
    perfect = {l.doc_id: {n: lab.value for n, lab in l.labels.items()
                          if not lab.is_absent} for l in corpus}
    result = score(perfect)
    assert result["accuracy"] == 1.0
    assert result["wrong"] == 0 and result["fabricated"] == 0


def test_an_extractor_that_says_nothing_scores_zero(edgar):
    result = score({})
    assert result["accuracy"] == 0.0
    assert result["missed"] == result["scorable"]


def test_inventing_a_value_is_counted_separately_from_misreading_one(edgar):
    """Claiming a cap on a lease that has none is a different failure from
    reading the wrong cap."""
    corpus = edgar
    result = score({corpus[0].doc_id: {"cam_cap": "5%"}})
    assert result["fabricated"] == 1
    assert result["wrong"] == 0


def test_a_wrong_value_is_counted_as_wrong(edgar):
    corpus = edgar
    result = score({corpus[0].doc_id: {"term_years": "99"}})
    assert result["wrong"] == 1
    assert result["fabricated"] == 0


def test_numbers_compare_regardless_of_formatting(edgar):
    corpus = edgar
    lease = next(l for l in corpus if l.label("annual_base_rent").value)
    value = lease.label("annual_base_rent").value
    assert score({lease.doc_id: {"annual_base_rent": "%s" % float(value)}})["right"] >= 1


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
