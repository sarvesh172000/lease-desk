"""The company at full scale, and the held-out company (chunk B2).

The test that matters most is the first one: scaling up must not move a single
number the demo was rehearsed on.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datagen.company import FULL, PHASE1, build_company
from datagen.heldout import HELDOUT_SEED, build_heldout
from datagen.leases import build_leases

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def worlds():
    small = build_company(PHASE1)
    big = build_company(FULL)
    return small, big, build_leases(small), build_leases(big)


# --- the scale-up must not disturb what works ------------------------------

def test_the_phase1_clinics_are_unchanged_inside_the_full_company(worlds):
    small, big, _, _ = worlds
    assert big.clinics[:5] == small.clinics


def test_the_phase1_leases_are_unchanged(worlds):
    _, _, small_leases, big_leases = worlds
    assert big_leases[:5] == small_leases


def test_the_rehearsed_rent_schedule_survives(worlds):
    """$443,255.70 depends on these five numbers."""
    _, _, _, big_leases = worlds
    lease = next(t for t in big_leases if t.lease_id == "LEASE-01")
    assert [s.monthly_rent for s in lease.rent_schedule()] == [
        18500.00, 19055.00, 19626.65, 20215.45, 20821.91
    ]


def test_the_phase1_landlords_are_unchanged(worlds):
    small, big, _, _ = worlds
    assert big.landlords[:2] == small.landlords


def test_the_default_scope_is_still_phase1():
    assert build_company().scope == PHASE1
    assert len(build_company().clinics) == 5


# --- the shape Jenil's Phase 2 group 2 asks for ----------------------------

def test_three_entities_one_per_state(worlds):
    _, big, _, _ = worlds
    assert len(big.entities) == 3
    assert {e.state for e in big.entities} == {"CA", "NV", "AZ"}


def test_three_regions(worlds):
    _, big, _, _ = worlds
    assert {r.name for r in big.regions} == {"Bay Area", "Southern California", "Desert"}


def test_thirty_clinics_ten_landlords_eight_centers(worlds):
    _, big, _, _ = worlds
    assert len(big.clinics) == 30
    assert len(big.landlords) == 10
    assert len(big.centers) == 8


def test_regions_do_not_map_onto_entities(worlds):
    """Bay Area and Southern California are both the California entity, while
    Desert spans Nevada and Arizona. Permission checks need both scopes."""
    _, big, _, _ = worlds
    socal_entities = {c.entity_id for c in big.clinics_in_region("REG-SOCAL")}
    desert_entities = {c.entity_id for c in big.clinics_in_region("REG-DESERT")}
    assert socal_entities == {"ENT-CA"}
    assert len(desert_entities) > 1


def test_every_clinic_belongs_to_an_entity_and_a_region(worlds):
    _, big, _, _ = worlds
    entity_ids = {e.entity_id for e in big.entities}
    region_ids = {r.region_id for r in big.regions}
    for clinic in big.clinics:
        assert clinic.entity_id in entity_ids
        assert clinic.region_id in region_ids


def test_every_entity_has_clinics(worlds):
    _, big, _, _ = worlds
    for entity in big.entities:
        assert big.clinics_in_entity(entity.entity_id), entity.entity_id


def test_centers_hold_more_than_one_clinic(worlds):
    """Shared pools are what make the CAM double-billing case possible."""
    _, big, _, _ = worlds
    assert len(big.shared_pool_centers()) >= 3


def test_two_landlords_sold_their_buildings(worlds):
    """The premises then carries one name in the lease and another on the
    invoice, which is what makes name resolution a real problem."""
    _, big, _, _ = worlds
    sold = [l for l in big.landlords if l.succeeded_by]
    assert len(sold) == 2
    for landlord in sold:
        assert big.landlord(landlord.succeeded_by) is not None


def test_pro_rata_never_exceeds_the_center(worlds):
    _, big, _, _ = worlds
    for center in big.centers:
        total = sum(big.pro_rata_for(c.clinic_id) for c in big.clinics_in(center.center_id))
        assert 0 < total <= 1.0, center.center_id


# --- leases at scale -------------------------------------------------------

def test_every_clinic_has_exactly_one_lease(worlds):
    _, big, _, big_leases = worlds
    assert sorted(t.clinic_id for t in big_leases) == sorted(c.clinic_id for c in big.clinics)


def test_lease_ids_are_unique(worlds):
    _, _, _, big_leases = worlds
    ids = [t.lease_id for t in big_leases]
    assert len(ids) == len(set(ids))


def test_leases_vary_so_extraction_cannot_pattern_match(worlds):
    _, _, _, big_leases = worlds
    assert len({t.escalation.kind for t in big_leases}) == 2
    assert len({t.term_years for t in big_leases}) >= 4
    assert len({t.base_rent_monthly for t in big_leases}) > 20


def test_every_schedule_is_continuous_and_ends_at_expiration(worlds):
    _, _, _, big_leases = worlds
    for lease in big_leases:
        steps = lease.rent_schedule()
        assert steps[0].start == lease.commencement
        assert steps[-1].end == lease.expiration
        for a, b in zip(steps, steps[1:]):
            assert (b.start - a.end).days == 1, lease.lease_id


def test_generation_is_deterministic(worlds):
    assert build_company(FULL) == build_company(FULL)
    assert build_leases(build_company(FULL)) == build_leases(build_company(FULL))


def test_an_unknown_scope_is_an_error():
    with pytest.raises(ValueError, match="scope must be"):
        build_company("enormous")


# --- the held-out company --------------------------------------------------

def test_held_out_shares_nothing_with_the_development_company(worlds):
    _, big, _, big_leases = worlds
    ho, ho_leases = build_heldout()

    assert {l.name for l in ho.landlords} & {l.name for l in big.landlords} == set()
    assert {c.clinic_id for c in ho.clinics} & {c.clinic_id for c in big.clinics} == set()
    assert {t.lease_id for t in ho_leases} & {t.lease_id for t in big_leases} == set()
    assert {c.center_id for c in ho.centers} & {c.center_id for c in big.centers} == set()


def test_held_out_uses_a_different_seed():
    ho, _ = build_heldout()
    assert ho.seed == HELDOUT_SEED
    assert ho.seed != build_company(FULL).seed


def test_held_out_lease_terms_differ_in_shape(worlds):
    """Not just different numbers — different sizes, rents and term lengths, so
    an extractor tuned to the development company has nothing to lean on."""
    _, _, _, big_leases = worlds
    _, ho_leases = build_heldout()
    assert {t.rsf for t in ho_leases} & {t.rsf for t in big_leases} == set()
    assert {t.cam_estimate_psf_annual for t in ho_leases} & \
           {t.cam_estimate_psf_annual for t in big_leases} == set()


def test_held_out_suites_are_numbered_differently():
    ho, _ = build_heldout()
    assert all(c.suite.startswith("Unit ") for c in ho.clinics)


def test_every_held_out_schedule_amortizes_to_zero():
    from leasedesk.models import load_lease
    from leasedesk.schedule import build

    ho, ho_leases = build_heldout()
    for terms in ho_leases:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(terms.to_engine_json(ho), fh)
            path = fh.name
        schedule = build(load_lease(path))
        assert abs(schedule.periods[-1].liability_close) < 0.01, terms.lease_id
        assert abs(schedule.periods[-1].rou_close) < 0.01, terms.lease_id


def test_held_out_is_deterministic():
    assert build_heldout()[0] == build_heldout()[0]
    assert build_heldout()[1] == build_heldout()[1]


def test_nothing_outside_eval_may_build_the_held_out_company():
    """If development code can reach it, it stops being held out the first time
    someone debugs against it."""
    offenders = []
    for path in list((ROOT / "backend" / "app").rglob("*.py")) + \
                list((ROOT / "leasedesk").rglob("*.py")) + \
                [p for p in (ROOT / "datagen").rglob("*.py") if p.name != "heldout.py"]:
        if "heldout" in path.read_text():
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], "held-out company reachable from: %s" % offenders
