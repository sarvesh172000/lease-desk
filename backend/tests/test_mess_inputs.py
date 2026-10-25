"""Scans, the accountant's spreadsheet, landlord replies, the classifier (B3)."""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.classify import (
    AMENDMENT, CREDIT_MEMO, KINDS, LEASE, OTHER, RENT_INVOICE, SCANNED, UNSURE,
    classify, classify_document,
)
from app.docs.pipeline import extract
from datagen.company import build_company
from datagen.emails import build_emails
from datagen.invoices.format_c_portal_csv import render as portal
from datagen.leases import build_leases
from datagen.month import build_month
from datagen.render_invoice import render_invoice
from datagen.render_lease import render_lease
from datagen.replies import (
    FULL_CREDIT, OUTCOMES, PARTIAL_CREDIT, QUERIED, REFUSED, build_replies,
)
from datagen.scans import BAD_FAX, CLEAN_SCAN, OFFICE_COPIER, has_text_layer, scan
from datagen.tracker_xlsx import build_tracker, read_tracker

JANUARY = date(2026, 1, 1)


@pytest.fixture(scope="module")
def world():
    company = build_company()
    leases = build_leases(company)
    return company, leases, build_month(JANUARY, company, leases)


@pytest.fixture(scope="module")
def clean_lease(world):
    company, leases, _ = world
    return render_lease(leases[0], company)


# --- scans -----------------------------------------------------------------

def test_a_scan_loses_its_text_layer(clean_lease):
    """Which is the point: it forces the vision path."""
    assert has_text_layer(clean_lease)
    assert not has_text_layer(scan(clean_lease))


def test_a_scan_keeps_every_page(clean_lease):
    original = extract(clean_lease).page_count
    assert extract(scan(clean_lease)).page_count == original


def test_the_pipeline_reports_no_words_for_a_scan(clean_lease):
    document = extract(scan(clean_lease))
    assert all(not page.has_text_layer for page in document.pages)
    assert sum(len(p.words) for p in document.pages) == 0


@pytest.mark.parametrize("profile", [CLEAN_SCAN, OFFICE_COPIER, BAD_FAX])
def test_every_profile_produces_a_readable_pdf(clean_lease, profile):
    data = scan(clean_lease, profile)
    assert data[:4] == b"%PDF"
    assert extract(data).page_count > 0


def test_scanning_is_deterministic(clean_lease):
    assert scan(clean_lease, OFFICE_COPIER, seed=7) == scan(clean_lease, OFFICE_COPIER, seed=7)


def test_different_profiles_differ(clean_lease):
    assert scan(clean_lease, CLEAN_SCAN) != scan(clean_lease, BAD_FAX)


# --- the previous accountant's spreadsheet ---------------------------------

@pytest.fixture(scope="module")
def tracker(world):
    company, leases, _ = world
    return build_tracker(company, leases)


def test_notes_are_read_past_the_title_and_the_blank_row(tracker):
    notes = read_tracker(tracker)
    assert len(notes) >= 5
    assert all(n.clinic_id.startswith("STORE-") for n in notes)


def test_the_header_is_not_the_first_row(tracker):
    """Finding it by content rather than position is the whole trick."""
    notes = read_tracker(tracker)
    assert min(n.row for n in notes) > 2


def test_colour_is_read_as_meaning(tracker):
    notes = read_tracker(tracker)
    meanings = {n.colour_meaning for n in notes if n.colour_meaning}
    assert "disputed" in meanings
    assert "reviewed and accepted" in meanings


def test_a_note_is_always_a_claim_never_a_rule(tracker):
    """Treating a note as a rule is how a system inherits someone else's
    mistakes and then compounds them."""
    assert all(n.is_claim for n in read_tracker(tracker))


def test_the_tracker_corroborates_the_suite_118_charge(tracker):
    """An independent low-trust source pointing at the same thing E3 found."""
    note = next(n for n in read_tracker(tracker) if n.clinic_id == "STORE-02")
    assert "118" in note.note


def test_an_empty_workbook_yields_nothing():
    from io import BytesIO

    from openpyxl import Workbook

    book = Workbook()
    buffer = BytesIO()
    book.save(buffer)
    assert read_tracker(buffer.getvalue()) == []


def test_the_tracker_is_deterministic(world):
    company, leases, _ = world
    first = read_tracker(build_tracker(company, leases))
    second = read_tracker(build_tracker(company, leases))
    assert [n.note for n in first] == [n.note for n in second]


# --- landlord replies ------------------------------------------------------

@pytest.fixture(scope="module")
def replies(world):
    company, _, _ = world
    return build_replies(company)


def test_every_outcome_is_exercised(replies):
    assert {r.outcome for r in replies} == set(OUTCOMES)


def test_a_full_credit_settles_the_dispute(replies):
    reply = next(r for r in replies if r.outcome == FULL_CREDIT)
    assert reply.settles
    assert reply.granted == reply.claimed
    assert reply.outstanding == 0.0


def test_a_refusal_also_settles_it(replies):
    """Settled is not the same as in our favour."""
    reply = next(r for r in replies if r.outcome == REFUSED)
    assert reply.settles
    assert reply.granted == 0.0


def test_a_partial_credit_settles_nothing(replies):
    """A receivable for the agreed part, and a decision still to make."""
    reply = next(r for r in replies if r.outcome == PARTIAL_CREDIT)
    assert not reply.settles
    assert 0 < reply.granted < reply.claimed
    assert reply.outstanding > 0


def test_a_query_reopens_rather_than_resolves(replies):
    reply = next(r for r in replies if r.outcome == QUERIED)
    assert not reply.settles
    assert reply.granted == 0.0


def test_replies_come_from_the_authorized_representative(world, replies):
    company, _, _ = world
    for reply in replies:
        landlord = company.landlord_for(reply.clinic_id)
        assert reply.sender == landlord.authorized_rep_email


def test_a_reply_threads_to_its_dispute(replies):
    assert all(r.in_reply_to for r in replies)
    assert all("In-Reply-To" in r.to_eml() for r in replies)


def test_replies_arrive_after_the_dispute_was_sent(replies):
    assert all(r.sent > date(2026, 2, 1) for r in replies)


# --- the classifier --------------------------------------------------------

def test_a_lease_is_recognised(world, clean_lease):
    result = classify_document(extract(clean_lease))
    assert result.kind == LEASE
    assert result.decided_by == "rules"


def test_a_statement_outranks_its_own_line_items(world):
    """An invoice carrying an operating expense line is still an invoice.
    Routing it to the CAM reader produces no number at all."""
    company, _, invoices = world
    result = classify_document(extract(render_invoice(invoices[0], company)))
    assert result.kind == RENT_INVOICE


def test_a_portal_export_is_recognised_by_its_columns(world):
    company, _, invoices = world
    result = classify(portal(invoices[0], company))
    assert result.kind == RENT_INVOICE
    assert "ChargeCode" in (result.evidence or "")


def test_an_executed_amendment_outranks_everything_it_mentions(world):
    company, _, _ = world
    body = next(m for m in build_emails(company) if m.kind == "executed_amendment").body
    assert classify(body).kind == AMENDMENT


def test_a_credit_reply_is_a_credit_memo(replies):
    reply = next(r for r in replies if r.outcome == FULL_CREDIT)
    assert classify(reply.body).kind == CREDIT_MEMO


def test_a_scan_is_routed_to_vision_not_guessed_at(clean_lease):
    result = classify_document(extract(scan(clean_lease)))
    assert result.kind == SCANNED
    assert result.needs_vision
    assert result.decided_by == "no_text"


def test_an_unremarkable_email_is_not_forced_into_a_category(world):
    company, _, _ = world
    body = next(m for m in build_emails(company) if m.kind == "noise").body
    result = classify(body)
    assert result.kind == OTHER
    assert result.confidence < UNSURE


def test_an_unsure_classification_asks_for_the_model(world):
    company, _, _ = world
    body = next(m for m in build_emails(company) if m.kind == "noise").body
    assert classify(body).needs_model


def test_a_confident_classification_does_not(clean_lease):
    assert not classify_document(extract(clean_lease)).needs_model


def test_every_rule_names_the_phrase_that_decided_it(world, clean_lease):
    result = classify_document(extract(clean_lease))
    assert result.evidence
    assert "matched" in result.evidence


def test_empty_text_is_treated_as_a_scan():
    assert classify("", has_text_layer=True).kind == SCANNED


def test_every_kind_the_model_may_return_is_known():
    assert LEASE in KINDS and SCANNED not in KINDS
