"""The month's abstraction step, and the confirmed rules the checker reads.

PHASE_1.md group 9: *Draft becomes lease_version 1. A regional manager
confirms it through transition(). Unconfirmed leases are never used by the
checker.* This module is both halves of that sentence on the platform side.

Drafting (`draft_versions`, the `abstraction` job, as `lease_agent`)
----------------------------------------------------------------------
For every lease of the entity that has no `lease_version` yet:

  1. Read the lease PDF from the content-addressed store
     (`source_document` id = md5('datagen.leases' | lease_id)).
  2. Get the 13 cited terms by one of two paths, and say which:

     ``abstraction:llm``        the real abstraction agent
                                (`agents/abstraction.abstract_lease`), when
                                ANTHROPIC_API_KEY is set or the LLM response
                                cache under `.cache/llm` already holds the
                                answer (a cold cache with no key never calls
                                out; it falls through to the generator).
     ``abstraction:generator``  the generated lease terms (what
                                `engine/from_datagen` also builds rules from),
                                each with the sentence the lease template
                                renders for it, then located in the real PDF
                                by the same citation check the agent's
                                quotes go through (`agents/abstraction.check`,
                                which calls `docs/citations.locate`).

     The path is the `agent_run.agent` and `prompt_id`; every `lease_term`
     points at that run through `extracted_by_run`. Nothing written by the
     generator path claims a model, a prompt version or a token.
  3. Write `lease_version` 1 (effective from the commencement it read) and one
     `lease_term` per field: value, page, bbox, quote, confidence. A quote the
     citation check cannot find on any page gets confidence 0, no page, no
     box, and a flag; a weak match keeps its (lower) score and is flagged.
     There is never a box that the page does not back.
  4. Replay the extracted rent over 2025's cash (`cross_check_history`) and
     add any disagreement to the flags, with both figures.
  5. Open one LEASE_ABSTRACTION work item on the version
     (`subject_type = 'lease_version'`), proposed `approve` by
     `agent:abstraction`, in the clinic's region, with every field and flag
     as evidence. A regional manager approving it (POST
     /api/items/{id}/actions/approve) confirms the version: transition()
     puts `confirms` in the event and the projection sets
     `confirmed_by`/`confirmed_at`.

Reading (`confirmed_rules`, the checking job)
---------------------------------------------
The checker's `LeaseRule`s are built from the *confirmed* version 1 terms in
the database, never from the generator. A lease with no confirmed version is
returned as waiting, with the reason, and its charges are not checked at all
(see `jobs/monthly.check_period`).

When the model cannot be read (C3)
----------------------------------
Provider calls on the LLM path go through the `llm` circuit breaker
(`work/breaker.py`); cached answers never reach it. A single failed call
falls back to the generator path, on record in the item's `path_note`. A
provider *outage* (the breaker is open) does not: the job raises
`ProviderUnavailable`, the worker holds it until the breaker next probes, and
whatever it drafted so far rolls back with it. A lease neither path can read
is never skipped in silence: it gets a LEASE_UNREADABLE work item, HELD for a
person, with the reason.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..records.ingest import stable_id
from ..work.breaker import guard_client, open_in_chain
from ..work.roles import load_actor
from ..work.transitions import create_item, transition
from .recovery import JobHeld

log = logging.getLogger(__name__)

ABSTRACTOR = "agent:abstraction"
ITEM_KIND = "LEASE_ABSTRACTION"
SUBJECT = "lease_version"
UNREADABLE_KIND = "LEASE_UNREADABLE"
LEASE_SOURCE = "datagen.leases"

PATH_LLM = "abstraction:llm"
PATH_GENERATOR = "abstraction:generator"
GENERATOR_PROMPT = "generator:datagen.leases"

# Fields the checker needs from a confirmed version to build a rule.
RULE_FIELDS = ("commencement", "expiration", "rentable_sf", "base_rent_monthly",
               "escalation_kind", "escalation_amount", "cam_estimate_psf_annual")

# Which clause of the lease form states each checked term. The sections are a
# fact about the lease template (the same numbering engine/from_datagen cites),
# not something read from a particular lease.
PROOF_FIELD = {"base_rent": "base_rent_monthly", "escalation": "escalation_amount",
               "cam_estimate": "cam_estimate_psf_annual"}


class AbstractionError(RuntimeError):
    """The step cannot run at all (for example, no abstraction agent actor)."""


class ProviderUnavailable(JobHeld):
    """The model provider is down (its circuit breaker is open): hold the job."""


# ---------------------------------------------------------------- data dir

def data_dir() -> Path:
    """Where `make seed` put the generated company; documents live under it.
    Resolved like the API resolves it (relative to the repository root)."""
    from ..api.deps import get_data_dir

    return get_data_dir()


def load_lease_document(conn: Connection, lease_id: str, root: Optional[Path] = None):
    """(source_document id, Document) for the lease PDF, or (id or None, None)."""
    from ..docs.pipeline import extract
    from ..docs.storage import LocalStorage

    doc_id = stable_id(LEASE_SOURCE, lease_id)
    sha = conn.execute(text("SELECT sha256 FROM source_document WHERE id = :id"),
                       {"id": doc_id}).scalar()
    if sha is None:
        return None, None
    sha = sha.strip()
    store = (root or data_dir()) / "documents"
    if not store.is_dir():
        return doc_id, None
    storage = LocalStorage(store)
    if not storage.exists(sha):
        return doc_id, None
    try:
        return doc_id, extract(storage.get(sha), sha256=sha)
    except Exception:  # noqa: BLE001 - PyMuPDF raises several types for a bad file
        log.warning("lease %s: stored document %s is not a readable PDF", lease_id, sha)
        return doc_id, None


# ------------------------------------------------------------ the LLM path

class CacheCold(RuntimeError):
    """No key and no cached answer: the LLM path is not available."""


class _CacheOnlyMessages:
    def parse(self, **_kwargs):
        raise CacheCold("the response cache has no answer and no ANTHROPIC_API_KEY is set")


class _CacheOnlyClient:
    """Stands in for the Anthropic client when there is no key: a cache hit
    never reaches it, a miss raises CacheCold instead of calling out."""
    messages = _CacheOnlyMessages()


def default_llm():
    """The LLM to try, or None when the LLM path cannot possibly run.

    With ANTHROPIC_API_KEY: the real client (cache first, as always), its
    provider calls behind the `llm` circuit breaker.
    Without: a cache-only client, if the cache directory exists at all."""
    from ..llm.cache import ResponseCache
    from ..llm.client import LLM

    cache_root = Path(os.environ.get("LEASEDESK_LLM_CACHE", ".cache/llm"))
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        # The same timeout and SDK retries LLM() uses when it builds its own.
        provider = anthropic.Anthropic(timeout=120.0, max_retries=3)
        return LLM(cache=ResponseCache(cache_root), client=guard_client(provider))
    if not cache_root.is_dir():
        return None
    return LLM(cache=ResponseCache(cache_root), client=_CacheOnlyClient())


def _is_cold(exc: BaseException) -> bool:
    while exc is not None:
        if isinstance(exc, CacheCold):
            return True
        exc = exc.__cause__
    return False


# ------------------------------------------------------ the generator path

def generator_terms(lease_id: str):
    """(LeaseTerms, Company) from the generator, or (None, company)."""
    from datagen.company import build_company
    from datagen.leases import build_leases

    company = build_company()
    for terms in build_leases(company):
        if terms.lease_id == lease_id:
            return terms, company
    return None, company


def generator_quotes(terms, company) -> Dict[str, Tuple[Any, str]]:
    """field -> (value, the sentence the lease template renders for it).

    The values are the generator's; the sentences are what datagen's lease
    template prints from those values. Whether the sentence really is on the
    page is not assumed here: `abstraction.check` locates each one."""
    from datagen.render_lease import _long, _option_phrase

    landlord = company.landlord(terms.landlord_id)
    share = company.pro_rata_for(terms.clinic_id) * 100
    esc = terms.escalation.describe()
    r = terms.renewal
    return {
        "commencement": (terms.commencement.isoformat(),
                         "shall commence on %s" % _long(terms.commencement)),
        "expiration": (terms.expiration.isoformat(),
                       "shall expire at 11:59 p.m. on %s" % _long(terms.expiration)),
        "rentable_sf": (float(terms.rsf), "The Premises are stipulated to contain "
                        "{:,} rentable square feet".format(terms.rsf)),
        "proportionate_share_pct": (round(share, 2),
                                    "Tenant’s Proportionate Share is %.2f%%, computed as "
                                    "the rentable area of the Premises" % share),
        "base_rent_monthly": (terms.base_rent_monthly, "The initial Monthly Base Rent is "
                              "${:,.2f} per month".format(terms.base_rent_monthly)),
        "escalation_kind": (terms.escalation.kind,
                            "the Monthly Base Rent shall increase by %s" % esc),
        "escalation_amount": (terms.escalation.amount,
                              "the Monthly Base Rent shall increase by %s" % esc),
        "cam_estimate_psf_annual": (terms.cam_estimate_psf_annual,
                                    "Landlord’s current estimate of Operating Expenses is "
                                    "$%.2f per rentable square foot per annum"
                                    % terms.cam_estimate_psf_annual),
        "security_deposit": (terms.security_deposit, "shall deposit with Landlord the sum of "
                             "${:,.2f} as a security deposit".format(terms.security_deposit)),
        "renewal_count": (float(r.count), "Tenant shall have %s to extend the Term"
                          % _option_phrase(r.count)),
        "renewal_years": (float(r.years), "each for an additional period of %d years" % r.years),
        "renewal_notice_days": (float(r.notice_days), "delivered to Landlord not less than %d "
                                "days prior to the then-current Expiration Date"
                                % r.notice_days),
        "authorized_representative": (landlord.authorized_rep, "Landlord designates %s as the "
                                      "sole representative authorized" % landlord.authorized_rep),
    }


def abstract_from_generator(document, lease_id: str):
    """The generator's terms as an `Abstraction`, every quote checked against
    the real PDF exactly as a model's quote would be. None if the generator
    has no such lease."""
    from ..agents.abstraction import AbstractedLease, check
    from ..docs.citations import locate

    terms, company = generator_terms(lease_id)
    if terms is None:
        return None
    raw = {}
    for name, (value, quote) in generator_quotes(terms, company).items():
        # The generator states no page. Claim the page the quote is found on,
        # so the check judges the quote and not a made-up page number; a quote
        # found nowhere claims page 1 and is reported uncited regardless.
        found = locate(document, quote) if document is not None else None
        raw[name] = {"value": value, "page": found.page if found else 1, "quote": quote}
    extracted = AbstractedLease.model_validate(dict(raw, uncertain=[]))
    if document is None:
        from ..docs.pipeline import Document
        document = Document(sha256=None, pages=[])
    return check(extracted, document, lease_id)


# --------------------------------------------------------------- drafting

@dataclass
class Draft:
    lease_id: str
    path: str
    abstraction: Any
    document_id: Optional[str]
    note: Optional[str] = None
    flags: List[str] = field(default_factory=list)
    run_id: Optional[int] = None


def abstract_one(conn: Connection, lease_id: str, *, root: Optional[Path] = None,
                 llm_factory: Callable[[], Any] = default_llm) -> Draft:
    """Read one lease by the best path available. A Draft whose abstraction
    is None if neither path can say anything about it (its `note` says why
    the LLM path did not)."""
    from ..agents.abstraction import abstract_lease

    doc_id, document = load_lease_document(conn, lease_id, root)
    flags: List[str] = []
    if document is None:
        flags.append("lease document not in the store: no field can be boxed")
    note = None
    llm = llm_factory() if document is not None else None
    if llm is not None:
        try:
            result = abstract_lease(document, llm, lease_id, source="%s.pdf" % lease_id)
            return Draft(lease_id, PATH_LLM, result, doc_id, flags=flags)
        except Exception as exc:  # noqa: BLE001 - any LLM failure falls through, on record
            outage = open_in_chain(exc)
            if outage is not None:
                raise ProviderUnavailable(
                    "model provider unavailable while reading %s (%s)" % (lease_id, outage),
                    delay=timedelta(seconds=max(outage.retry_in, 1.0))) from exc
            if _is_cold(exc):
                note = "LLM cache cold and no API key; read from the generator"
            else:
                note = "LLM path failed (%s: %s); read from the generator" % (
                    type(exc).__name__, str(exc)[:300])
                log.warning("lease %s: %s", lease_id, note)
    result = abstract_from_generator(document, lease_id)
    return Draft(lease_id, PATH_GENERATOR, result, doc_id, note=note, flags=flags)


def draft_versions(conn: Connection, entity_id: str, *, root: Optional[Path] = None,
                   llm_factory: Callable[[], Any] = default_llm,
                   history_until: Optional[date] = None) -> Dict[str, Any]:
    """Draft version 1 for every lease of the entity that has none, and open
    one LEASE_ABSTRACTION item per draft. Idempotent: a lease with any
    version is left alone."""
    actor = load_actor(conn, ABSTRACTOR)
    leases = conn.execute(text("""
        SELECT l.id, l.clinic_id, k.entity_id, k.region_id
          FROM lease l JOIN clinic k ON k.id = l.clinic_id
         WHERE k.entity_id = :e
           AND NOT EXISTS (SELECT 1 FROM lease_version v WHERE v.lease_id = l.id)
         ORDER BY l.id
    """), {"e": entity_id}).mappings().all()

    out: Dict[str, Any] = {"drafted": [], "paths": {}, "flagged_fields": 0, "unreadable": []}
    for lease in leases:
        # One drafter per lease: a second worker waits here, then finds the
        # version the first one wrote.
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                     {"k": "lease_version|%s" % lease["id"]})
        if conn.execute(text("SELECT 1 FROM lease_version WHERE lease_id = :l"),
                        {"l": lease["id"]}).first():
            continue
        draft = abstract_one(conn, lease["id"], root=root, llm_factory=llm_factory)
        commencement = (_date(_value(draft.abstraction, "commencement"))
                        if draft.abstraction is not None else None)
        if commencement is None:
            out["unreadable"].append(lease["id"])
            _route_unreadable(conn, actor, lease, draft)
            continue
        _cross_check(conn, draft, history_until)
        version_id, fields = _write_version(conn, draft, commencement)
        _open_item(conn, actor, lease, draft, version_id, fields)
        out["drafted"].append(lease["id"])
        out["paths"][lease["id"]] = draft.path
        out["flagged_fields"] += sum(1 for f in fields if f["status"] != "verified")
    out["versions"] = len(out["drafted"])
    return out


def _value(abstraction, name):
    try:
        return abstraction.value(name)
    except KeyError:
        return None


def _date(value) -> Optional[date]:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _cross_check(conn: Connection, draft: Draft, until: Optional[date]) -> None:
    """The extracted rent against what was actually paid in the history."""
    from ..agents.abstraction import cross_check_history

    rows = conn.execute(text("""
        SELECT to_char(period, 'YYYY-MM') AS month, sum(amount) AS paid
          FROM payment
         WHERE lease_id = :l AND charge_type = 'base_rent'
           AND (CAST(:until AS date) IS NULL OR period < :until)
         GROUP BY period ORDER BY period
    """), {"l": draft.lease_id, "until": until}).all()
    paid = {r.month: float(r.paid) for r in rows}
    try:
        cross_check_history(draft.abstraction, paid)
    except (TypeError, ValueError, AttributeError) as exc:
        draft.flags.append("history cross-check could not run: %s" % exc)


def _field_rows(draft: Draft) -> List[Dict[str, Any]]:
    rows = []
    for f in draft.abstraction.fields:
        c = f.citation
        rows.append({
            "field": f.name,
            "value": _jsonable(f.value),
            "page": c.page if c else None,
            "bbox": [round(float(v), 2) for v in c.box] if c else None,
            "quote": f.quote or None,
            # The citation score is the field's confidence: 1.0 for an exact
            # match, lower for a partial one, 0 for a quote found nowhere.
            "confidence": round(float(c.score), 3) if c else 0.0,
            "status": f.status,
        })
    return rows


def _jsonable(value):
    if isinstance(value, date):
        return value.isoformat()
    return value


def _write_version(conn: Connection, draft: Draft, commencement: date):
    meta = getattr(draft.abstraction, "meta", None)
    if draft.path == PATH_LLM and meta is not None:
        prompt_id, _, prompt_version = meta.prompt_ref.partition("@")
        run = dict(agent=PATH_LLM, prompt_id=prompt_id, prompt_version=prompt_version or None,
                   model=meta.model, input_tokens=meta.input_tokens,
                   output_tokens=meta.output_tokens, cost_usd=meta.cost_usd,
                   cache_hit=meta.cache_hit)
    else:
        run = dict(agent=PATH_GENERATOR, prompt_id=GENERATOR_PROMPT, prompt_version=None,
                   model=None, input_tokens=0, output_tokens=0, cost_usd=0, cache_hit=False)
    run_id = conn.execute(text("""
        INSERT INTO agent_run (agent, prompt_id, prompt_version, model, status, input_tokens,
                               output_tokens, cost_usd, cache_hit, finished_at)
        VALUES (:agent, :prompt_id, :prompt_version, :model, 'succeeded', :input_tokens,
                :output_tokens, :cost_usd, :cache_hit, now())
        RETURNING id
    """), run).scalar_one()
    version_id = conn.execute(text("""
        INSERT INTO lease_version (lease_id, version, effective_from)
        VALUES (:l, 1, :eff) RETURNING id
    """), {"l": draft.lease_id, "eff": commencement}).scalar_one()

    fields = _field_rows(draft)
    for f in fields:
        conn.execute(text("""
            INSERT INTO lease_term (lease_version_id, field, value, document_id, page, bbox,
                                    quote, confidence, extracted_by_run)
            VALUES (:v, :field, CAST(:value AS jsonb), :doc, :page,
                    CAST(:bbox AS double precision[]), :quote, :confidence, :run)
        """), {"v": version_id, "field": f["field"], "value": json.dumps(f["value"]),
               "doc": draft.document_id if f["page"] is not None else None,
               "page": f["page"], "bbox": f["bbox"], "quote": f["quote"],
               "confidence": f["confidence"], "run": run_id})
    draft.run_id = run_id
    return version_id, fields


def _open_item(conn: Connection, actor, lease: Mapping, draft: Draft, version_id: int,
               fields: List[Dict[str, Any]]) -> None:
    low = [f["field"] for f in fields if f["status"] != "verified"]
    flags = list(draft.flags) + list(draft.abstraction.flags)
    source = "the abstraction agent" if draft.path == PATH_LLM else "the generated lease terms"
    reason = "%s v1 read from %s: %d of %d fields boxed on the lease%s%s. Confirm before " \
             "the checker uses it." % (
                 lease["id"], source, len(fields) - len(low), len(fields),
                 "; low confidence: %s" % ", ".join(low) if low else "",
                 "; %d flag(s)" % len(flags) if flags else "")
    evidence = {
        "lease_id": lease["id"],
        "lease_version_id": version_id,
        "version": 1,
        "path": draft.path,
        "path_note": draft.note,
        "agent_run_id": draft.run_id,
        "document_id": draft.document_id,
        "confidence": draft.abstraction.confidence,
        "fields": fields,
        "low_confidence": low,
        "flags": flags,
        "history_disagreements": [
            {"period": d.period, "schedule_says": d.schedule_says, "cash_says": d.cash_says}
            for d in draft.abstraction.disagreements],
    }
    item = create_item(conn, actor, kind=ITEM_KIND, subject_type=SUBJECT, subject_id=version_id,
                       entity_id=lease["entity_id"], region_id=lease["region_id"],
                       clinic_id=lease["clinic_id"],
                       title="%s v1 abstraction: %d fields, %d low confidence" % (
                           lease["id"], len(fields), len(low)))
    transition(conn, actor, item["id"], "propose", reason=reason,
               patch={"proposal": "approve", "reason": reason, "evidence": evidence})


def _route_unreadable(conn: Connection, actor, lease: Mapping, draft: Draft) -> None:
    """A lease no path could read goes to a person, HELD with the reason,
    never past them. Idempotent: an item already opened is left as it is."""
    if draft.abstraction is None:
        why = "neither the abstraction agent nor the generated terms could read it"
    else:
        why = "no commencement date could be read from it (%s)" % (draft.note or draft.path)
    reason = "%s could not be read: %s. A person must abstract it before any of its " \
             "charges are checked." % (lease["id"], why)
    item = create_item(conn, actor, kind=UNREADABLE_KIND, subject_type="lease",
                       subject_id=lease["id"], entity_id=lease["entity_id"],
                       region_id=lease["region_id"], clinic_id=lease["clinic_id"],
                       title="%s could not be read" % lease["id"])
    if item["state"] != "NEW":
        return
    transition(conn, actor, item["id"], "hold", reason=reason, patch={
        "proposal": "hold", "reason": reason,
        "evidence": {"lease_id": lease["id"], "why": why, "document_id": draft.document_id,
                     "path_note": draft.note, "flags": list(draft.flags)}})


# ------------------------------------------------- confirmed rules (checker)

@dataclass
class ConfirmedRules:
    rules: Dict[str, Any]                 # lease_id -> LeaseRule
    versions: Dict[str, int]              # lease_id -> confirmed lease_version id
    waiting: Dict[str, str]               # lease_id -> why it cannot be checked yet

    @property
    def fingerprint(self) -> str:
        """Names the set of confirmed versions; a re-check is due when it changes."""
        return ",".join(str(v) for _, v in sorted(self.versions.items())) or "none"


# Item states in which a confirmation stands. Approving sets confirmed_by;
# an approved item pulled back (hold) leaves the stamp on the row as history,
# but the version is not confirmed again until it is approved again.
CONFIRMED_STATES = frozenset({"APPROVED", "POSTED", "CLOSED"})


def is_confirmed(confirmed_by: Optional[str], item_state: Optional[str]) -> bool:
    return confirmed_by is not None and (item_state is None or item_state in CONFIRMED_STATES)


def confirmed_rules(conn: Connection, entity_id: str) -> ConfirmedRules:
    """A `LeaseRule` for every lease of the entity whose version 1 a person
    has confirmed, built from that version's stored terms. Every other lease
    is waiting, with the reason."""
    from ..engine.charges import LeaseRule, Proof
    from ..engine.from_datagen import PROOF_TEMPLATES

    leases = conn.execute(text("""
        SELECT l.id, l.clinic_id, k.suite, v.id AS version_id, v.confirmed_by,
               w.id AS item_id, w.state AS item_state
          FROM lease l
          JOIN clinic k ON k.id = l.clinic_id
          LEFT JOIN lease_version v ON v.lease_id = l.id AND v.version = 1
          LEFT JOIN work_item w ON w.kind = :kind AND w.subject_type = :st
                               AND w.subject_id = v.id::text
         WHERE k.entity_id = :e
         ORDER BY l.id
    """), {"e": entity_id, "kind": ITEM_KIND, "st": SUBJECT}).mappings().all()
    confirmed = [r["version_id"] for r in leases
                 if is_confirmed(r["confirmed_by"], r["item_state"])]
    terms: Dict[int, Dict[str, Any]] = {}
    if confirmed:
        for t in conn.execute(text("""
            SELECT lease_version_id, field, value, quote, page FROM lease_term
             WHERE lease_version_id = ANY (CAST(:ids AS bigint[]))
        """), {"ids": confirmed}).mappings():
            value = t["value"]
            if isinstance(value, dict) and "value" in value:
                value = value["value"]
            terms.setdefault(t["lease_version_id"], {})[t["field"]] = (value, t["quote"])

    out = ConfirmedRules({}, {}, {})
    for r in leases:
        lease_id = r["id"]
        if r["version_id"] is None:
            out.waiting[lease_id] = "no lease_version yet: the abstraction step has not drafted it"
            continue
        if not is_confirmed(r["confirmed_by"], r["item_state"]):
            out.waiting[lease_id] = (
                "lease_version %d is not confirmed (work item %s is %s); a regional manager "
                "confirms it by approving that item" % (
                    r["version_id"], r["item_id"] or "-", r["item_state"] or "missing"))
            continue
        t = terms.get(r["version_id"], {})
        missing = [f for f in RULE_FIELDS if t.get(f, (None,))[0] in (None, "")]
        try:
            if missing:
                raise ValueError("missing %s" % ", ".join(missing))
            start = _date(t["commencement"][0])
            end = _date(t["expiration"][0])
            if start is None or end is None or end < start:
                raise ValueError("unreadable term dates")
            rent = float(t["base_rent_monthly"][0])
            kind = str(t["escalation_kind"][0])
            amount = float(t["escalation_amount"][0])
            psf = float(t["cam_estimate_psf_annual"][0])
            rsf = float(t["rentable_sf"][0])
            if kind not in ("fixed_percent", "fixed_step"):
                raise ValueError("escalation_kind %r" % kind)
        except (TypeError, ValueError) as exc:
            out.waiting[lease_id] = "confirmed lease_version %d cannot be checked against: %s" % (
                r["version_id"], exc)
            continue
        proof = {}
        for key, name in PROOF_FIELD.items():
            section = PROOF_TEMPLATES[key][0]
            quote = t.get(name, (None, None))[1]
            if quote:
                proof[key] = Proof(section, quote)
        section, template = PROOF_TEMPLATES["premises"]
        proof["premises"] = Proof(section, template.format(suite=r["suite"]))
        proof["payment_timing"] = Proof(*PROOF_TEMPLATES["payment_timing"])
        out.rules[lease_id] = LeaseRule(
            lease_id=lease_id, clinic_id=r["clinic_id"], suite=r["suite"],
            commencement=start, expiration=end, steps=rent_steps(start, end, rent, kind, amount),
            cam_estimate_monthly=round(rsf * psf / 12, 2), cam_estimate_psf_annual=psf,
            proof=proof)
        out.versions[lease_id] = r["version_id"]
    return out


def rent_steps(start: date, end: date, rent: float, kind: str, amount: float) -> List:
    """One step per lease year from commencement, the last cut at expiration;
    each year's rent is the previous year's stated (rounded) rent escalated,
    the way the lease's Section 3.3 and the generator both compute it."""
    from ..engine.charges import RentStep

    steps = []
    while start <= end:
        stop = min(_add_months(start, 12) - timedelta(days=1), end)
        rent = round(rent, 2)
        steps.append(RentStep(start, stop, rent))
        start = stop + timedelta(days=1)
        rent = rent * (1 + amount) if kind == "fixed_percent" else rent + amount
    return steps


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = (nxt - timedelta(days=1)).day
    return date(year, month, min(d.day, last))
