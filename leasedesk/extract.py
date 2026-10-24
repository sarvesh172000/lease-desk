"""Turn messy lease documents into structured terms with Claude.

The model's only job is to read: what does this document say the rent is, when
does it change, when does the term end. Every number it returns is then fed to
`schedule.py`, which does the arithmetic. Nothing here computes a balance.
"""

from datetime import date
from typing import List, Optional
import os

from pydantic import BaseModel, Field

MODEL = "claude-opus-5-5"

ABSTRACT_PROMPT = """You are a lease abstractor for a corporate accounting team.

Read the document and extract only what it states. Rules:
- Never infer a number that is not written or directly derivable from stated
  terms (an escalation percentage plus a base rent is derivable; a market rate
  is not).
- Dates are ISO (YYYY-MM-DD). Rent is a monthly dollar amount.
- If the document is an amendment, extract only what it CHANGES.
- If a term is genuinely absent, leave it null and say so in `uncertain`.
"""

FIND_PROMPT = """You are searching a corporate mailbox for the reason a rent
payment stopped matching the lease schedule.

Variance: {variance}

Below are message snippets. Identify which, if any, explains the variance.
Quote the exact sentence you relied on. If none of them explains it, say so —
do not stretch an unrelated message to fit.
"""


class ExtractedStep(BaseModel):
    start: str = Field(description="First month this rent applies, YYYY-MM-DD")
    end: str = Field(description="Last month this rent applies, YYYY-MM-DD")
    monthly_rent: float


class ExtractedLease(BaseModel):
    location: str
    lessor: str
    commencement: Optional[str] = None
    end: Optional[str] = None
    steps: List[ExtractedStep] = Field(default_factory=list)
    renewal_options: List[str] = Field(default_factory=list)
    uncertain: List[str] = Field(
        default_factory=list,
        description="Terms the document does not state clearly; these go to a human.",
    )
    quotes: List[str] = Field(
        default_factory=list, description="Exact sentences supporting the extraction"
    )


class FoundAmendment(BaseModel):
    explains_variance: bool
    source: Optional[str] = None
    summary: Optional[str] = None
    effective: Optional[str] = None
    new_end: Optional[str] = None
    steps: List[ExtractedStep] = Field(default_factory=list)
    quote: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def abstract_lease(document_text: str) -> ExtractedLease:
    """Pull structured terms out of a lease PDF's text."""
    response = _client().messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=ABSTRACT_PROMPT,
        messages=[{"role": "user", "content": document_text}],
        output_format=ExtractedLease,
    )
    return response.parsed_output


def find_amendment(variance_text: str, messages: List[str]) -> FoundAmendment:
    """Search inbox snippets for the document that explains a payment variance."""
    corpus = "\n\n---\n\n".join(messages)
    response = _client().messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=FIND_PROMPT.format(variance=variance_text),
        messages=[{"role": "user", "content": corpus}],
        output_format=FoundAmendment,
    )
    return response.parsed_output


def available() -> bool:
    """True when the API key is set, so the CLI can fall back to stored data."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
