"""Northbay Physical Therapy — the fictional company, generated from a seed.

Phase 1 scope: one legal entity in California, one region, 5 clinics, 2
landlords, 2 centers. Everything is deterministic from `SEED`, so the same
company, the same leases and the same answer key come out of every run. The
eval depends on that.

Two deliberate shapes here, both set up for later phases:

  - **Serramonte Medical Plaza holds two Northbay clinics.** That is what makes
    the Phase 2 shared-pool double billing case possible: one vendor line can
    be billed in full to both suites.
  - **Every lease names an authorized representative in its notices clause.**
    The source trust ranking turns on whether an email came from that named
    person or from property management without stated authority.
"""

from dataclasses import dataclass, field
from typing import List, Optional

SEED = 20261023
COMPANY_NAME = "Northbay Physical Therapy"


@dataclass(frozen=True)
class Person:
    person_id: str
    name: str
    role: str
    email: str


@dataclass(frozen=True)
class Entity:
    entity_id: str
    name: str
    state: str


@dataclass(frozen=True)
class Region:
    region_id: str
    name: str
    manager_id: str


@dataclass(frozen=True)
class Landlord:
    landlord_id: str
    name: str
    notice_address: str
    authorized_rep: str
    authorized_rep_email: str
    # Property management, deliberately NOT the authorized representative.
    # Email from here ranks below a written confirmation from the rep.
    property_manager: str
    property_manager_email: str


@dataclass(frozen=True)
class Center:
    center_id: str
    name: str
    address: str
    landlord_id: str
    total_rsf: int


@dataclass(frozen=True)
class Clinic:
    clinic_id: str
    name: str
    entity_id: str
    region_id: str
    center_id: str
    suite: str
    rsf: int
    service_line: str

    @property
    def pro_rata(self) -> float:
        """Filled in by `Company.pro_rata_for`, which needs the center."""
        raise NotImplementedError


@dataclass
class Company:
    entity: Entity
    region: Region
    people: List[Person]
    landlords: List[Landlord]
    centers: List[Center]
    clinics: List[Clinic]
    seed: int = SEED

    def landlord(self, landlord_id: str) -> Landlord:
        return _one(self.landlords, "landlord_id", landlord_id)

    def center(self, center_id: str) -> Center:
        return _one(self.centers, "center_id", center_id)

    def clinic(self, clinic_id: str) -> Clinic:
        return _one(self.clinics, "clinic_id", clinic_id)

    def person(self, role: str) -> Person:
        for p in self.people:
            if p.role == role:
                return p
        raise KeyError(role)

    def clinics_in(self, center_id: str) -> List[Clinic]:
        return [c for c in self.clinics if c.center_id == center_id]

    def landlord_for(self, clinic_id: str) -> Landlord:
        return self.landlord(self.center(self.clinic(clinic_id).center_id).landlord_id)

    def pro_rata_for(self, clinic_id: str) -> float:
        """The clinic's share of its center, as a fraction of total RSF."""
        clinic = self.clinic(clinic_id)
        center = self.center(clinic.center_id)
        return round(clinic.rsf / center.total_rsf, 6)


def build_company(seed: int = SEED) -> Company:
    entity = Entity("ENT-CA", "Northbay Physical Therapy of California, Inc.", "CA")
    region = Region("REG-BAY", "Bay Area", "PER-RM-BAY")

    people = [
        Person("PER-RM-BAY", "Dana Whitfield", "regional_manager", "dana.whitfield@northbaypt.example"),
        Person("PER-AP", "Marcus Oyelaran", "ap_clerk", "marcus.oyelaran@northbaypt.example"),
        Person("PER-CTRL", "Priya Raghunathan", "controller", "priya.raghunathan@northbaypt.example"),
        Person("PER-AUD", "External Auditor", "auditor", "audit@brennan-cpa.example"),
    ]

    landlords = [
        Landlord(
            landlord_id="LL-SERRA",
            name="Serramonte Retail Partners LLC",
            notice_address="1500 Serramonte Blvd, Suite 400, Daly City, CA 94015",
            authorized_rep="Dana Reyes",
            authorized_rep_email="dana.reyes@serramonteretail.example",
            property_manager="Kevin Tran",
            property_manager_email="ktran@crestpointpm.example",
        ),
        Landlord(
            landlord_id="LL-PACIFIC",
            name="Pacific Crest Properties LLC",
            notice_address="88 Baldwin Ave, San Mateo, CA 94401",
            authorized_rep="Alicia Moreno",
            authorized_rep_email="amoreno@pacificcrestprop.example",
            property_manager="Sandra Villalobos",
            property_manager_email="svillalobos@baysidemgmt.example",
        ),
    ]

    centers = [
        # Two Northbay suites here — the Phase 2 double-billing setup.
        Center("CTR-SERRA", "Serramonte Medical Plaza",
               "2001 Junipero Serra Blvd, Daly City, CA 94014", "LL-SERRA", 64_000),
        Center("CTR-BAYVIEW", "Bayview Commons",
               "410 E Hillsdale Blvd, San Mateo, CA 94403", "LL-PACIFIC", 48_500),
    ]

    clinics = [
        Clinic("CLINIC-01", "Northbay PT — Daly City", "ENT-CA", "REG-BAY",
               "CTR-SERRA", "Suite 210", 6_200, "outpatient"),
        Clinic("CLINIC-02", "Northbay PT — Serramonte Hand Therapy", "ENT-CA", "REG-BAY",
               "CTR-SERRA", "Suite 115", 3_100, "hand therapy"),
        Clinic("CLINIC-03", "Northbay PT — San Mateo", "ENT-CA", "REG-BAY",
               "CTR-BAYVIEW", "Suite 100", 5_400, "outpatient"),
        Clinic("CLINIC-04", "Northbay PT — Bayview Sports Medicine", "ENT-CA", "REG-BAY",
               "CTR-BAYVIEW", "Suite 240", 4_150, "sports medicine"),
        Clinic("CLINIC-05", "Northbay PT — Bayview Aquatic", "ENT-CA", "REG-BAY",
               "CTR-BAYVIEW", "Suite 305", 2_800, "aquatic therapy"),
    ]

    return Company(entity, region, people, landlords, centers, clinics, seed)


def _one(items, attr, value):
    for item in items:
        if getattr(item, attr) == value:
            return item
    raise KeyError("%s=%r" % (attr, value))
