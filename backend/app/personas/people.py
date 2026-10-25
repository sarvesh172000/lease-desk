"""The people, simulated, so a year can run without anyone at the keyboard.

A year of unattended operation is the claim; it cannot be tested if every
escalation waits for a human. So each person the system escalates to has a
facts file — what they know, what they agreed to by phone, what they would
refuse — and answers are generated from those facts and nothing else.

Three rules make this honest rather than a way of marking our own homework:

  **A persona answers only from its facts.** It is not told the answer key, or
  what the system hopes to hear. Asked something its facts do not cover, it
  says so, and the question stays open — which is the realistic outcome.

  **Every answer is tagged `simulated`.** It goes into the audit stream marked,
  so no demo can pass a generated approval off as a human one, and no eval can
  count one as evidence a person agreed.

  **The controller sometimes says no.** A system only ever tested on yes has
  never exercised the path that matters most.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

AGREE = "agree"
REFUSE = "refuse"
UNKNOWN = "unknown"
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Persona:
    person_id: str
    name: str
    role: str
    region_id: Optional[str]
    entity_id: Optional[str]
    # What this person actually knows. Nothing else is available to them.
    facts: List[str] = field(default_factory=list)
    # Things they would not agree to, whatever the system proposes.
    refuses: List[str] = field(default_factory=list)
    response_days: int = 2
    # Out of ten, how often they simply do not reply in time.
    unavailable_in: int = 0

    def knows_about(self, topic: str) -> Optional[str]:
        return _best(topic, self.facts)

    def would_refuse(self, topic: str) -> Optional[str]:
        return _best(topic, self.refuses)


@dataclass
class Answer:
    question_id: str
    persona_id: str
    verdict: str
    body: str
    answered_on: Optional[date]
    basis: Optional[str] = None
    # Always true here. It is carried into the audit stream so a generated
    # approval can never be mistaken for a person's.
    simulated: bool = True

    @property
    def settles(self) -> bool:
        return self.verdict in (AGREE, REFUSE)


PERSONAS: Dict[str, Persona] = {
    "PER-RM-BAY": Persona(
        "PER-RM-BAY", "Dana Whitfield", "regional_manager", "REG-BAY", "ENT-CA",
        facts=[
            "Serramonte agreed in June 2026 to extend Suite 210 three years and "
            "cut rent to $17,400; facilities has the executed amendment.",
            "Suite 118 was handed back in 2024 and Northbay has not occupied it since.",
            "The Serramonte operating expense estimate was never renegotiated; "
            "the lease rate of $11.50 per square foot still stands.",
        ],
        refuses=[
            "paying a capital cost such as parking lot repaving through operating expenses",
        ],
        response_days=2,
        unavailable_in=1,
    ),
    "PER-RM-SOCAL": Persona(
        "PER-RM-SOCAL", "Imani Okonkwo", "regional_manager", "REG-SOCAL", "ENT-CA",
        facts=[
            "No escalation was renegotiated at any Southern California store in 2026.",
            "Wilshire Court changed property managers in March; the landlord entity did not change.",
        ],
        refuses=["an escalation applied before the lease anniversary"],
        response_days=3,
        unavailable_in=2,
    ),
    "PER-RM-DESERT": Persona(
        "PER-RM-DESERT", "Theo Lindqvist", "regional_manager", "REG-DESERT", None,
        facts=["Nothing was agreed verbally with any Desert landlord in 2026."],
        refuses=["a charge with no supporting document"],
        response_days=4,
        unavailable_in=3,
    ),
    "PER-CTRL": Persona(
        "PER-CTRL", "Priya Raghunathan", "controller", None, None,
        facts=[
            "Remeasurement entries may be posted once the executed amendment is on file.",
            "Operating leases only; no finance lease classification has been adopted.",
            "Materiality for the 2026 close is $5,000 per entity.",
        ],
        refuses=[
            "posting an adjustment with no executed document behind it",
            "closing a period while the subledger does not tie to the general ledger",
        ],
        response_days=1,
        unavailable_in=0,
    ),
    "PER-AP": Persona(
        "PER-AP", "Marcus Oyelaran", "ap_clerk", None, None,
        facts=["Payment batches are released on the first business day of the month."],
        refuses=["releasing a payment for a charge still under review"],
        response_days=1,
        unavailable_in=1,
    ),
}


def answer(persona: Persona, question_id: str, topic: str, asked_on: date,
           sequence: Optional[int] = None) -> Answer:
    """How this person replies, from their facts alone.

    Deterministic: the same question on the same day gets the same answer, so
    a year can be replayed and compared. Unavailability is spread across the
    question id rather than a counter, because defaulting a counter to zero
    made anyone with any unavailability unavailable every single time.
    """
    slot = sequence if sequence is not None else _slot(question_id)
    if persona.unavailable_in and (slot % 10) < persona.unavailable_in:
        return Answer(
            question_id, persona.person_id, UNAVAILABLE,
            "%s did not respond before the due date." % persona.name,
            None, None,
        )

    # A specific fact beats a general objection. "May we post the
    # remeasurement entries?" is covered by a fact saying exactly that, and
    # must not be caught by a standing refusal about posting without a
    # document — which is what happened while matching was on substrings.
    fact = persona.knows_about(topic)
    refusal = persona.would_refuse(topic)
    if refusal and (fact is None or _score(topic, refusal) > _score(topic, fact)):
        return Answer(
            question_id, persona.person_id, REFUSE,
            "%s will not agree to this: %s." % (persona.name, refusal),
            asked_on + timedelta(days=persona.response_days), refusal,
        )

    if fact:
        return Answer(
            question_id, persona.person_id, AGREE,
            "%s confirms: %s" % (persona.name, fact),
            asked_on + timedelta(days=persona.response_days), fact,
        )

    return Answer(
        question_id, persona.person_id, UNKNOWN,
        "%s does not know. The question stays open." % persona.name,
        asked_on + timedelta(days=persona.response_days), None,
    )


def route(role: str, region_id: Optional[str] = None) -> Optional[Persona]:
    for persona in PERSONAS.values():
        if persona.role != role:
            continue
        if region_id is None or persona.region_id == region_id:
            return persona
    return None


def _slot(question_id: str) -> int:
    return sum(ord(c) for c in question_id)


def _keywords(topic: str) -> List[str]:
    stop = {"the", "a", "an", "of", "for", "to", "is", "was", "and", "in", "on",
            "at", "with", "this", "that", "they", "them", "we", "may", "can",
            "should", "would", "did", "does", "any", "still", "about"}
    return [w.strip(".,;:?()").lower() for w in topic.split()
            if len(w) > 3 and w.strip(".,;:?()").lower() not in stop]


def _score(topic: str, candidate: str) -> int:
    """How many whole words the question and the statement share.

    Whole words, not substrings: "post" inside "posting" matched a standing
    refusal against a question the person's own facts answered.
    """
    words = set(_keywords(candidate))
    return sum(1 for word in _keywords(topic) if word in words)


def _best(topic: str, candidates: List[str], minimum: int = 1) -> Optional[str]:
    scored = [(_score(topic, c), c) for c in candidates]
    scored = [(s, c) for s, c in scored if s >= minimum]
    if not scored:
        return None
    return max(scored, key=lambda pair: pair[0])[1]
