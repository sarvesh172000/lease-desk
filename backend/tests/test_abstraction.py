"""The abstraction agent and the citation check behind it.

No API key and no network: a fake client returns a fixed `AbstractedLease`, so
these tests are about what the system does with what a model returns — a good
model, a sloppy one, and a lying one.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.abstraction import (
    AbstractedLease, CITED_FIELDS, abstract_lease, check, confidence,
)
from app.docs.citations import STRONG, WEAK, locate
from app.docs.pipeline import extract
from app.llm.cache import ResponseCache
from app.llm.client import LLM
from app.llm.registry import PromptRegistry
from app.llm.usage import UsageLog
from datagen.company import build_company
from datagen.leases import build_leases
from datagen.render_lease import render_lease
from fakes import FakeClient, FakeResponse


@pytest.fixture(scope="module")
def doc():
    company = build_company()
    return extract(render_lease(build_leases(company)[0], company), sha256="a" * 64)


def good_model() -> AbstractedLease:
    """What a careful model returns: every quote verbatim, every page right."""
    return AbstractedLease(
        commencement={"value": "2024-01-01", "page": 2,
                      "quote": "shall commence on January 1, 2024"},
        expiration={"value": "2028-12-31", "page": 2,
                    "quote": "shall expire at 11:59 p.m. on December 31, 2028"},
        rentable_sf={"value": 6200, "page": 2,
                     "quote": "The Premises are stipulated to contain 6,200 rentable square feet"},
        proportionate_share_pct={"value": 9.69, "page": 2,
                                 "quote": "Tenant’s Proportionate Share is 9.69%"},
        base_rent_monthly={"value": 18500.00, "page": 3,
                           "quote": "The initial Monthly Base Rent is $18,500.00 per month"},
        escalation_kind={"value": "fixed_percent", "page": 3,
                         "quote": "the Monthly Base Rent shall increase by 3.00% per annum"},
        escalation_amount={"value": 0.03, "page": 3,
                           "quote": "the Monthly Base Rent shall increase by 3.00% per annum"},
        cam_estimate_psf_annual={"value": 11.50, "page": 4,
                                 "quote": "estimate of Operating Expenses is $11.50 per rentable square foot per annum"},
        security_deposit={"value": 37000.00, "page": 5,
                          "quote": "deposit with Landlord the sum of $37,000.00"},
        renewal_count={"value": 1, "page": 7,
                       "quote": "one (1) option to extend the Term"},
        renewal_years={"value": 3, "page": 7,
                       "quote": "an additional period of 3 years"},
        renewal_notice_days={"value": 270, "page": 7,
                             "quote": "not less than 270 days prior to the then-current Expiration Date"},
        authorized_representative={"value": "Dana Reyes", "page": 7,
                                   "quote": "Landlord designates Dana Reyes as the sole"},
        uncertain=[],
    )


def build_llm(tmp_path, extracted):
    return LLM(
        registry=PromptRegistry(),
        cache=ResponseCache(tmp_path / "cache"),
        usage=UsageLog(),
        client=FakeClient(lambda kw: FakeResponse(extracted)),
    )


# --- the happy path --------------------------------------------------------

def test_every_field_is_verified(doc, tmp_path):
    result = abstract_lease(doc, build_llm(tmp_path, good_model()), "LEASE-01")
    assert [f.name for f in result.needs_review] == []
    assert len(result.verified) == len(CITED_FIELDS)


def test_confidence_is_high_when_everything_cites(doc, tmp_path):
    result = abstract_lease(doc, build_llm(tmp_path, good_model()), "LEASE-01")
    assert result.confidence > 0.95


def test_abstraction_is_usable(doc, tmp_path):
    assert abstract_lease(doc, build_llm(tmp_path, good_model()), "LEASE-01").is_usable


def test_values_match_the_lease(doc, tmp_path):
    result = abstract_lease(doc, build_llm(tmp_path, good_model()), "LEASE-01")
    truth = build_leases(build_company())[0]
    assert result.value("commencement") == truth.commencement
    assert result.value("expiration") == truth.expiration
    assert result.value("base_rent_monthly") == truth.base_rent_monthly
    assert result.value("rentable_sf") == truth.rsf
    assert result.value("security_deposit") == truth.security_deposit
    assert result.value("renewal_notice_days") == truth.renewal.notice_days


def test_dates_are_coerced_to_date_objects(doc, tmp_path):
    result = abstract_lease(doc, build_llm(tmp_path, good_model()), "LEASE-01")
    assert isinstance(result.value("commencement"), date)


def test_counts_are_coerced_to_int(doc, tmp_path):
    result = abstract_lease(doc, build_llm(tmp_path, good_model()), "LEASE-01")
    assert result.value("renewal_count") == 1
    assert isinstance(result.value("renewal_count"), int)


def test_every_field_gets_a_page_and_a_box(doc, tmp_path):
    result = abstract_lease(doc, build_llm(tmp_path, good_model()), "LEASE-01")
    for f in result.fields:
        x0, y0, x1, y1 = f.citation.box
        assert x1 > x0 and y1 > y0, f.name
        assert 1 <= f.citation.page <= doc.page_count


def test_run_meta_carries_the_prompt_version(doc, tmp_path):
    result = abstract_lease(doc, build_llm(tmp_path, good_model()), "LEASE-01")
    assert result.meta.model_ref.startswith("claude-opus-5-5/lease_abstraction@v1+")


def test_the_lease_text_is_fenced_before_it_reaches_the_model(doc, tmp_path):
    llm = build_llm(tmp_path, good_model())
    abstract_lease(doc, llm, "LEASE-01")
    sent = llm._client.messages.calls[0]["messages"][0]["content"]
    assert "UNTRUSTED DATA" in sent
    assert "=== PAGE 1 OF 8 ===" in sent


# --- a model that gets things wrong ----------------------------------------

def test_an_invented_quote_is_uncited_and_flagged(doc, tmp_path):
    sloppy = good_model()
    sloppy.base_rent_monthly.quote = "Tenant shall pay rent of $25,000.00 in Dogecoin"
    sloppy.base_rent_monthly.value = 25000.00

    result = check(sloppy, doc, "LEASE-01")
    assert result.field("base_rent_monthly").status == "uncited"
    assert any("no sentence on any page matches" in f for f in result.flags)
    assert not result.is_usable


def test_an_invented_value_drops_confidence(doc, tmp_path):
    sloppy = good_model()
    sloppy.base_rent_monthly.quote = "Tenant shall pay rent of $25,000.00 in Dogecoin"
    assert check(sloppy, doc, "LEASE-01").confidence < 0.95


def test_a_wrong_page_is_corrected_and_flagged(doc):
    sloppy = good_model()
    sloppy.base_rent_monthly.page = 7  # the quote is really on page 3

    result = check(sloppy, doc, "LEASE-01")
    field = result.field("base_rent_monthly")
    assert field.citation.page == 3
    assert not field.page_matches
    assert any("not page 7 as claimed" in f for f in result.flags)


def test_a_paraphrased_quote_still_locates_but_is_not_perfect(doc):
    sloppy = good_model()
    sloppy.base_rent_monthly.quote = "The initial Monthly Base Rent is 18,500.00 per month"
    field = check(sloppy, doc, "LEASE-01").field("base_rent_monthly")
    assert field.citation is not None
    assert field.citation.score < 1.0


def test_a_reworded_quote_is_not_accepted(doc):
    """Semantically right, verbatim wrong. The model must quote, not summarise."""
    sloppy = good_model()
    sloppy.base_rent_monthly.quote = "Monthly rent starts at eighteen thousand five hundred dollars"
    assert check(sloppy, doc, "LEASE-01").field("base_rent_monthly").status == "uncited"


def test_uncertain_terms_are_surfaced_and_cost_confidence(doc):
    unsure = good_model()
    unsure.uncertain = ["CAM audit window is stated twice with different periods"]

    result = check(unsure, doc, "LEASE-01")
    assert not result.is_usable
    assert any("model unsure" in f for f in result.flags)
    assert result.confidence < check(good_model(), doc, "LEASE-01").confidence


def test_a_lease_needing_review_is_not_silently_usable(doc):
    sloppy = good_model()
    sloppy.security_deposit.quote = "no such sentence anywhere in this document at all"
    result = check(sloppy, doc, "LEASE-01")
    assert not result.is_usable
    assert "security_deposit" in [f.name for f in result.needs_review]


# --- confidence ------------------------------------------------------------

def test_confidence_of_nothing_is_zero():
    assert confidence([], []) == 0.0


def test_confidence_falls_as_fields_go_uncited(doc):
    base = check(good_model(), doc, "LEASE-01").confidence
    one_bad = good_model()
    one_bad.security_deposit.quote = "not in the document"
    two_bad = good_model()
    two_bad.security_deposit.quote = "not in the document"
    two_bad.renewal_years.quote = "also not in the document"

    assert check(two_bad, doc, "LEASE-01").confidence < \
        check(one_bad, doc, "LEASE-01").confidence < base


# --- the citation locator itself -------------------------------------------

def test_locate_returns_none_for_empty_quote(doc):
    assert locate(doc, "") is None
    assert locate(doc, "   ") is None


def test_locate_prefers_the_hinted_page_on_a_tie(doc):
    """"Page 3" appears in the footer of page 3 and nowhere else as a phrase."""
    hit = locate(doc, "Base Rent", page_hint=3)
    assert hit is not None
    assert hit.page == 3


def test_thresholds_are_ordered():
    assert 0 < WEAK < STRONG <= 1.0


# --- the abstraction has to be usable by the engine ------------------------

def test_abstracted_terms_rebuild_the_true_rent_schedule(doc, tmp_path):
    """The whole chain: PDF -> model -> citations -> engine.

    If the agent read the lease correctly, the schedule built from what it
    extracted is the schedule built from the terms the generator started with.
    """
    import json
    import tempfile

    from leasedesk.models import load_lease
    from leasedesk.schedule import build

    company = build_company()
    truth = build_leases(company)[0]
    result = abstract_lease(doc, build_llm(tmp_path, good_model()), "LEASE-01")

    payload = result.to_engine_json(
        location="Northbay PT — Daly City — Suite 210",
        lessor="Serramonte Retail Partners LLC",
        discount_rate=truth.discount_rate,
    )
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(payload, fh)
        path = fh.name

    rebuilt = build(load_lease(path))
    original = build(load_lease(_write(truth.to_engine_json(company))))

    assert [p.payment for p in rebuilt.periods] == [p.payment for p in original.periods]
    assert rebuilt.opening_liability == original.opening_liability
    assert abs(rebuilt.periods[-1].liability_close) < 0.01


def test_rebuilt_steps_match_the_rehearsed_numbers(doc, tmp_path):
    result = abstract_lease(doc, build_llm(tmp_path, good_model()), "LEASE-01")
    payload = result.to_engine_json("x", "y", 0.072)
    assert [s["monthly_rent"] for s in payload["steps"]] == [
        18500.00, 19055.00, 19626.65, 20215.45, 20821.91
    ]


def _write(payload):
    import json
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(payload, fh)
        return fh.name
