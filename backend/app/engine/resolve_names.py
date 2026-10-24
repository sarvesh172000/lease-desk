"""Decide whether two names are the same party.

"Pacific Crest Properties LLC" on the lease, "Pacific Crest Prop. Mgmt" on the
invoice, "PACIFIC CREST PROPERTIES, L.L.C." in the bank export. A human reads
all three as one landlord without thinking about it; a join on the string
produces three.

It matters beyond tidiness. A charge that cannot be tied to a landlord cannot
be tied to a lease, so it cannot be checked at all — it falls out of the
reconciliation silently, which is the worst way for a charge to fail.

Two things this deliberately does not do. It does not merge on a close score
alone: above the threshold it proposes, and a person confirms, because quietly
merging two landlords that are genuinely different corrupts every figure that
follows. And it does not treat a successor name as the same party — when a
building is sold the new owner is a different legal entity, so that link is
recorded as a succession, not as an alias.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Tuple

# Above this, two names are the same party. Between the two, a human decides.
CERTAIN = 0.92
PROPOSE = 0.78

_SUFFIXES = (
    "llc", "l l c", "inc", "incorporated", "lp", "llp", "ltd", "limited",
    "corp", "corporation", "co", "company", "trust", "partners", "partnership",
    "holdings", "group", "properties", "property", "realty", "investors",
    "management", "mgmt", "capital", "associates",
)

_ABBREVIATIONS = {
    "prop": "properties", "props": "properties", "mgmt": "management",
    "mgt": "management", "assoc": "associates", "co": "company",
    "intl": "international", "natl": "national", "svcs": "services",
}


@dataclass(frozen=True)
class Match:
    query: str
    matched_id: Optional[str]
    matched_name: Optional[str]
    score: float
    verdict: str  # "resolved" | "propose" | "unmatched"
    reason: str

    @property
    def needs_human(self) -> bool:
        return self.verdict == "propose"


@dataclass
class Directory:
    """The parties we know about, and the names they go by."""
    names: Dict[str, str] = field(default_factory=dict)          # id -> canonical
    aliases: Dict[str, str] = field(default_factory=dict)        # alias id -> id
    successions: Dict[str, str] = field(default_factory=dict)    # old id -> new id

    @classmethod
    def from_landlords(cls, landlords: Iterable) -> "Directory":
        directory = cls()
        for landlord in landlords:
            directory.names[landlord.landlord_id] = landlord.name
            successor = getattr(landlord, "succeeded_by", None)
            if successor:
                directory.successions[landlord.landlord_id] = successor
        return directory

    def canonical(self, party_id: str) -> Optional[str]:
        return self.names.get(self.aliases.get(party_id, party_id))

    def current_owner(self, party_id: str) -> str:
        """Follow a succession to whoever holds the building now.

        Kept separate from aliasing: the predecessor is a different legal
        entity, and the lease still names it.
        """
        seen = set()
        while party_id in self.successions and party_id not in seen:
            seen.add(party_id)
            party_id = self.successions[party_id]
        return party_id


def normalize(name: str) -> str:
    """Strip what varies and keep what identifies.

    Punctuation, case, entity suffixes and the common abbreviations all go;
    what is left is the distinctive part of the name.
    """
    text = re.sub(r"[^a-z0-9\s]", " ", (name or "").lower())
    # "L.L.C." becomes three single-letter tokens once punctuation goes, and
    # none of them matches an entry in the suffix list. Dropping one-character
    # words first is what lets the spelled-out form match the plain one.
    words = [w for w in text.split() if len(w) > 1]
    words = [_ABBREVIATIONS.get(w, w) for w in words]
    kept = [w for w in words if w not in _SUFFIXES]
    return " ".join(kept or words)


def similarity(left: str, right: str) -> float:
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    ratio = SequenceMatcher(None, a, b).ratio()
    # A name that is wholly contained in the other — "pacific crest" inside
    # "pacific crest property management" — is a strong signal the sequence
    # ratio alone under-weights.
    if a in b or b in a:
        ratio = max(ratio, 0.90)

    left_words, right_words = set(a.split()), set(b.split())
    overlap = len(left_words & right_words) / max(len(left_words), len(right_words))
    return round(max(ratio, overlap * 0.95), 4)


def resolve(name: str, directory: Directory) -> Match:
    """Which known party this name refers to, if any."""
    if not name or not name.strip():
        return Match(name, None, None, 0.0, "unmatched", "empty name")

    scored: List[Tuple[float, str]] = sorted(
        ((similarity(name, canonical), party_id)
         for party_id, canonical in directory.names.items()),
        reverse=True,
    )
    if not scored:
        return Match(name, None, None, 0.0, "unmatched", "no known parties")

    score, party_id = scored[0]
    canonical = directory.names[party_id]

    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if score >= CERTAIN and score - runner_up >= 0.05:
        return Match(name, party_id, canonical, score, "resolved",
                     "matches %r" % canonical)

    if score >= PROPOSE:
        close = [directory.names[p] for s, p in scored[:3] if s >= PROPOSE]
        return Match(name, party_id, canonical, score, "propose",
                     "closest is %r at %.0f%%%s — a person confirms before "
                     "anything is merged" % (
                         canonical, score * 100,
                         ", but %d candidates are close" % len(close)
                         if len(close) > 1 else ""))

    return Match(name, None, None, score, "unmatched",
                 "nothing above %.0f%%; closest was %r at %.0f%%"
                 % (PROPOSE * 100, canonical, score * 100))


def resolve_all(names: Iterable[str], directory: Directory) -> List[Match]:
    return [resolve(name, directory) for name in names]
