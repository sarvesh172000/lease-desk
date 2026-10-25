"""Northbay Coffee — the fictional coffee chain, generated from a seed.

Phase 1 scope: one legal entity in California, one region, 5 stores, 2
landlords, 2 centers. Everything is deterministic from `SEED`, so the same
company, the same leases and the same answer key come out of every run. The
eval depends on that.

Two deliberate shapes here, both set up for later phases:

  - **Serramonte Plaza holds two Northbay stores.** That is what makes
    the Phase 2 shared-pool double billing case possible: one vendor line can
    be billed in full to both suites.
  - **Every lease names an authorized representative in its notices clause.**
    The source trust ranking turns on whether an email came from that named
    person or from property management without stated authority.
"""

from dataclasses import dataclass, field
from typing import List, Optional

SEED = 20261023
COMPANY_NAME = "Northbay Coffee"

# Phase 1 ran on five California stores. Phase 2 is the whole company. The
# five are unchanged inside it — same ids, same suites, same square footage,
# same landlords — so every rehearsed figure survives the scale-up.
PHASE1 = "phase1"
FULL = "full"


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
    # Set where this landlord sold the building and another now holds the
    # lease. The premises then carries one name in the lease and another on the
    # invoice, which is what makes resolving landlord names across sources a
    # real problem rather than a hypothetical one.
    succeeded_by: Optional[str] = None


@dataclass(frozen=True)
class Center:
    center_id: str
    name: str
    address: str
    landlord_id: str
    total_rsf: int
    # True where more than one Northbay clinic sits in the same center, so one
    # vendor line can be allocated to both. These are the shared-pool cases.
    shared_pool: bool = False


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
    entities: List[Entity] = field(default_factory=list)
    regions: List[Region] = field(default_factory=list)
    scope: str = PHASE1

    def __post_init__(self):
        if not self.entities:
            self.entities = [self.entity]
        if not self.regions:
            self.regions = [self.region]

    def entity_by(self, entity_id: str) -> Entity:
        return _one(self.entities, "entity_id", entity_id)

    def region_by(self, region_id: str) -> Region:
        return _one(self.regions, "region_id", region_id)

    def clinics_in_region(self, region_id: str) -> List[Clinic]:
        return [c for c in self.clinics if c.region_id == region_id]

    def clinics_in_entity(self, entity_id: str) -> List[Clinic]:
        return [c for c in self.clinics if c.entity_id == entity_id]

    def shared_pool_centers(self) -> List[Center]:
        """Centers holding more than one Northbay clinic."""
        return [c for c in self.centers if len(self.clinics_in(c.center_id)) > 1]

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


def build_company(scope: str = PHASE1, seed: int = SEED) -> Company:
    """The company at the requested scope.

    `PHASE1` is the five Bay Area clinics everything was built and rehearsed
    on. `FULL` is the real thing: three legal entities, three regions, thirty
    clinics, ten landlords, eight centers — with those five inside it,
    untouched.
    """
    base = _phase1(seed)
    if scope == PHASE1:
        return base
    if scope != FULL:
        raise ValueError("scope must be %r or %r, not %r" % (PHASE1, FULL, scope))
    return _full(base, seed)


def _phase1(seed: int) -> Company:
    entity = Entity("ENT-CA", "Northbay Coffee Company of California, Inc.", "CA")
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
        Center("CTR-SERRA", "Serramonte Plaza",
               "2001 Junipero Serra Blvd, Daly City, CA 94014", "LL-SERRA", 64_000),
        Center("CTR-BAYVIEW", "Bayview Commons",
               "410 E Hillsdale Blvd, San Mateo, CA 94403", "LL-PACIFIC", 48_500),
    ]

    clinics = [
        Clinic("STORE-01", "Northbay Coffee — Daly City", "ENT-CA", "REG-BAY",
               "CTR-SERRA", "Suite 210", 6_200, "café"),
        Clinic("STORE-02", "Northbay Coffee — Serramonte Express", "ENT-CA", "REG-BAY",
               "CTR-SERRA", "Suite 115", 3_100, "express bar"),
        Clinic("STORE-03", "Northbay Coffee — San Mateo", "ENT-CA", "REG-BAY",
               "CTR-BAYVIEW", "Suite 100", 5_400, "café"),
        Clinic("STORE-04", "Northbay Coffee — Bayview Drive-Thru", "ENT-CA", "REG-BAY",
               "CTR-BAYVIEW", "Suite 240", 4_150, "drive-thru"),
        Clinic("STORE-05", "Northbay Coffee — Bayview Roastery", "ENT-CA", "REG-BAY",
               "CTR-BAYVIEW", "Suite 305", 2_800, "roastery"),
    ]

    return Company(entity, region, people, landlords, centers, clinics, seed,
                   scope=PHASE1)


def _one(items, attr, value):
    for item in items:
        if getattr(item, attr) == value:
            return item
    raise KeyError("%s=%r" % (attr, value))


# --- the whole company -----------------------------------------------------
#
# Three legal entities, one per state, because that is how a group like this is
# actually structured and it is what makes the close a per-entity job. Three
# regions that do NOT map onto the entities: Bay Area and Southern California
# are both the California entity, while Desert spans Nevada and Arizona. A
# regional manager owns landlord relationships in their region; a controller
# owns the books of an entity. The two scopes cut across each other, which is
# precisely why permission checks need both.

_ENTITIES = [
    ("ENT-NV", "Northbay Coffee Company of Nevada, LLC", "NV"),
    ("ENT-AZ", "Northbay Coffee Company of Arizona, LLC", "AZ"),
]

_REGIONS = [
    ("REG-SOCAL", "Southern California", "PER-RM-SOCAL"),
    ("REG-DESERT", "Desert", "PER-RM-DESERT"),
]

_MANAGERS = [
    ("PER-RM-SOCAL", "Imani Okonkwo", "imani.okonkwo@northbaypt.example"),
    ("PER-RM-DESERT", "Theo Lindqvist", "theo.lindqvist@northbaypt.example"),
]

# Eight landlords hold the eight centers. Two more appear as the landlord of
# record on leases at buildings that were since sold, so the same premises has
# one name in the lease and another on the invoice. That is what makes entity
# resolution across sources a real problem rather than a hypothetical one.
_LANDLORDS = [
    ("LL-CRESTLINE", "Crestline Medical Holdings LLC",
     "2200 Wilshire Blvd, Suite 820, Santa Monica, CA 90403",
     "Rosa Beltran", "rbeltran@crestlinemed.example",
     "Omar Haddad", "ohaddad@pinnaclepm.example", None),
    ("LL-VALLEYOAK", "Valley Oak Properties LP",
     "500 N Brand Blvd, Glendale, CA 91203",
     "Nathan Choi", "nchoi@valleyoakprop.example",
     "Priscilla Nunez", "pnunez@valleyoakpm.example", None),
    ("LL-SUNRIDGE", "Sunridge Commercial Trust",
     "7900 W Sahara Ave, Las Vegas, NV 89117",
     "Marguerite Dupont", "mdupont@sunridgetrust.example",
     "Caleb Ruiz", "cruiz@desertpm.example", None),
    ("LL-SAGUARO", "Saguaro Plaza Partners LLC",
     "4455 E Camelback Rd, Phoenix, AZ 85018",
     "Hector Villanueva", "hvillanueva@saguaroplaza.example",
     "Dawn Fitzgerald", "dfitzgerald@saguaropm.example", None),
    ("LL-HARBORPT", "Harbor Point Realty Group",
     "1 World Trade Center, Suite 900, Long Beach, CA 90831",
     "Yuki Tanabe", "ytanabe@harborpointrealty.example",
     "Gregory Adeyemi", "gadeyemi@harborpm.example", None),
    ("LL-REDROCK", "Red Rock Office Holdings LLC",
     "6671 Las Vegas Blvd S, Las Vegas, NV 89119",
     "Sofia Markovic", "smarkovic@redrockoffice.example",
     "Benjamin Osei", "bosei@redrockpm.example", None),
    # Sold their buildings; still named on the original leases.
    ("LL-PALOVERDE", "Palo Verde Investors LLC",
     "2929 N Central Ave, Phoenix, AZ 85012",
     "Annette Kowalski", "akowalski@paloverdeinv.example",
     "Annette Kowalski", "akowalski@paloverdeinv.example", "LL-SAGUARO"),
    ("LL-MERIDIAN", "Meridian Street Capital LLC",
     "801 S Figueroa St, Los Angeles, CA 90017",
     "Darius Bennett", "dbennett@meridianstreet.example",
     "Darius Bennett", "dbennett@meridianstreet.example", "LL-HARBORPT"),
]

# center_id, name, address, landlord, total rsf, how many Northbay stores
_CENTERS = [
    ("CTR-WILSHIRE", "Wilshire Court", "2240 Wilshire Blvd, Santa Monica, CA 90403",
     "LL-CRESTLINE", 71_500, 5),
    ("CTR-GLENDALE", "Glendale Pavilion", "520 N Brand Blvd, Glendale, CA 91203",
     "LL-VALLEYOAK", 58_200, 4),
    ("CTR-HARBOR", "Harbor Point Center", "3300 E Willow St, Long Beach, CA 90806",
     "LL-HARBORPT", 49_800, 3),
    ("CTR-SAHARA", "Sahara Crossing", "7920 W Sahara Ave, Las Vegas, NV 89117",
     "LL-SUNRIDGE", 44_600, 4),
    ("CTR-REDROCK", "Red Rock Plaza", "6690 Via Austi Pkwy, Las Vegas, NV 89119",
     "LL-REDROCK", 38_900, 3),
    ("CTR-CAMELBACK", "Camelback Commons", "4480 E Camelback Rd, Phoenix, AZ 85018",
     "LL-SAGUARO", 52_300, 6),
]

_SERVICE_LINES = [
    "café", "drive-thru", "express bar", "roastery",
    "bakery café", "reserve bar", "kiosk",
]

_CITY_FOR = {
    "CTR-WILSHIRE": "Santa Monica", "CTR-GLENDALE": "Glendale",
    "CTR-HARBOR": "Long Beach", "CTR-SAHARA": "Las Vegas",
    "CTR-REDROCK": "Las Vegas", "CTR-CAMELBACK": "Phoenix",
}

_REGION_FOR = {
    "CTR-WILSHIRE": ("REG-SOCAL", "ENT-CA"),
    "CTR-GLENDALE": ("REG-SOCAL", "ENT-CA"),
    "CTR-HARBOR": ("REG-SOCAL", "ENT-CA"),
    "CTR-SAHARA": ("REG-DESERT", "ENT-NV"),
    "CTR-REDROCK": ("REG-DESERT", "ENT-NV"),
    "CTR-CAMELBACK": ("REG-DESERT", "ENT-AZ"),
}

# Suite sizes, cycled deterministically so every store differs but no run does.
_RSF_CYCLE = (5_900, 3_400, 4_750, 2_950, 6_400, 3_850, 5_200, 4_100)


def _full(base: Company, seed: int) -> Company:
    entities = [base.entity] + [Entity(*e) for e in _ENTITIES]
    regions = [base.region] + [Region(*r) for r in _REGIONS]
    people = list(base.people) + [
        Person(pid, name, "regional_manager", email) for pid, name, email in _MANAGERS
    ]
    landlords = list(base.landlords) + [
        Landlord(lid, name, addr, rep, rep_email, pm, pm_email, succeeded_by)
        for lid, name, addr, rep, rep_email, pm, pm_email, succeeded_by in _LANDLORDS
    ]

    centers = list(base.centers)
    clinics = list(base.clinics)
    index = len(base.clinics)

    for center_id, name, address, landlord_id, total_rsf, count in _CENTERS:
        centers.append(Center(center_id, name, address, landlord_id, total_rsf,
                              shared_pool=count > 1))
        region_id, entity_id = _REGION_FOR[center_id]
        for n in range(count):
            index += 1
            clinics.append(Clinic(
                clinic_id="STORE-%02d" % index,
                name="Northbay Coffee — %s %s" % (
                    _CITY_FOR[center_id],
                    _SERVICE_LINES[index % len(_SERVICE_LINES)].title()),
                entity_id=entity_id,
                region_id=region_id,
                center_id=center_id,
                suite="Suite %d" % (100 + n * 45 + (index % 7) * 5),
                rsf=_RSF_CYCLE[index % len(_RSF_CYCLE)],
                service_line=_SERVICE_LINES[index % len(_SERVICE_LINES)],
            ))

    # The two Phase 1 centers hold more than one clinic each, so they are
    # shared pools too.
    centers = [
        Center(c.center_id, c.name, c.address, c.landlord_id, c.total_rsf,
               shared_pool=len([x for x in clinics if x.center_id == c.center_id]) > 1)
        for c in centers
    ]

    return Company(base.entity, base.region, people, landlords, centers, clinics,
                   seed, entities=entities, regions=regions, scope=FULL)
