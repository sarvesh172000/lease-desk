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
    Without: a cache-only client, if there is any cache to read at all.

    The cache is the one every other caller uses (settings' llm_cache_dir,
    LEASEDESK_LLM_CACHE_DIR) plus the repository's committed answers
    (client.REPLAY_DIR), so the demo's leases are read by the abstraction
    agent with no key. LEASEDESK_LLM_CACHE names one directory and nothing
    else: the suite and the chaos harness point it at an empty one to keep the
    generator path deterministic and offline."""
    from ..llm.cache import ResponseCache
    from ..llm.client import LLM, REPLAY_DIR, _default_cache_dir

    only = os.environ.get("LEASEDESK_LLM_CACHE")
    root, replay = (Path(only), None) if only else (Path(_default_cache_dir()), REPLAY_DIR)
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        # The same timeout and SDK retries LLM() uses when it builds its own.
        provider = anthropic.Anthropic(timeout=120.0, max_retries=3)
        return LLM(cache=ResponseCache(root, replay=replay), client=guard_client(provider))
    # Checked before building the cache, which creates its own directory.
    if not any(d is not None and d.is_dir() for d in (root, replay)):
        return None
    return LLM(cache=ResponseCache(root, replay=replay), client=_CacheOnlyClient())


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
    versions: Dict[str, int]              # lease_id -> terminal confirmed lease_version id
    waiting: Dict[str, str]               # lease_id -> why it cannot be checked yet
    version_chains: Dict[str, Tuple[int, ...]] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Names every ordered standing version chain; a re-check is due when it changes."""
        chains = self.version_chains or {
            lease_id: (version_id,) for lease_id, version_id in self.versions.items()
        }
        if not chains:
            return "none"
        return json.dumps(
            {lease_id: list(chain) for lease_id, chain in sorted(chains.items())},
            separators=(",", ":"),
        )


# Item states in which a confirmation stands. Approving sets confirmed_by;
# an approved item pulled back (hold) leaves the stamp on the row as history,
# but the version is not confirmed again until it is approved again.
CONFIRMED_STATES = frozenset({"APPROVED", "POSTED", "CLOSED"})
POSTED_MODIFICATION_STATES = frozenset({"POSTED"})


def is_confirmed(confirmed_by: Optional[str], item_state: Optional[str],
                 item_kind: Optional[str] = None) -> bool:
    if confirmed_by is None:
        return False
    standing = POSTED_MODIFICATION_STATES if item_kind == "LEASE_MODIFICATION" \
        else CONFIRMED_STATES
    return item_state is None or item_state in standing


def confirmed_rules(conn: Connection, entity_id: str, *, as_of: date) -> ConfirmedRules:
    """Rules from the latest standing version effective for ``as_of``.

    The date is required so historical checking cannot silently use today's
    latest version. An unconfirmed later draft never hides the last confirmed
    version. A modification becomes standing only after gateway posting and
    starts at its own ``effective_from`` date.
    """
    from ..engine.charges import LeaseRule, Proof
    from ..engine.from_datagen import PROOF_TEMPLATES

    rows = conn.execute(text("""
        SELECT l.id, l.clinic_id, k.suite, v.id AS version_id, v.version,
               v.effective_from, v.confirmed_by, w.id AS item_id, w.state AS item_state,
               w.kind AS item_kind,
               CASE WHEN w.kind = :modification THEN (
                   SELECT proposed.diff->'set'->'evidence'->'changed_terms'
                     FROM audit_event proposed
                    WHERE proposed.subject_type = 'work_item'
                      AND proposed.subject_id = w.id::text
                      AND proposed.action = 'propose' AND proposed.allowed
                      AND proposed.actor_id = 'agent:investigation'
                    ORDER BY proposed.seq DESC LIMIT 1
               ) END AS changed_terms
          FROM lease l
          JOIN clinic k ON k.id = l.clinic_id
          LEFT JOIN lease_version v ON v.lease_id = l.id
          LEFT JOIN LATERAL (
              SELECT wi.id, wi.state, wi.kind FROM work_item wi
               WHERE wi.subject_type = :st AND wi.subject_id = v.id::text
                 AND wi.kind IN (:abstraction, :modification)
               ORDER BY wi.id DESC LIMIT 1
          ) w ON true
         WHERE k.entity_id = :e
         ORDER BY l.id, v.version
    """), {"e": entity_id, "st": SUBJECT, "abstraction": ITEM_KIND,
             "modification": "LEASE_MODIFICATION"}).mappings().all()
    by_lease: Dict[str, List[Mapping[str, Any]]] = {}
    for row in rows:
        by_lease.setdefault(row["id"], []).append(row)

    chosen: Dict[str, Mapping[str, Any]] = {}
    standing_by_lease: Dict[str, List[Mapping[str, Any]]] = {}
    latest: Dict[str, Optional[Mapping[str, Any]]] = {}
    for lease_id, candidates in by_lease.items():
        versions = [r for r in candidates if r["version_id"] is not None]
        applicable = [r for r in versions if r["effective_from"] <= as_of]
        latest[lease_id] = max(
            applicable or versions,
            key=lambda r: (r["effective_from"], r["version"]),
            default=None,
        )
        standing = sorted(
            (r for r in applicable
             if is_confirmed(r["confirmed_by"], r["item_state"], r["item_kind"])),
            key=lambda r: (r["effective_from"], r["version"]),
        )
        if standing:
            foundation = min(applicable, key=lambda r: r["version"])
            chain = [foundation] + [
                candidate for candidate in standing
                if candidate["version_id"] != foundation["version_id"]
            ]
            standing_by_lease[lease_id] = sorted(
                chain, key=lambda r: (r["effective_from"], r["version"]))
            chosen[lease_id] = standing[-1]

    confirmed = [r["version_id"] for chain in standing_by_lease.values() for r in chain]
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
    for lease_id in by_lease:
        row = chosen.get(lease_id)
        if row is None:
            draft = latest.get(lease_id)
            if draft is None:
                out.waiting[lease_id] = (
                    "no lease_version yet: the abstraction step has not drafted it")
            elif draft["effective_from"] > as_of:
                out.waiting[lease_id] = "no lease_version is effective by %s" % as_of
            else:
                out.waiting[lease_id] = (
                    "lease_version %d is not confirmed (work item %s is %s); a person "
                    "confirms it by approving that item" % (
                        draft["version_id"], draft["item_id"] or "-",
                        draft["item_state"] or "missing"))
            continue
        t = terms.get(row["version_id"], {})
        missing = [f for f in RULE_FIELDS if t.get(f, (None,))[0] in (None, "")]
        try:
            if missing:
                raise ValueError("missing %s" % ", ".join(missing))
            commencement, end, steps = _composed_rent_steps(
                standing_by_lease[lease_id], terms)
            psf = float(t["cam_estimate_psf_annual"][0])
            rsf = float(t["rentable_sf"][0])
        except (KeyError, TypeError, ValueError) as exc:
            out.waiting[lease_id] = "confirmed lease_version %d cannot be checked against: %s" % (
                row["version_id"], exc)
            continue
        proof = {}
        for key, name in PROOF_FIELD.items():
            section = PROOF_TEMPLATES[key][0]
            quote = t.get(name, (None, None))[1]
            if quote:
                proof[key] = Proof(section, quote)
        section, template = PROOF_TEMPLATES["premises"]
        proof["premises"] = Proof(section, template.format(suite=row["suite"]))
        proof["payment_timing"] = Proof(*PROOF_TEMPLATES["payment_timing"])
        out.rules[lease_id] = LeaseRule(
            lease_id=lease_id, clinic_id=row["clinic_id"], suite=row["suite"],
            commencement=commencement, expiration=end, steps=steps,
            cam_estimate_monthly=round(rsf * psf / 12, 2), cam_estimate_psf_annual=psf,
            proof=proof)
        out.versions[lease_id] = row["version_id"]
        out.version_chains[lease_id] = tuple(
            version["version_id"] for version in standing_by_lease[lease_id]
        )
    return out


def _composed_rent_steps(chain: List[Mapping[str, Any]],
                         terms: Mapping[int, Mapping[str, Any]]):
    """Compose posted amendment deltas without resetting unchanged rent.

    Every version stores a full term snapshot for audit and display. Only the
    fields named by its immutable ``changed_terms`` event alter the standing
    contract. Regenerating the current rent regime from its original anchor
    preserves anniversary boundaries for extension-only amendments.
    """
    from ..agents.abstraction import percent_unit_problem
    from ..engine.charges import RentStep

    base = min(chain, key=lambda row: row["version"])
    base_terms = terms[base["version_id"]]
    commencement = _date(base_terms["commencement"][0])
    end = _date(base_terms["expiration"][0])
    if commencement is None or end is None or end < commencement:
        raise ValueError("unreadable term dates")
    regime_start = commencement
    regime_rent = float(base_terms["base_rent_monthly"][0])
    kind = str(base_terms["escalation_kind"][0])
    amount = float(base_terms["escalation_amount"][0])
    _validate_escalation(kind, amount, percent_unit_problem)
    steps = rent_steps(regime_start, end, regime_rent, kind, amount)

    amendments = sorted(
        (row for row in chain if row["version_id"] != base["version_id"]),
        key=lambda row: (row["effective_from"], row["version"]),
    )
    for row in amendments:
        snapshot = terms[row["version_id"]]
        changed = _changed_terms(row)
        effective = row["effective_from"]
        new_end = (_date(snapshot["expiration"][0])
                   if "expiration" in changed else end)
        if new_end is None or new_end < effective:
            raise ValueError("version %d has an unreadable expiration" % row["version"])
        rent_changed = bool(changed & {
            "base_rent_monthly", "escalation_kind", "escalation_amount",
        })
        if rent_changed:
            current_rent = _rent_on(steps, effective)
            if current_rent is None:
                raise ValueError("version %d starts outside the standing rent schedule"
                                 % row["version"])
            if "base_rent_monthly" in changed:
                regime_rent = float(snapshot["base_rent_monthly"][0])
            else:
                regime_rent = current_rent
            if "escalation_kind" in changed:
                kind = str(snapshot["escalation_kind"][0])
            if "escalation_amount" in changed:
                amount = float(snapshot["escalation_amount"][0])
            _validate_escalation(kind, amount, percent_unit_problem)
            regime_start = effective
            prefix = _rent_before(steps, effective, RentStep)
        else:
            prefix = _rent_before(steps, regime_start, RentStep)
        end = new_end
        steps = prefix + rent_steps(regime_start, end, regime_rent, kind, amount)
    return commencement, end, steps


def _changed_terms(row: Mapping[str, Any]) -> set[str]:
    raw = row.get("changed_terms")
    return set(raw) if isinstance(raw, Mapping) else set(RULE_FIELDS)


def _validate_escalation(kind: str, amount: float, validate) -> None:
    if kind not in ("fixed_percent", "fixed_step"):
        raise ValueError("escalation_kind %r" % kind)
    problem = validate(kind, amount)
    if problem:
        raise ValueError(problem)


def _rent_on(steps, when: date) -> Optional[float]:
    for step in steps:
        if step.start <= when <= step.end:
            return float(step.monthly_rent)
    return None


def _rent_before(steps, cutoff: date, rent_step):
    out = []
    for step in steps:
        if step.start >= cutoff:
            break
        stop = min(step.end, cutoff - timedelta(days=1))
        if step.start <= stop:
            out.append(rent_step(step.start, stop, step.monthly_rent))
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
