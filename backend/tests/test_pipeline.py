import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.docs.pipeline import Document, Page, Word, extract, render_page_png, union
from datagen.company import build_company
from datagen.leases import build_leases
from datagen.render_lease import render_lease


@pytest.fixture(scope="module")
def lease_pdf():
    company = build_company()
    return render_lease(build_leases(company)[0], company)


@pytest.fixture(scope="module")
def doc(lease_pdf):
    return extract(lease_pdf, sha256="a" * 64)


def test_lease_renders_within_the_expected_page_range(doc):
    assert 8 <= doc.page_count <= 12


def test_pages_are_numbered_from_one(doc):
    assert [p.number for p in doc.pages] == list(range(1, doc.page_count + 1))


def test_every_page_carries_a_text_layer(doc):
    assert all(p.has_text_layer for p in doc.pages)


def test_page_dimensions_are_letter(doc):
    assert round(doc.page(1).width) == 612
    assert round(doc.page(1).height) == 792


def test_numbered_text_labels_every_page(doc):
    body = doc.numbered_text()
    assert "=== PAGE 1 OF %d ===" % doc.page_count in body
    assert "=== PAGE %d OF %d ===" % (doc.page_count, doc.page_count) in body


def test_missing_page_raises(doc):
    with pytest.raises(KeyError):
        doc.page(99)


# --- the quotes the abstraction agent has to cite --------------------------

@pytest.mark.parametrize("quote", [
    "The initial Monthly Base Rent is $18,500.00 per month",
    "Tenant’s Proportionate Share is 9.69%",
    "the Monthly Base Rent shall increase by 3.00% per annum",
    "January 1, 2024",
    "December 31, 2028",
    "Dana Reyes",
])
def test_key_terms_are_findable_with_a_box(doc, quote):
    hits = doc.find(quote)
    assert hits, "%r not found" % quote
    page, (x0, y0, x1, y1) = hits[0]
    assert 1 <= page <= doc.page_count
    assert x1 > x0 and y1 > y0


def test_quote_can_start_inside_a_word(doc):
    """The PDF word is "$18,500.00"; a quote saying "18,500.00" must still box."""
    assert doc.find("18,500.00")


def test_quote_can_end_before_punctuation(doc):
    """The PDF word is "9.69%," with a comma."""
    assert doc.find("9.69%")


def test_quote_spanning_a_line_break_matches(doc):
    assert doc.find("not less than 270 days prior to the then-current Expiration Date")


def test_every_escalated_rent_appears_in_the_table(doc):
    for amount in ("18,500.00", "19,055.00", "19,626.65", "20,215.45", "20,821.91"):
        assert doc.find(amount), "%s missing from the rent schedule" % amount


def test_text_absent_from_the_document_is_not_found(doc):
    assert doc.find("Base Rent shall be payable in Dogecoin") == []


def test_search_is_case_and_quote_insensitive(doc):
    assert doc.find("tenant's proportionate share is 9.69%")


def test_empty_needle_finds_nothing(doc):
    assert doc.find("") == []


# --- page images -----------------------------------------------------------

def test_render_page_png(lease_pdf):
    png = render_page_png(lease_pdf, 3)
    assert png[:4] == b"\x89PNG"
    assert len(png) > 1000


def test_render_page_out_of_range(lease_pdf):
    with pytest.raises(KeyError):
        render_page_png(lease_pdf, 99)


# --- geometry --------------------------------------------------------------

def test_union_covers_every_word():
    words = [Word("a", 10, 20, 30, 40, 0, 0, 0), Word("b", 35, 18, 60, 44, 0, 0, 1)]
    assert union(words) == (10, 18, 60, 44)


def test_union_of_nothing_is_an_error():
    with pytest.raises(ValueError):
        union([])
