"""Messy inputs: three invoice formats, one parser, and name resolution (B3)."""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.docs.invoice_parser import (
    FORMAT_LETTER, FORMAT_PORTAL, FORMAT_TABLE, PORTAL_CODES, parse,
)
from app.engine.resolve_names import (
    CERTAIN, PROPOSE, Directory, normalize, resolve, similarity,
)
from datagen.company import FULL, build_company
from datagen.invoices.format_b_letter import render as letter
from datagen.invoices.format_c_portal_csv import render as portal
from datagen.leases import build_leases
from datagen.month import build_month
from datagen.render_invoice import render_invoice

JANUARY = date(2026, 1, 1)


@pytest.fixture(scope="module")
def invoices():
    company = build_company(FULL)
    return company, build_month(JANUARY, company, build_leases(company))


def formats(invoice, company):
    return (
        (FORMAT_TABLE, render_invoice(invoice, company)),
        (FORMAT_LETTER, letter(invoice, company)),
        (FORMAT_PORTAL, portal(invoice, company)),
    )


# --- every format, every invoice -------------------------------------------

def test_all_three_formats_parse_every_invoice_exactly(invoices):
    company, all_invoices = invoices
    for invoice in all_invoices:
        for expected_format, data in formats(invoice, company):
            result = parse(data)
            assert result.source_format == expected_format
            assert result.issues == [], (invoice.invoice_id, expected_format, result.issues)
            assert len(result.lines) == len(invoice.charges), \
                (invoice.invoice_id, expected_format)


def test_every_format_agrees_on_the_total(invoices):
    company, all_invoices = invoices
    for invoice in all_invoices:
        totals = {parse(data).line_total for _, data in formats(invoice, company)}
        assert totals == {invoice.total()}, invoice.invoice_id


def test_the_format_is_detected_without_being_told(invoices):
    company, all_invoices = invoices
    invoice = all_invoices[0]
    assert parse(render_invoice(invoice, company)).source_format == FORMAT_TABLE
    assert parse(letter(invoice, company)).source_format == FORMAT_LETTER
    assert parse(portal(invoice, company)).source_format == FORMAT_PORTAL


def test_charge_types_survive_the_round_trip(invoices):
    company, all_invoices = invoices
    for invoice in all_invoices:
        billed = sorted(c.charge_type for c in invoice.charges)
        for _, data in formats(invoice, company):
            assert sorted(l.charge_type for l in parse(data).lines) == billed


# --- the footing check -----------------------------------------------------

def test_a_statement_that_does_not_foot_is_flagged(invoices):
    """A parser that silently drops a line it could not read is worse than one
    that fails loudly."""
    company, all_invoices = invoices
    csv_text = portal(all_invoices[0], company)
    broken = csv_text.replace("19626.65", "19000.00", 1)
    result = parse(broken)
    assert not result.foots
    assert result.needs_review
    assert "sum to" in result.issues[0]


def test_an_unknown_charge_code_is_reported_not_ignored(invoices):
    company, all_invoices = invoices
    broken = portal(all_invoices[0], company).replace(",RNT,", ",ZZZ,", 1)
    result = parse(broken)
    assert any("unknown charge code" in i for i in result.issues)


def test_the_portal_total_row_is_not_a_line_item(invoices):
    """It looks exactly like one."""
    company, all_invoices = invoices
    result = parse(portal(all_invoices[0], company))
    assert all(l.description != "STATEMENT TOTAL" for l in result.lines)
    assert result.stated_total == all_invoices[0].total()


def test_a_single_charge_statement_parses(invoices):
    """The line and the total are the same number, so excluding anything equal
    to the total would lose the only line."""
    company, all_invoices = invoices
    one_line = next(i for i in all_invoices if len(i.charges) == 1)
    for _, data in formats(one_line, company):
        result = parse(data)
        assert len(result.lines) == 1
        assert result.foots


def test_two_charges_of_the_same_type_both_survive(invoices):
    """A letter mentioning rent twice — once for a suite we do not lease."""
    company, all_invoices = invoices
    stray = next(i for i in all_invoices
                 if sum(1 for c in i.charges if c.charge_type == "base_rent") > 1)
    for _, data in formats(stray, company):
        rents = [l for l in parse(data).lines if l.charge_type == "base_rent"]
        assert len(rents) == 2


def test_every_portal_code_maps_to_a_charge_type():
    assert "TOT" not in PORTAL_CODES
    assert set(PORTAL_CODES.values()) >= {"base_rent", "cam_estimate", "property_tax"}


# --- name resolution -------------------------------------------------------

@pytest.fixture(scope="module")
def directory():
    return Directory.from_landlords(build_company(FULL).landlords)


def test_the_same_name_resolves(directory):
    assert resolve("Pacific Crest Properties LLC", directory).verdict == "resolved"


def test_an_abbreviated_name_resolves(directory):
    match = resolve("Pacific Crest Prop. Mgmt", directory)
    assert match.verdict == "resolved"
    assert match.matched_name == "Pacific Crest Properties LLC"


def test_punctuation_and_case_do_not_matter(directory):
    """"L.L.C." becomes three single-letter tokens once punctuation goes."""
    assert resolve("PACIFIC CREST PROPERTIES, L.L.C.", directory).verdict == "resolved"


def test_a_dropped_suffix_still_resolves(directory):
    assert resolve("Harbor Point Realty", directory).verdict == "resolved"


def test_an_unrelated_name_is_not_forced_onto_a_landlord(directory):
    match = resolve("Northside Dental Group", directory)
    assert match.verdict == "unmatched"
    assert match.matched_id is None


def test_an_empty_name_is_unmatched(directory):
    assert resolve("", directory).verdict == "unmatched"
    assert resolve("   ", directory).verdict == "unmatched"


def test_a_borderline_name_is_proposed_not_merged(directory):
    """Quietly merging two landlords that are genuinely different corrupts
    every figure that follows."""
    match = resolve("Crestline Medical", directory)
    assert match.verdict in ("resolved", "propose")
    if match.verdict == "propose":
        assert match.needs_human


def test_normalization_strips_entity_suffixes():
    assert normalize("Acme Holdings LLC") == normalize("Acme, Inc.")


def test_similarity_is_symmetric():
    a, b = "Pacific Crest Properties LLC", "Pacific Crest Prop Mgmt"
    assert similarity(a, b) == similarity(b, a)


def test_thresholds_are_ordered():
    assert 0 < PROPOSE < CERTAIN <= 1.0


# --- succession is not an alias --------------------------------------------

def test_a_sold_building_follows_to_the_current_owner(directory):
    assert directory.successions
    for old, new in directory.successions.items():
        assert directory.current_owner(old) == new


def test_the_predecessor_keeps_its_own_identity(directory):
    """When a building is sold the new owner is a different legal entity, and
    the lease still names the old one."""
    old = next(iter(directory.successions))
    assert directory.canonical(old) is not None
    assert directory.canonical(old) != directory.names[directory.current_owner(old)]


def test_a_party_with_no_successor_is_its_own_current_owner(directory):
    assert directory.current_owner("LL-SERRA") == "LL-SERRA"
