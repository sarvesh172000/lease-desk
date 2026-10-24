"""A second company the system has never seen.

A generator and the thing it tests drift toward each other. Terms get worded
the way the extractor already parses them; errors get planted in the shapes the
checker already catches. Scores climb and nothing improves. The honest answer
to "did you overfit your own data" is a company built from a different seed,
with different landlords, different cities, different lease language and
different suite numbering — scored once, at the end, and reported next to the
development score.

**Only `eval/` may build this.** A test enforces it. If development code can
reach the held-out company, it stops being held out the first time someone
debugs against it.

    from datagen.heldout import build_heldout
    company, leases = build_heldout()
"""

from dataclasses import replace
from datetime import date, timedelta
from typing import List, Optional, Tuple

from .company import (
    FULL, Center, Clinic, Company, Entity, Landlord, Person, Region,
)
from .leases import Escalation, LeaseTerms, RenewalOption

HELDOUT_SEED = 71104329
COMPANY_NAME = "Stonebridge Rehabilitation Partners"

_ENTITIES = [
    ("ENT-OR", "Stonebridge Rehabilitation of Oregon, Inc.", "OR"),
    ("ENT-WA", "Stonebridge Rehabilitation of Washington, LLC", "WA"),
]

_REGIONS = [
    ("REG-WILLAMETTE", "Willamette", "PER-RM-WIL"),
    ("REG-PUGET", "Puget Sound", "PER-RM-PUG"),
]

_PEOPLE = [
    ("PER-RM-WIL", "Astrid Halvorsen", "regional_manager", "astrid.halvorsen@stonebridgerehab.example"),
    ("PER-RM-PUG", "Desmond Achebe", "regional_manager", "desmond.achebe@stonebridgerehab.example"),
    ("PER-AP", "Lucia Ferraro", "ap_clerk", "lucia.ferraro@stonebridgerehab.example"),
    ("PER-CTRL", "Wendell Burkhart", "controller", "wendell.burkhart@stonebridgerehab.example"),
    ("PER-AUD", "External Auditor", "auditor", "audit@halloran-llp.example"),
]

# No name here appears in the development company.
_LANDLORDS = [
    ("LL-WILLAMETTE", "Willamette Crossing Investors LLC",
     "1120 SW 5th Ave, Suite 400, Portland, OR 97204",
     "Ingrid Sorensen", "isorensen@willamettecrossing.example",
     "Marcus Delacroix", "mdelacroix@cascadepm.example"),
    ("LL-CASCADIA", "Cascadia Medical Realty Trust",
     "701 Pike St, Suite 1500, Seattle, WA 98101",
     "Jonah Kirkpatrick", "jkirkpatrick@cascadiamedical.example",
     "Renata Oyelowo", "royelowo@emeraldpm.example"),
    ("LL-TUALATIN", "Tualatin Valley Holdings LP",
     "9200 SW Nimbus Ave, Beaverton, OR 97008",
     "Beatriz Alencar", "balencar@tualatinvalley.example",
     "Finn Gallagher", "fgallagher@tvpropertymgmt.example"),
    ("LL-OLYMPIC", "Olympic Gateway Properties LLC",
     "3300 Pacific Ave, Tacoma, WA 98418",
     "Sanjay Raghav", "sraghav@olympicgateway.example",
     "Clara Wojcik", "cwojcik@gatewaypm.example"),
    ("LL-ROSEQUARTER", "Rose Quarter Commercial LLC",
     "1 N Center Court St, Portland, OR 97227",
     "Thandiwe Mabaso", "tmabaso@rosequartercre.example",
     "Victor Lindgren", "vlindgren@rqmanagement.example"),
]

# center_id, name, address, landlord, total rsf, clinics
_CENTERS = [
    ("CTR-WILLAMETTE", "Willamette Crossing", "1140 SW 5th Ave, Portland, OR 97204",
     "LL-WILLAMETTE", 62_400, 4),
    ("CTR-PIKE", "Pike Street Health Center", "715 Pike St, Seattle, WA 98101",
     "LL-CASCADIA", 55_800, 4),
    ("CTR-NIMBUS", "Nimbus Business Park", "9240 SW Nimbus Ave, Beaverton, OR 97008",
     "LL-TUALATIN", 41_200, 3),
    ("CTR-GATEWAY", "Olympic Gateway Plaza", "3340 Pacific Ave, Tacoma, WA 98418",
     "LL-OLYMPIC", 36_700, 3),
    ("CTR-ROSE", "Rose Quarter Medical Commons", "25 N Center Court St, Portland, OR 97227",
     "LL-ROSEQUARTER", 47_900, 4),
]

_REGION_FOR = {
    "CTR-WILLAMETTE": ("REG-WILLAMETTE", "ENT-OR"),
    "CTR-NIMBUS": ("REG-WILLAMETTE", "ENT-OR"),
    "CTR-ROSE": ("REG-WILLAMETTE", "ENT-OR"),
    "CTR-PIKE": ("REG-PUGET", "ENT-WA"),
    "CTR-GATEWAY": ("REG-PUGET", "ENT-WA"),
}

_CITY_FOR = {
    "CTR-WILLAMETTE": "Portland", "CTR-PIKE": "Seattle", "CTR-NIMBUS": "Beaverton",
    "CTR-GATEWAY": "Tacoma", "CTR-ROSE": "Rose Quarter",
}

_SERVICE_LINES = ("outpatient", "neurological rehabilitation", "orthopedic therapy",
                  "occupational therapy", "pelvic health")

# Deliberately different from the development company: different sizes,
# different rent per square foot, different escalation shapes, different terms.
_RSF_CYCLE = (4_280, 6_750, 3_120, 5_540, 2_680, 7_100, 4_900)
_PSF_CYCLE = (32.80, 38.40, 27.60, 43.10, 30.20, 35.90, 25.40)
_TERM_YEARS = (6, 4, 8, 5, 3, 7, 5)
_STARTS = ((2023, 4), (2024, 8), (2022, 11), (2025, 2), (2024, 6), (2023, 9), (2025, 5))
_ESCALATIONS = (
    ("fixed_percent", 0.0325), ("fixed_step", 390.00), ("fixed_percent", 0.0280),
    ("fixed_step", 215.00), ("fixed_percent", 0.0400), ("fixed_percent", 0.0225),
    ("fixed_step", 500.00),
)
_CAM_PSF = (11.80, 9.20, 13.60, 10.10, 12.40, 8.50, 14.00)
_RENEWALS = (RenewalOption(2, 5, 300), RenewalOption(1, 3, 150),
             RenewalOption(1, 10, 365), RenewalOption(0, 0, 0))
_IBR = {3: 0.0690, 4: 0.0715, 5: 0.0740, 6: 0.0765, 7: 0.0790, 8: 0.0810}


def build_heldout() -> Tuple[Company, List[LeaseTerms]]:
    """The held-out company and its leases. Scored once, at the end."""
    entities = [Entity(*e) for e in _ENTITIES]
    regions = [Region(*r) for r in _REGIONS]
    people = [Person(*p) for p in _PEOPLE]
    landlords = [Landlord(*l) for l in _LANDLORDS]

    centers: List[Center] = []
    clinics: List[Clinic] = []
    index = 0

    for center_id, name, address, landlord_id, total_rsf, count in _CENTERS:
        centers.append(Center(center_id, name, address, landlord_id, total_rsf,
                              shared_pool=count > 1))
        region_id, entity_id = _REGION_FOR[center_id]
        for n in range(count):
            index += 1
            slot = index % len(_RSF_CYCLE)
            clinics.append(Clinic(
                clinic_id="HO-CLINIC-%02d" % index,
                name="Stonebridge — %s %s" % (
                    _CITY_FOR[center_id], _SERVICE_LINES[index % len(_SERVICE_LINES)].title()),
                entity_id=entity_id,
                region_id=region_id,
                center_id=center_id,
                suite="Unit %s" % chr(ord("A") + n) + str(200 + index),
                rsf=_RSF_CYCLE[slot],
                service_line=_SERVICE_LINES[index % len(_SERVICE_LINES)],
            ))

    company = Company(
        entity=entities[0], region=regions[0], people=people, landlords=landlords,
        centers=centers, clinics=clinics, seed=HELDOUT_SEED,
        entities=entities, regions=regions, scope=FULL,
    )
    return company, _leases(company)


def _leases(company: Company) -> List[LeaseTerms]:
    out: List[LeaseTerms] = []
    for clinic in company.clinics:
        number = int(clinic.clinic_id.split("-")[-1])
        slot = number % len(_PSF_CYCLE)

        year, month = _STARTS[slot]
        start = date(year, month, 1)
        years = _TERM_YEARS[slot]
        end = _add_months(start, years * 12) - timedelta(days=1)
        monthly = round(clinic.rsf * _PSF_CYCLE[slot] / 12, 2)
        kind, amount = _ESCALATIONS[slot]

        out.append(LeaseTerms(
            lease_id="HO-LEASE-%02d" % number,
            clinic_id=clinic.clinic_id,
            landlord_id=company.center(clinic.center_id).landlord_id,
            commencement=start,
            expiration=end,
            rsf=clinic.rsf,
            base_rent_monthly=monthly,
            escalation=Escalation(kind, amount, start.month),
            cam_estimate_psf_annual=_CAM_PSF[slot],
            security_deposit=round(monthly * 2, 2),
            renewal=_RENEWALS[number % len(_RENEWALS)],
            discount_rate=_IBR.get(years, 0.0740),
        ))
    return out


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    last = 31 if month == 12 else (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))
