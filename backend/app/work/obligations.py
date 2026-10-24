"""Obligations and critical dates (PHASE_2.md group 12).

What a lease makes someone do by a date, computed from the lease's own terms
with the clause that sets each one:

  renewal_notice    the last day written notice exercising the renewal option
                    can reach the landlord: expiration minus the notice days
                    (Section 11.2). Missing it voids the option. Only when the
                    lease grants at least one option.
  expiration        the expiration date (Section 2).
  deposit_return    expiration plus 30 days (Section 5.2): the landlord owes
                    the security deposit back; follow up if it is not paid.
                    Assumes surrender on the expiration date (5.2 runs from the
                    later of the two).
  cam_audit_window  for each calendar year of the term, the last day to audit
                    the landlord's operating expense statement: 180 days after
                    receipt (Section 4.7) of a statement due 120 days after the
                    year ends (Section 4.6). Assumes the statement arrives on
                    the last day 4.6 allows; a late statement moves the window
                    later, never earlier, so the date is the safe one.

Where the terms come from: the lease's confirmed lease_version rows (the
highest confirmed version that states each field, so a confirmed amendment
wins), with the lease_term's page, quote and document as the citation. A
lease with no confirmed version falls back to the generator's terms (the
same path jobs/lease_versions.py drafts from), marked source 'generator',
with the sentence the lease template prints but no page.

The deadline job (jobs/obligations.py, as lease_agent) refreshes the table
and opens an OBLIGATION work item at 90, 60 and 30 business days (weekdays;
holidays are not modelled) before each due date, routed to the clinic's
region, proposed by agent:obligations. Each threshold fires once: the item's
subject_id is <obligation id>:<due date>:<threshold>bd, and create_item is
idempotent on it. When the clock jumps past several thresholds at once only
the most urgent fires. The regional manager's decision (approve: acted on;
reject: not acting, with a reason) is recorded on the item.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .events import append_event
from .roles import load_actor
from .transitions import create_item, transition

AGENT = "agent:obligations"
ITEM_KIND = "OBLIGATION"
SUBJECT = "obligation"

RENEWAL_NOTICE = "renewal_notice"
EXPIRATION = "expiration"
DEPOSIT_RETURN = "deposit_return"
CAM_AUDIT = "cam_audit_window"
KINDS = (RENEWAL_NOTICE, CAM_AUDIT, DEPOSIT_RETURN, EXPIRATION)

THRESHOLDS = (90, 60, 30)              # business days before the due date
DEPOSIT_RETURN_DAYS = 30               # Section 5.2
STATEMENT_DAYS = 120                   # Section 4.6
AUDIT_DAYS = 180                       # Section 4.7

CONFIRMED_STATES = ("APPROVED", "POSTED", "CLOSED")

# The lease form's clauses (datagen/render_lease.py renders these sentences;
# the section numbers are a fact about the template, like
# engine/from_datagen's PROOF_TEMPLATES).
CLAUSES = {
    "expiration": ("2", None),
    "renewal": ("11.2", None),
    "deposit_return": ("5.2", "Landlord shall return the security deposit, less any amounts "
                              "properly applied, within thirty (30) days after the later of the "
                              "expiration of the Term"),
    "reconciliation": ("4.6", "Within one hundred twenty (120) days after the end of each "
                              "calendar year, Landlord shall deliver to Tenant a statement"),
    "audit": ("4.7", "Tenant shall have the right, exercisable not later than one hundred "
                     "eighty (180) days after receipt of Landlord's annual statement, to audit"),
}

FIELDS = ("commencement", "expiration", "security_deposit", "renewal_count", "renewal_years",
          "renewal_notice_days")


@dataclass(frozen=True)
class Term:
    value: Any
    page: Optional[int] = None
    quote: Optional[str] = None
    document_id: Optional[str] = None
    lease_version_id: Optional[int] = None

    def cite(self, field_name: str, section: Optional[str]) -> Dict[str, Any]:
        return {"field": field_name, "section": section, "page": self.page, "quote": self.quote,
                "document_id": self.document_id, "lease_version_id": self.lease_version_id}


@dataclass(frozen=True)
class Obligation:
    lease_id: str
    kind: str
    key: str
    due_date: date
    action: str
    citation: Dict[str, Any]
    source: str
    lease_version_id: Optional[int]
    details: Dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------ business days

def business_days_before(d: date, n: int) -> date:
    """The date n weekdays before d."""
    if n < 0:
        raise ValueError("n must be >= 0")
    out = d
    while n:
        out -= timedelta(days=1)
        if out.weekday() < 5:
            n -= 1
    return out


def alert_dates(due: date) -> Dict[int, date]:
    return {n: business_days_before(due, n) for n in THRESHOLDS}


def threshold_for(today: date, due: date) -> Optional[int]:
    """The threshold that is current on `today`: the most urgent one whose
    alert date has passed, while the due date has not."""
    if today > due:
        return None
    for n in sorted(THRESHOLDS):
        if today >= business_days_before(due, n):
            return n
    return None


# -------------------------------------------------------------------- terms

def lease_terms(conn: Connection, lease_id: str) -> Tuple[Dict[str, Term], str]:
    """(field -> Term, source). Confirmed lease_version rows first, newest
    confirmed version per field; else the generator's terms."""
    rows = conn.execute(text("""
        SELECT v.id AS version_id, v.version, t.field, t.value, t.page, t.quote, t.document_id
          FROM lease_version v
          JOIN lease_term t ON t.lease_version_id = v.id
         WHERE v.lease_id = :lease AND v.confirmed_by IS NOT NULL
           AND coalesce((SELECT w.state FROM work_item w
                          WHERE w.subject_type = 'lease_version' AND w.subject_id = v.id::text
                          ORDER BY w.id DESC LIMIT 1), 'APPROVED') = ANY(:ok)
           AND t.field = ANY(:fields)
         ORDER BY v.version DESC
    """), {"lease": lease_id, "ok": list(CONFIRMED_STATES), "fields": list(FIELDS)}).mappings()
    terms: Dict[str, Term] = {}
    for r in rows:
        if r["field"] in terms:
            continue
        value = r["value"]
        if isinstance(value, dict) and "value" in value:
            value = value["value"]
        if value in (None, ""):
            continue
        terms[r["field"]] = Term(value, r["page"], r["quote"], r["document_id"], r["version_id"])
    if "expiration" in terms:
        return terms, "lease_term"
    return generator_terms(lease_id), "generator"


def generator_terms(lease_id: str) -> Dict[str, Term]:
    """The generator's terms with the sentence the lease template prints for
    each (jobs/lease_versions.py's generator path). Empty when the generator
    has no such lease."""
    from ..jobs.lease_versions import generator_quotes
    from ..jobs.lease_versions import generator_terms as gen

    terms, company = gen(lease_id)
    if terms is None:
        return {}
    quotes = generator_quotes(terms, company)
    return {name: Term(value, None, quote) for name, (value, quote) in quotes.items()
            if name in FIELDS}


# ------------------------------------------------------------------ compute

def compute(lease_id: str, terms: Mapping[str, Term], source: str, *,
            landlord: Optional[Mapping] = None,
            locate: Optional[Any] = None) -> List[Obligation]:
    """Every obligation the terms imply. Pure but for `locate(quote)`, an
    optional callable returning (page, document_id) for a template clause."""
    expiration_t = terms.get("expiration")
    if expiration_t is None:
        return []
    expiration = _date(expiration_t.value)
    if expiration is None:
        return []
    commencement = _date(terms["commencement"].value) if "commencement" in terms else None
    version = expiration_t.lease_version_id
    out: List[Obligation] = []
    landlord = landlord or {}

    out.append(Obligation(
        lease_id, EXPIRATION, EXPIRATION, expiration,
        "Lease %s expires %s: decide on renewal, relocation or surrender in time for the "
        "renewal notice." % (lease_id, expiration.isoformat()),
        {"section": CLAUSES["expiration"][0], **expiration_t.cite("expiration", "2")},
        source, version))

    count = _int(terms.get("renewal_count"))
    days = _int(terms.get("renewal_notice_days"))
    years = _int(terms.get("renewal_years"))
    if count and days:
        due = expiration - timedelta(days=days)
        notice = terms["renewal_notice_days"]
        out.append(Obligation(
            lease_id, RENEWAL_NOTICE, RENEWAL_NOTICE, due,
            "Last day for written notice exercising the renewal option (%d option%s of %d "
            "years) to reach %s%s. Time is of the essence: missing it voids the option."
            % (count, "" if count == 1 else "s", years or 0, landlord.get("name") or "the landlord",
               (" at " + landlord["notice_address"]) if landlord.get("notice_address") else ""),
            {**notice.cite("renewal_notice_days", CLAUSES["renewal"][0]),
             "also": [expiration_t.cite("expiration", "2")]},
            source, version, {"notice_days": days, "options": count, "years": years}))

    deposit = terms.get("security_deposit")
    if deposit is not None and _float(deposit.value):
        due = expiration + timedelta(days=DEPOSIT_RETURN_DAYS)
        section, quote = CLAUSES["deposit_return"]
        page, doc = (locate(quote) if locate else (None, None)) or (None, None)
        out.append(Obligation(
            lease_id, DEPOSIT_RETURN, DEPOSIT_RETURN, due,
            "Landlord owes the $%s security deposit back within %d days after expiration and "
            "surrender: by %s if surrendered on expiration. Follow up if it is not received."
            % ("{:,.2f}".format(_float(deposit.value)), DEPOSIT_RETURN_DAYS, due.isoformat()),
            {"section": section, "quote": quote, "page": page,
             "document_id": doc or deposit.document_id, "field": None,
             "lease_version_id": version,
             "also": [deposit.cite("security_deposit", "5.1"), expiration_t.cite("expiration", "2")],
             "assumption": "surrender on the expiration date"},
            source, version, {"deposit": str(deposit.value)}))

    if commencement is not None:
        rec_section, rec_quote = CLAUSES["reconciliation"]
        aud_section, aud_quote = CLAUSES["audit"]
        rec_at = (locate(rec_quote) if locate else None) or (None, None)
        aud_at = (locate(aud_quote) if locate else None) or (None, None)
        for year in range(commencement.year, expiration.year + 1):
            statement_due = date(year, 12, 31) + timedelta(days=STATEMENT_DAYS)
            due = statement_due + timedelta(days=AUDIT_DAYS)
            out.append(Obligation(
                lease_id, CAM_AUDIT, "%s:%d" % (CAM_AUDIT, year), due,
                "Last day to exercise the audit right over %d operating expenses: %d days after "
                "the annual statement, due by %s. Review the reconciliation before then."
                % (year, AUDIT_DAYS, statement_due.isoformat()),
                {"section": aud_section, "quote": aud_quote, "page": aud_at[0],
                 "document_id": aud_at[1], "field": None, "lease_version_id": version,
                 "also": [{"section": rec_section, "quote": rec_quote, "page": rec_at[0],
                           "document_id": rec_at[1]}],
                 "assumption": "the statement arrives on the last day Section 4.6 allows"},
                source, version, {"year": year, "statement_due": statement_due.isoformat()}))
    return out


# -------------------------------------------------------------- persistence

def refresh(conn: Connection, entity_id: Optional[str] = None, *,
            locate_clauses: bool = True) -> Dict[str, Any]:
    """Recompute every lease's obligations into the obligation table (as
    lease_agent). A new obligation, or one whose due date moved (a confirmed
    amendment), is an audit event; an unchanged one is not. Idempotent."""
    leases = conn.execute(text("""
        SELECT l.id, l.clinic_id, k.entity_id, k.region_id, d.name, d.notice_address
          FROM lease l JOIN clinic k ON k.id = l.clinic_id JOIN landlord d ON d.id = l.landlord_id
         WHERE l.status = 'active' AND (CAST(:e AS text) IS NULL OR k.entity_id = :e)
         ORDER BY l.id
    """), {"e": entity_id}).mappings().all()
    agent = load_actor(conn, AGENT)
    found, changed, skipped = 0, [], {}
    for lease in leases:
        terms, source = lease_terms(conn, lease["id"])
        if not terms:
            skipped[lease["id"]] = "no confirmed lease_version and no generated terms"
            continue
        locate = _locator(conn, lease["id"]) if locate_clauses else None
        for ob in compute(lease["id"], terms, source, locate=locate,
                          landlord={"name": lease["name"],
                                    "notice_address": lease["notice_address"]}):
            found += 1
            before = conn.execute(text(
                "SELECT id, due_date FROM obligation WHERE lease_id = :l AND key = :k"),
                {"l": ob.lease_id, "k": ob.key}).mappings().first()
            row_id = conn.execute(text("""
                INSERT INTO obligation (lease_id, clinic_id, entity_id, region_id, kind, key,
                                        due_date, action, citation, source, lease_version_id,
                                        details)
                VALUES (:lease, :clinic, :entity, :region, :kind, :key, :due, :action,
                        CAST(:citation AS jsonb), :source, :version, CAST(:details AS jsonb))
                ON CONFLICT (lease_id, key) DO UPDATE SET
                    due_date = EXCLUDED.due_date, action = EXCLUDED.action,
                    citation = EXCLUDED.citation, source = EXCLUDED.source,
                    lease_version_id = EXCLUDED.lease_version_id, details = EXCLUDED.details,
                    computed_at = now()
                RETURNING id
            """), {"lease": ob.lease_id, "clinic": lease["clinic_id"],
                   "entity": lease["entity_id"], "region": lease["region_id"], "kind": ob.kind,
                   "key": ob.key, "due": ob.due_date, "action": ob.action,
                   "citation": _json(ob.citation), "source": ob.source,
                   "version": ob.lease_version_id, "details": _json(ob.details)}).scalar_one()
            if before is None or before["due_date"] != ob.due_date:
                changed.append(row_id)
                append_event(conn, actor_id=agent.id, action="compute", subject_type=SUBJECT,
                             subject_id=row_id,
                             diff={"from": before["due_date"].isoformat() if before else None,
                                   "to": ob.due_date.isoformat()},
                             evidence={"lease_id": ob.lease_id, "kind": ob.kind, "key": ob.key,
                                       "source": ob.source, "citation": ob.citation})
    return {"obligations": found, "new_or_moved": changed, "skipped": skipped}


def create_alerts(conn: Connection, today: date, entity_id: Optional[str] = None) -> List[int]:
    """Open the OBLIGATION work items due on `today` (90/60/30 business days
    before each due date), routed to the clinic's region and proposed by
    agent:obligations. Returns the ids of items this call created."""
    rows = conn.execute(text("""
        SELECT o.*, r.manager_id FROM obligation o LEFT JOIN region r ON r.id = o.region_id
         WHERE o.due_date >= :today AND (CAST(:e AS text) IS NULL OR o.entity_id = :e)
         ORDER BY o.due_date, o.id
    """), {"today": today, "e": entity_id}).mappings().all()
    agent = load_actor(conn, AGENT)
    created = []
    for ob in rows:
        n = threshold_for(today, ob["due_date"])
        if n is None:
            continue
        subject = "%d:%s:%dbd" % (ob["id"], ob["due_date"].isoformat(), n)
        days_left = (ob["due_date"] - today).days
        item = create_item(
            conn, agent, kind=ITEM_KIND, subject_type=SUBJECT, subject_id=subject,
            title="%s: %s due %s (%d business days)" % (
                ob["clinic_id"], ob["kind"].replace("_", " "), ob["due_date"].isoformat(), n),
            entity_id=ob["entity_id"], region_id=ob["region_id"], clinic_id=ob["clinic_id"],
            evidence={"obligation_id": ob["id"]})
        if item["state"] != "NEW":
            continue
        transition(conn, agent, item["id"], "propose", reason=ob["action"], patch={
            "proposal": "act",
            "evidence": {"obligation_id": ob["id"], "lease_id": ob["lease_id"],
                         "kind": ob["kind"], "key": ob["key"],
                         "due_date": ob["due_date"].isoformat(), "threshold_business_days": n,
                         "alert_date": business_days_before(ob["due_date"], n).isoformat(),
                         "calendar_days_left": days_left, "action": ob["action"],
                         "citation": ob["citation"], "source": ob["source"],
                         "routed_to": ob["manager_id"],
                         "decision": "approve when acted on; reject with the reason if not"}})
        created.append(item["id"])
    return created


def due_within(conn: Connection, today: date, within_days: int,
               where: Iterable[str] = (), params: Optional[Mapping] = None) -> List[Dict]:
    """Obligations due from today through today + within_days, soonest
    first, each with its alert items."""
    clauses = ["o.due_date BETWEEN :today AND :until", *where]
    rows = conn.execute(text("""
        SELECT o.* FROM obligation o WHERE %s ORDER BY o.due_date, o.lease_id, o.key
    """ % " AND ".join(clauses)), dict(params or {}, today=today,
                                     until=today + timedelta(days=within_days))).mappings().all()
    out = []
    for r in rows:
        alerts = conn.execute(text("""
            SELECT id, state, title, proposal, reason, updated_at FROM work_item
             WHERE kind = :k AND subject_type = :st AND subject_id LIKE :prefix ORDER BY id
        """), {"k": ITEM_KIND, "st": SUBJECT, "prefix": "%d:%%" % r["id"]}).mappings().all()
        out.append(dict(r, alerts=[dict(a) for a in alerts],
                        alert_dates={str(n): d.isoformat()
                                     for n, d in alert_dates(r["due_date"]).items()}))
    return out


# ------------------------------------------------------------------ helpers

def _locator(conn: Connection, lease_id: str):
    """locate(quote) -> (page, document_id) in the stored lease PDF, reading
    the PDF at most once; (None, None) when it is not available."""
    cache: Dict[str, Any] = {}

    def locate(quote: str):
        if "doc" not in cache:
            try:
                from ..jobs.lease_versions import load_lease_document

                cache["doc_id"], cache["doc"] = load_lease_document(conn, lease_id)
            except Exception:  # noqa: BLE001 - no store or unreadable: pages stay unknown
                cache["doc_id"], cache["doc"] = None, None
        if cache["doc"] is None:
            return None, None
        from ..docs.citations import locate as find

        hit = find(cache["doc"], quote)
        return (hit.page, cache["doc_id"]) if hit else (None, None)

    return locate


def _date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _int(term: Optional[Term]) -> int:
    try:
        return int(float(term.value)) if term is not None else 0
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _json(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, default=str)
