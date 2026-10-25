"""The generated billing month, and what a checker has to be able to see in it.

The second half of this file is a specification rather than a regression test:
it pins the three *kinds* of wrongness January contains, because a checker that
only compares amounts catches barely half of them. Stage 3's
`agents/checker.py` has to satisfy all three.
"""

import csv
import hashlib
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datagen.company import build_company
from datagen.errors import JANUARY_2026, real_errors
from datagen.leases import build_leases
from datagen.month import (
    build_month, build_payments, expected_charges, write_ap_export, write_bank_export,
)
from datagen.render_invoice import render_invoice

PERIOD = date(2026, 1, 1)


@pytest.fixture(scope="module")
def world():
    company = build_company()
    leases = build_leases(company)
    invoices = build_month(PERIOD, company, leases)
    return company, leases, invoices, build_payments(invoices, company)


# --- shape -----------------------------------------------------------------

def test_one_invoice_per_lease_plus_the_duplicate(world):
    _, leases, invoices, _ = world
    assert len(invoices) == len(leases) + 1


def test_every_invoice_has_at_least_one_charge(world):
    _, _, invoices, _ = world
    assert all(invoice.charges for invoice in invoices)


def test_invoice_total_is_the_sum_of_its_charges(world):
    _, _, invoices, _ = world
    for invoice in invoices:
        assert invoice.total() == round(sum(c.amount for c in invoice.charges), 2)


def test_one_bank_line_per_charge(world):
    _, _, invoices, payments = world
    assert len(payments) == sum(len(i.charges) for i in invoices)


def test_ap_pays_exactly_what_was_billed(world):
    """The premise of the whole system: nobody compared the invoice to the lease."""
    _, _, invoices, payments = world
    assert round(sum(p.amount for p in payments), 2) == round(
        sum(i.total() for i in invoices), 2
    )


def test_invoice_ids_are_unique(world):
    _, _, invoices, _ = world
    ids = [i.invoice_id for i in invoices]
    assert len(ids) == len(set(ids))


def test_payments_land_on_or_after_the_due_date(world):
    _, _, invoices, payments = world
    due = {i.invoice_id: i.due_date for i in invoices}
    assert all(p.paid_on >= due[p.invoice_id] for p in payments)


# --- the planted errors ----------------------------------------------------

def test_total_variance_matches_the_error_catalog(world):
    company, leases, invoices, _ = world
    expected = expected_charges(PERIOD, company, leases)
    variance = 0.0
    for invoice in invoices:
        for charge in invoice.charges:
            if charge.error_id in ("E2", "E3"):
                variance += charge.amount          # wholly unsupported lines
            else:
                variance += charge.amount - expected[charge.clinic_id].get(
                    charge.charge_type, 0.0)
    assert round(variance, 2) == round(sum(e.variance for e in real_errors()), 2)
    assert round(variance, 2) == 25_736.36


def test_every_planted_error_reaches_the_invoices(world):
    _, _, invoices, _ = world
    tagged = {c.error_id for i in invoices for c in i.charges if c.error_id}
    # E6 is correct, so it is not tagged on a charge — it is the absence of one.
    assert tagged == {"E1", "E2", "E3", "E4", "E5"}


def test_the_correct_but_odd_charge_is_exactly_what_the_lease_says(world):
    """STORE-04's rent rose $400 on 1 January. A checker that holds this is wrong."""
    company, leases, invoices, _ = world
    expected = expected_charges(PERIOD, company, leases)
    charge = next(
        c for i in invoices for c in i.charges
        if c.clinic_id == "STORE-04" and c.charge_type == "base_rent"
    )
    assert charge.amount == expected["STORE-04"]["base_rent"] == 13_680.00
    assert charge.error_id is None


def test_clinics_with_no_planted_error_are_billed_correctly(world):
    company, leases, invoices, _ = world
    expected = expected_charges(PERIOD, company, leases)
    for invoice in invoices:
        for charge in invoice.charges:
            if charge.error_id is None:
                assert charge.amount == expected[charge.clinic_id][charge.charge_type], \
                    "%s %s" % (charge.clinic_id, charge.charge_type)


# --- what the checker must be able to see ----------------------------------
#
# Three different questions. An amount comparison answers only the first.

def test_kind_1_an_amount_that_disagrees_with_the_lease(world):
    """E4 and E5: one rent line, wrong number. Visible by comparing amounts."""
    company, leases, invoices, _ = world
    expected = expected_charges(PERIOD, company, leases)
    wrong = [
        c for i in invoices for c in i.charges
        if c.error_id in ("E4", "E5")
    ]
    assert len(wrong) == 2
    for charge in wrong:
        assert charge.amount != expected[charge.clinic_id][charge.charge_type]


def test_kind_2_a_duplicate_is_a_counting_question_not_an_amount_one(world):
    """E2: January rent billed twice, both times for the *correct* amount.

    Comparing each payment to the schedule finds nothing — both match. Only
    counting rent charges per lease and period finds it.
    """
    company, leases, invoices, _ = world
    expected = expected_charges(PERIOD, company, leases)
    rent_charges = [
        c for i in invoices for c in i.charges
        if c.clinic_id == "STORE-01" and c.charge_type == "base_rent"
    ]
    assert len(rent_charges) == 2
    for charge in rent_charges:
        assert charge.amount == expected["STORE-01"]["base_rent"], \
            "both duplicates carry the correct amount, which is what hides them"

    counts = Counter(
        (c.lease_id, c.period) for i in invoices for c in i.charges
        if c.charge_type == "base_rent"
    )
    assert counts[("LEASE-01", PERIOD)] == 2


def test_kind_3_a_charge_for_premises_the_lease_does_not_cover(world):
    """E3: the amount is irrelevant — the suite is not the leased premises."""
    company, _, invoices, _ = world
    stray = next(
        c for i in invoices for c in i.charges if c.error_id == "E3"
    )
    assert stray.suite == "Suite 118"
    assert stray.suite != company.clinic(stray.clinic_id).suite
    assert company.clinic("STORE-02").suite == "Suite 115"


def test_cam_errors_are_invisible_to_a_rent_only_check(world):
    """E1 is an operating expense line. A rent schedule says nothing about it."""
    _, _, invoices, _ = world
    cam = next(c for i in invoices for c in i.charges if c.error_id == "E1")
    assert cam.charge_type == "cam_estimate"


# --- exports ---------------------------------------------------------------

def test_bank_export_is_readable_by_the_existing_engine(world, tmp_path):
    from leasedesk.reconcile import load_payments

    _, _, _, payments = world
    path = tmp_path / "bank.csv"
    write_bank_export(payments, path)
    loaded = load_payments(str(path))
    assert len(loaded) == len(payments)
    assert loaded[0].lease_id.startswith("LEASE-")


def test_bank_export_carries_the_charge_type_for_filtering(world, tmp_path):
    _, _, _, payments = world
    path = tmp_path / "bank.csv"
    write_bank_export(payments, path)
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    assert {r["charge_type"] for r in rows} == {"base_rent", "cam_estimate"}


def test_ap_export_has_one_row_per_charge(world, tmp_path):
    _, _, invoices, _ = world
    path = tmp_path / "ap.csv"
    write_ap_export(invoices, path)
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == sum(len(i.charges) for i in invoices)


# --- reproducibility -------------------------------------------------------

def test_month_generation_is_deterministic():
    assert build_month(PERIOD) == build_month(PERIOD)


def test_invoice_pdf_is_byte_reproducible(world):
    company, _, invoices, _ = world
    first = hashlib.sha256(render_invoice(invoices[0], company)).hexdigest()
    second = hashlib.sha256(render_invoice(invoices[0], company)).hexdigest()
    assert first == second


def test_invoice_pdf_states_the_billed_amount(world):
    from app.docs.pipeline import extract

    company, _, invoices, _ = world
    invoice = next(i for i in invoices if i.clinic_id == "STORE-03")
    doc = extract(render_invoice(invoice, company))
    assert doc.find("17,270.11"), "the wrong rent must be quotable on the invoice"
    assert doc.find(invoice.invoice_id)


# --- the catalog is for eval only ------------------------------------------

def test_only_eval_imports_the_error_catalog():
    """The benchmark is worthless if the system under test can read the answers."""
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for path in list(root.glob("backend/app/**/*.py")) + list(root.glob("leasedesk/**/*.py")):
        if "errors" in path.read_text() and "datagen.errors" in path.read_text():
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], "datagen.errors imported outside eval: %s" % offenders


def test_charge_ids_are_unique_within_a_month(world):
    """One invoice can carry two charges of the same type — the real rent and a
    line for premises we do not lease. An id that collides makes them one
    charge to anything keyed by it."""
    _, _, invoices, _ = world
    ids = [c.charge_id for i in invoices for c in i.charges]
    assert len(ids) == len(set(ids))


def test_the_stray_suite_line_has_its_own_id(world):
    _, _, invoices, _ = world
    clinic_02 = [c for i in invoices for c in i.charges if c.clinic_id == "STORE-02"]
    rent = [c for c in clinic_02 if c.charge_type == "base_rent"]
    assert len(rent) == 2
    assert rent[0].charge_id != rent[1].charge_id
