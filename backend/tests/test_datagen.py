import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datagen.company import build_company
from datagen.leases import build_leases


def test_company_shape():
    c = build_company()
    assert len(c.clinics) == 5
    assert len(c.landlords) == 2
    assert len(c.centers) == 2


def test_one_center_holds_two_clinics_for_the_double_bill_case():
    c = build_company()
    sizes = sorted(len(c.clinics_in(ctr.center_id)) for ctr in c.centers)
    assert sizes == [2, 3]


def test_generation_is_deterministic():
    assert build_company() == build_company()
    assert build_leases() == build_leases()


def test_pro_rata_is_the_share_of_the_center():
    c = build_company()
    total = sum(c.pro_rata_for(cl.clinic_id) for cl in c.clinics_in("CTR-SERRA"))
    assert 0 < total < 1  # Northbay does not occupy the whole plaza


def test_authorized_rep_differs_from_property_manager():
    """The trust ranking depends on telling these two apart."""
    for landlord in build_company().landlords:
        assert landlord.authorized_rep != landlord.property_manager
        assert landlord.authorized_rep_email != landlord.property_manager_email


def test_every_clinic_has_exactly_one_lease():
    leases = build_leases()
    assert sorted(l.clinic_id for l in leases) == [
        "STORE-0%d" % i for i in range(1, 6)
    ]


def test_clinic_01_reproduces_the_rehearsed_store_14_numbers():
    lease = build_leases()[0]
    assert lease.commencement == date(2024, 1, 1)
    assert lease.expiration == date(2028, 12, 31)
    assert lease.discount_rate == 0.0720
    assert [s.monthly_rent for s in lease.rent_schedule()] == [
        18500.00, 19055.00, 19626.65, 20215.45, 20821.91
    ]


def test_rent_schedule_is_continuous_and_ends_at_expiration():
    for lease in build_leases():
        steps = lease.rent_schedule()
        assert steps[0].start == lease.commencement
        assert steps[-1].end == lease.expiration
        for earlier, later in zip(steps, steps[1:]):
            assert (later.start - earlier.end).days == 1, lease.lease_id


def test_fixed_step_escalation_adds_a_flat_amount():
    lease = next(l for l in build_leases() if l.escalation.kind == "fixed_step")
    rents = [s.monthly_rent for s in lease.rent_schedule()]
    deltas = {round(b - a, 2) for a, b in zip(rents, rents[1:])}
    assert deltas == {lease.escalation.amount}


def test_percent_escalation_compounds_annually():
    lease = build_leases()[0]
    rents = [s.monthly_rent for s in lease.rent_schedule()]
    assert rents[1] == round(rents[0] * 1.03, 2)
    assert rents[2] == round(rents[1] * 1.03, 2)


def test_engine_json_loads_in_the_existing_engine():
    import json, tempfile
    from leasedesk.models import load_lease

    company = build_company()
    terms = build_leases(company)[0]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(terms.to_engine_json(company), fh)
        path = fh.name

    lease = load_lease(path)
    assert lease.lease_id == "LEASE-01"
    assert lease.rent_for(date(2026, 3, 1)) == 19626.65


def test_generated_lease_builds_a_schedule_that_amortizes_to_zero():
    import json, tempfile
    from leasedesk.models import load_lease
    from leasedesk.schedule import build

    company = build_company()
    for terms in build_leases(company):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(terms.to_engine_json(company), fh)
            path = fh.name
        schedule = build(load_lease(path))
        assert abs(schedule.periods[-1].liability_close) < 0.01, terms.lease_id
        assert abs(schedule.periods[-1].rou_close) < 0.01, terms.lease_id


def test_rendered_pdf_is_byte_reproducible():
    """The store is content-addressed and the answer key cites documents by
    sha256, so the same lease must hash the same on every run. ReportLab
    stamps a creation time unless `invariant` is set."""
    import hashlib

    from datagen.render_lease import render_lease

    company = build_company()
    terms = build_leases(company)[0]
    first = hashlib.sha256(render_lease(terms, company)).hexdigest()
    second = hashlib.sha256(render_lease(terms, company)).hexdigest()
    assert first == second


def test_different_leases_render_differently():
    import hashlib

    from datagen.render_lease import render_lease

    company = build_company()
    digests = {
        hashlib.sha256(render_lease(t, company)).hexdigest()
        for t in build_leases(company)
    }
    assert len(digests) == 5


# --- what the landlord bills, versus what the books expect -----------------

def test_the_landlord_bills_the_amendment_the_books_have_not_seen():
    """The variance the product exists to catch has to be in the generated
    month, not only in the tests: from the amendment's effective date the
    invoice is for the new rent while the books still run the old schedule."""
    from datetime import date

    from datagen.build import billed_as
    from datagen.company import build_company
    from datagen.leases import SECOND_AMENDMENT, build_leases

    company = build_company()
    books = {t.lease_id: t for t in build_leases(company)}

    before = {t.lease_id: t for t in billed_as(company, date(2026, 1, 1))}
    assert before["LEASE-01"].base_rent_monthly == books["LEASE-01"].base_rent_monthly
    assert before["LEASE-01"].expiration == books["LEASE-01"].expiration

    after = {t.lease_id: t for t in billed_as(company, SECOND_AMENDMENT.effective)}
    assert after["LEASE-01"].expiration == SECOND_AMENDMENT.new_expiration
    assert after["LEASE-01"].expiration != books["LEASE-01"].expiration
    # Every other lease is untouched: one amendment, one lease.
    for lease_id in books:
        if lease_id != "LEASE-01":
            assert after[lease_id].expiration == books[lease_id].expiration


def test_a_month_before_the_amendment_generates_as_it_always_did():
    """January must stay byte-identical, or every stored sha and the whole
    answer key move under us."""
    from datetime import date

    from datagen.build import billed_as
    from datagen.company import build_company
    from datagen.leases import build_leases

    company = build_company()
    assert [t.to_dict() if hasattr(t, "to_dict") else t
            for t in billed_as(company, date(2026, 1, 1))] == \
           [t.to_dict() if hasattr(t, "to_dict") else t
            for t in build_leases(company)]
