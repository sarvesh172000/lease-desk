"""Response models. The first three mirror the frozen fixtures in DESIGN.md §16
key for key; the rest have no fixture and are documented here instead.

Money is serialized as a JSON number with two decimals of meaning, because
that is what the fixtures show and what the frontend is built against. A field
is Optional only where the real data can genuinely lack it; then it is null,
never a made-up value.
"""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel

# The four statuses the frontend's StatusBadge knows (DESIGN.md §16).
STATUSES = ("balanced", "exception", "pending_review", "escalated")


# --- GET /api/leases ----------------------------------------------------------

class LeaseSummary(BaseModel):
    lease_id: str
    clinic_id: str
    location: str
    lessor: str
    status: str                       # 'exception' | 'balanced'
    monthly_rent: Optional[float]     # null when the lease's terms are not on file
    liability: Optional[float]
    end: Optional[date]


# --- GET /api/exceptions ------------------------------------------------------

class ExceptionSummary(BaseModel):
    exception_id: str
    lease_id: Optional[str]
    clinic_id: Optional[str]
    period: Optional[date]
    charge_type: Optional[str]
    expected: Optional[float]
    actual: Optional[float]
    delta: Optional[float]
    status: str
    confidence: Optional[float]


# --- GET /api/exceptions/{id} -------------------------------------------------

class Evidence(BaseModel):
    doc_id: Optional[str] = None
    date: Optional[str] = None
    source: Optional[str] = None
    trust_rank: Optional[int] = None
    quote: Optional[str] = None
    page: Optional[int] = None
    box: Optional[List[float]] = None


class Entry(BaseModel):
    account: str
    debit: float
    credit: float


class Investigation(BaseModel):
    root_cause: Optional[str] = None
    confidence: Optional[float] = None
    explains_variance: Optional[bool] = None
    evidence: List[Evidence] = []
    liability_before: Optional[float] = None
    liability_after: Optional[float] = None
    rou_before: Optional[float] = None
    rou_after: Optional[float] = None
    entries: List[Entry] = []
    balanced: Optional[bool] = None


class InvoiceLine(BaseModel):
    """The billed line under review, boxed on the invoice page it came from.
    `page`/`box` are located in the stored PDF; null when the text was not
    found, which leaves the page shown without a highlight."""
    doc_id: Optional[str] = None
    page: Optional[int] = None
    box: Optional[List[float]] = None
    description: Optional[str] = None
    amount: Optional[float] = None


class LeaseCitation(BaseModel):
    """The lease clause the expected amount rests on, as the checker cited it."""
    doc_id: Optional[str] = None
    page: Optional[int] = None
    box: Optional[List[float]] = None
    label: Optional[str] = None
    quote: Optional[str] = None


class ExceptionDetail(BaseModel):
    exception_id: str
    lease_id: Optional[str]
    clinic_id: Optional[str] = None
    period: Optional[date]
    charge_type: Optional[str] = None
    expected: Optional[float]
    actual: Optional[float]
    delta: Optional[float]
    status: str
    confidence: Optional[float] = None
    invoice_line: Optional[InvoiceLine] = None
    lease_citation: Optional[LeaseCitation] = None
    # None when nothing has been investigated: an empty Investigation would
    # read on screen as an investigation that found nothing, which is a
    # different claim.
    investigation: Optional[Investigation]


# --- POST /api/exceptions/{id}/approve ----------------------------------------

class ApproveResult(BaseModel):
    """§16 #4 returns the new status, one of STATUSES."""
    status: str


# --- GET /api/leases/{id}/schedule (no fixture in §16) -------------------------

class ScheduleRow(BaseModel):
    """One month, the fields of SCHEDULE_PERIOD in DESIGN.md §15."""
    index: int
    period: date
    payment: float
    interest: float
    liability_open: float
    liability_close: float
    rou_open: float
    rou_amortization: float
    rou_close: float
    straight_line_cost: float


class Schedule(BaseModel):
    lease_id: str
    version: int
    versions: List[int]               # every version this lease has, for a picker
    effective_from: date              # commencement for v1, the amendment date after
    confirmed: bool                   # v1 is the lease as signed; later ones need a person
    discount_rate: float
    opening_liability: float
    opening_rou: float
    rows: List[ScheduleRow]


# --- GET /api/audit (no fixture in §16) -----------------------------------------

class AuditEvent(BaseModel):
    seq: int
    at: datetime
    actor_id: str
    action: str
    subject_type: str
    subject_id: str
    allowed: bool
    reason: Optional[str]


class AuditTrail(BaseModel):
    chain_verified: bool
    broken_seq: Optional[int]         # the first broken link, when there is one
    events: List[AuditEvent]


# --- GET /api/documents/{sha}/pages (no fixture in §16) -------------------------

class PageSize(BaseModel):
    number: int                       # 1-based, as citations cite it
    width: float                      # PDF points; scale `box` against these
    height: float


class DocumentPages(BaseModel):
    sha256: str
    page_count: int
    pages: List[PageSize]
