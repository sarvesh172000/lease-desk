"""The "Why?" agent: why is this item where it is, answered from the record.

It has five fixed query tools and nothing else. It cannot run SQL of its
own choosing, call another agent, or write:

    timeline_for(subject)          every event about one subject, oldest first
    decisions_by_policy(ref)       every decision that cited a policy, and the policy
    sources_for(item)              the sources the item weighed, each with its rank
    denied_attempts(subject|actor) refusals on record (allowed = false)
    as_known_on(lease, date)       the lease terms we had confirmed on a date

`why()` picks the tools from the item (and, optionally, words in the
question), runs them, and answers in two or three sentences together with
every row it used, so a reader can check each claim against a row.

The answer is a deterministic template by default: offline, reproducible,
tested. When ANTHROPIC_API_KEY is set (or a client is handed in), the same
rows may be re-phrased by a model through the teammate's LLM client
(app/llm). The model sees the tool rows only, fenced as untrusted data under
a fixed system prompt; never the question, never the item row, never the
template. Any failure falls back to the template.

Read-only by construction: the tools are SELECTs, and `read_only()` opens a
`SET TRANSACTION READ ONLY` transaction, so even a bug cannot write. The API
runs it as `lease_reader`, the auditor's role, which holds no write grant.

Bitemporal terms (PHASE_2 group 5) are not built yet. `as_known_on` answers
from lease_version and its confirmed_at: the latest version confirmed on or
before the date, with its terms, and says so in its rows.
"""

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ..agents.trust import LANDLORD_INVOICE, ORIGINAL_LEASE, RANK_NAMES

TOOLS = ("timeline_for", "decisions_by_policy", "sources_for", "denied_attempts", "as_known_on")

PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPT_ID = "why_answer"

BITEMPORAL_NOTE = ("bitemporal terms are not built; answered from lease versions and the time "
                   "each was confirmed")

_EVENT_COLUMNS = """
    e.seq, e.at, e.actor_id, a.name AS actor_name, a.role AS actor_role, e.action,
    e.subject_type, e.subject_id, e.allowed, e.reason, e.diff, e.evidence,
    e.policy_ref, e.model_ref, e.hash
"""


class WhyError(LookupError):
    """The subject of the question is not on record."""


@dataclass
class WhyAnswer:
    answer: str
    rows: List[Dict[str, Any]]
    tools_used: List[str]
    path: str = "template"          # or "llm:<model_ref>"
    item_id: Optional[int] = None
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"answer": self.answer, "rows": self.rows, "tools_used": self.tools_used,
                "path": self.path, "item_id": self.item_id, "notes": self.notes}


# ------------------------------------------------------------- read only

@contextmanager
def read_only(eng: Engine) -> Iterator[Connection]:
    """A connection inside a READ ONLY transaction, rolled back at the end."""
    with eng.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            yield conn
        finally:
            tx.rollback()


# ------------------------------------------------------------------ tools

def timeline_for(conn: Connection, subject_type: str, subject_id: Any) -> List[Dict[str, Any]]:
    """Every event about one subject, oldest first, with who acted."""
    rows = conn.execute(text("""
        SELECT %s FROM audit_event e LEFT JOIN actor a ON a.id = e.actor_id
         WHERE e.subject_type = :t AND e.subject_id = :i ORDER BY e.seq
    """ % _EVENT_COLUMNS), {"t": subject_type, "i": str(subject_id)}).mappings().all()
    return [_event_row("timeline_for", r) for r in rows]


def decisions_by_policy(conn: Connection, policy_ref: str) -> List[Dict[str, Any]]:
    """The policy (each matching version) and every decision that cited it.

    A ref matches a policy by id, by name, or by `name@vN`; an event matches
    when its policy_ref is the ref or starts with `ref@`."""
    ref = str(policy_ref)
    policies = conn.execute(text("""
        SELECT id, name, version, status, effective_from, effective_to, rule
          FROM policy
         WHERE id::text = :r OR name = :r OR name || '@v' || version = :r
         ORDER BY name, version
    """), {"r": ref}).mappings().all()
    events = conn.execute(text("""
        SELECT %s FROM audit_event e LEFT JOIN actor a ON a.id = e.actor_id
         WHERE e.policy_ref = :r OR e.policy_ref LIKE :prefix
         ORDER BY e.seq
    """ % _EVENT_COLUMNS), {"r": ref, "prefix": _like_prefix(ref) + "@%"}).mappings().all()
    out = [dict(_plain(dict(p)), tool="decisions_by_policy", kind="policy") for p in policies]
    return out + [_event_row("decisions_by_policy", r) for r in events]


def sources_for(conn: Connection, item: Mapping) -> List[Dict[str, Any]]:
    """The sources an item weighed, highest authority first.

    When the resolver recorded them (evidence.sources, chunk B1) those are
    the answer, ranked; a charge check also keeps the two it was checked
    against, read fresh from the database: the landlord's invoice line, and
    the confirmed lease version the checker read, with the clause it cited."""
    evidence = item.get("evidence") if isinstance(item.get("evidence"), Mapping) else {}
    recorded = evidence.get("sources")
    if isinstance(recorded, list) and recorded:
        rows = []
        for i, s in enumerate(recorded):
            row = dict(_plain(s)) if isinstance(s, Mapping) else {"claim": _plain(s)}
            rank = _first(row, "trust_rank", "rank")
            row.setdefault("rank_name", RANK_NAMES.get(rank) if isinstance(rank, int) else None)
            row.update(tool="sources_for", recorded=True, order=i)
            rows.append(row)
        rows.sort(key=lambda r: (_rank_key(_first(r, "trust_rank", "rank")), r["order"]))
        return _checked_against(conn, item, evidence) + rows
    return _checked_against(conn, item, evidence)


def _checked_against(conn: Connection, item: Mapping, evidence: Mapping) -> List[Dict[str, Any]]:
    """A charge check's invoice line and confirmed lease version, if it names them."""
    rows = []
    charge_id = evidence.get("charge_id") or (
        item.get("subject_id") if item.get("subject_type") == "landlord_charge" else None)
    version_id = evidence.get("lease_version_id")
    if version_id is not None:
        v = conn.execute(text("""
            SELECT id, lease_id, version, effective_from, confirmed_by, confirmed_at
              FROM lease_version WHERE id = :id
        """), {"id": _int(version_id)}).mappings().first()
        proof = evidence.get("proof") if isinstance(evidence.get("proof"), Mapping) else {}
        rows.append({
            "tool": "sources_for", "recorded": False, "source": "lease_version",
            "rank": ORIGINAL_LEASE, "rank_name": RANK_NAMES[ORIGINAL_LEASE],
            "claims": _amount(evidence.get("supported")), "claim_label": "supported",
            "lease_id": (v or {}).get("lease_id") or evidence.get("lease_id"),
            "lease_version_id": _int(version_id), "version": (v or {}).get("version"),
            "confirmed_by": (v or {}).get("confirmed_by"),
            "confirmed_at": _plain((v or {}).get("confirmed_at")),
            "section": proof.get("section"), "page": proof.get("page"),
            "quote": proof.get("quote"), "box": _plain(proof.get("box")),
        })
    if charge_id:
        c = conn.execute(text("""
            SELECT c.id, c.invoice_id, c.charge_type, c.description, c.amount, c.page,
                   c.period, d.sha256
              FROM landlord_charge c LEFT JOIN source_document d ON d.id = c.document_id
             WHERE c.id = :id
        """), {"id": str(charge_id)}).mappings().first()
        if c is not None:
            rows.append({
                "tool": "sources_for", "recorded": False, "source": "landlord_invoice",
                "rank": LANDLORD_INVOICE, "rank_name": RANK_NAMES[LANDLORD_INVOICE],
                "claims": _amount(c["amount"]), "claim_label": "billed",
                "charge_id": c["id"], "invoice_id": c["invoice_id"],
                "charge_type": c["charge_type"], "description": c["description"],
                "page": c["page"], "period": _plain(c["period"]), "doc_id": c["sha256"],
            })
    return sorted(rows, key=lambda r: r["rank"])


def denied_attempts(conn: Connection, *, subject_type: Optional[str] = None,
                    subject_id: Any = None, actor_id: Optional[str] = None,
                    limit: int = 200) -> List[Dict[str, Any]]:
    """Refusals on record, for a subject, an actor, or both."""
    if subject_id is None and actor_id is None:
        raise ValueError("denied_attempts needs a subject or an actor")
    where, params = ["NOT e.allowed"], {"limit": limit}
    if subject_id is not None:
        where.append("e.subject_type = :t AND e.subject_id = :i")
        params.update(t=subject_type or "work_item", i=str(subject_id))
    if actor_id is not None:
        where.append("e.actor_id = :a")
        params["a"] = actor_id
    rows = conn.execute(text("""
        SELECT %s FROM audit_event e LEFT JOIN actor a ON a.id = e.actor_id
         WHERE %s ORDER BY e.seq LIMIT :limit
    """ % (_EVENT_COLUMNS, " AND ".join(where))), params).mappings().all()
    return [_event_row("denied_attempts", r) for r in rows]


def as_known_on(conn: Connection, lease_id: str, on: Any) -> List[Dict[str, Any]]:
    """What we had confirmed about a lease by the end of `on`.

    One row per version (known or not yet, with its confirmation), then the
    terms of the latest version confirmed by then. Bitemporal valid/recorded
    time is not built; the rows say so."""
    day = on if isinstance(on, date) else date.fromisoformat(str(on)[:10])
    cutoff = datetime.combine(day, time.max, tzinfo=timezone.utc)
    versions = conn.execute(text("""
        SELECT id, lease_id, version, effective_from, confirmed_by, confirmed_at
          FROM lease_version WHERE lease_id = :l ORDER BY version
    """), {"l": lease_id}).mappings().all()
    rows, known = [], None
    for v in versions:
        is_known = v["confirmed_at"] is not None and v["confirmed_at"] <= cutoff
        if is_known and v["effective_from"] <= day:
            known = v
        rows.append(dict(_plain(dict(v)), tool="as_known_on", kind="lease_version",
                         as_of=day.isoformat(), known=is_known, note=BITEMPORAL_NOTE))
    if known is not None:
        for t in conn.execute(text("""
            SELECT field, value, page, quote FROM lease_term
             WHERE lease_version_id = :v ORDER BY field
        """), {"v": known["id"]}).mappings():
            rows.append(dict(_plain(dict(t)), tool="as_known_on", kind="lease_term",
                             lease_id=lease_id, version=known["version"],
                             lease_version_id=known["id"], as_of=day.isoformat()))
    return rows


# -------------------------------------------------------------- the agent

def why(conn: Connection, item_id: Any, question: Optional[str] = None, *,
        llm: Any = None) -> WhyAnswer:
    """Why is this work item where it is? Two or three sentences plus rows."""
    item = _item(conn, item_id)
    evidence = item.get("evidence") if isinstance(item.get("evidence"), Mapping) else {}
    q = (question or "").lower()
    used: List[str] = []
    rows: List[Dict[str, Any]] = []

    def run(name, result):
        if name not in used:
            used.append(name)
        rows.extend(result)
        return result

    timeline = run("timeline_for", timeline_for(conn, "work_item", item["id"]))
    sources = run("sources_for", sources_for(conn, item))
    denied = run("denied_attempts", denied_attempts(conn, subject_type="work_item",
                                                    subject_id=item["id"]))
    refs = sorted({e["policy_ref"] for e in timeline if e.get("policy_ref")})
    policy_rows: List[Dict[str, Any]] = []
    for ref in refs:
        policy_rows += run("decisions_by_policy", decisions_by_policy(conn, ref))
    known_rows: List[Dict[str, Any]] = []
    lease_id = evidence.get("lease_id")
    wants_known = any(w in q for w in ("known", "believe", "as of", "knew", "thought"))
    if lease_id and wants_known:
        asked = re.search(r"\d{4}-\d{2}-\d{2}", q)
        on = asked.group(0) if asked else _decision_day(timeline, item)
        known_rows = run("as_known_on", as_known_on(conn, lease_id, on))

    sentences = [_why_state(item, evidence, sources),
                 _who_acted(timeline, policy_rows),
                 _refusals(denied)]
    if known_rows:
        sentences[2] = _known(known_rows, denied)
    answer = " ".join(s for s in sentences if s)
    result = WhyAnswer(answer=answer, rows=rows, tools_used=used, item_id=item["id"])
    if known_rows:
        result.notes.append(BITEMPORAL_NOTE)
    if not sources:
        result.notes.append("no sources on record for this item")

    client = llm if llm is not None else (_default_llm() if os.environ.get("ANTHROPIC_API_KEY")
                                          else None)
    if client is not None:
        phrased = _phrase(client, rows)
        if phrased is not None:
            result.answer, result.path = phrased
    return result


# ------------------------------------------------------- template sentences

def _why_state(item: Mapping, ev: Mapping, sources: List[Mapping]) -> str:
    if item.get("kind") == "CHARGE_CHECK" and ev.get("charge_type"):
        what = ", ".join(str(x) for x in (
            item.get("clinic_name") or item.get("clinic_id"),
            _charge_name(ev.get("charge_type")),
            item["period"].strftime("%B %Y") if isinstance(item.get("period"), date) else None) if x)
    else:
        what = item.get("title") or item.get("kind")
    head = "Item %s (%s) is %s" % (item["id"], what, item["state"])
    recorded = [s for s in sources if s.get("recorded")]
    decision = ev.get("decision") if isinstance(ev.get("decision"), Mapping) else {}
    trusted_id = decision.get("trusted")
    trusted_amendment = next((
        s for s in recorded
        if s.get("source_id") == trusted_id
        and _first(s, "trust_rank", "rank") == 1
        and s.get("kind") == "amendment"), None)
    if trusted_amendment is not None:
        explanation = str(decision.get("explanation") or "The executed amendment governs.")
        return ("%s because the resolver trusted %s (rank 1), which states %s. %s" % (
            head, _source_name(trusted_amendment),
            _show(_first(trusted_amendment, "value", "claim")), explanation))
    lease = next((s for s in sources if s.get("source") == "lease_version"), None)
    invoice = next((s for s in sources if s.get("source") == "landlord_invoice"), None)
    if item.get("kind") == "CHARGE_CHECK" and invoice is not None:
        billed = ev.get("billed", invoice.get("claims"))
        bill = "landlord invoice %s billed %s" % (invoice.get("invoice_id"), _money(billed))
        cite = "lease"
        if lease is not None:
            cite = "lease %s v%s" % (lease.get("lease_id"), lease.get("version"))
            where = [x for x in (
                "§%s" % lease["section"] if lease.get("section") else None,
                "p.%s" % lease["page"] if lease.get("page") else None,
                "confirmed by %s" % lease["confirmed_by"] if lease.get("confirmed_by") else None) if x]
            if where:
                cite += " (%s)" % ", ".join(where)
        supports = "supports %s" % _money(ev.get("supported"))
        if item.get("proposal") == "hold":
            gap = _dec(billed) - _dec(ev.get("supported")) if _dec(billed) is not None and _dec(
                ev.get("supported")) is not None else None
            held = "the %s difference" % _money(gap) if gap is not None else "the difference"
            return ("%s because two sources disagree: %s, but the confirmed %s %s; the lease "
                    "outranks an invoice, so the checker held %s." % (head, bill, cite, supports,
                                                                       held))
        return "%s: %s and the confirmed %s %s, so the two sources agree." % (
            head, bill, cite, supports)
    recorded = [s for s in sources if s.get("recorded")]
    if recorded:
        top, others = recorded[0], recorded[1:]
        parts = ["%s claims %s" % (_source_name(s), _show(_first(s, "claims", "value", "claim")))
                 for s in recorded[:3]]
        trusted = next((s for s in recorded if s.get("trusted")), top)
        return "%s because its sources disagree: %s; the resolver trusted %s%s." % (
            head, "; ".join(parts), _source_name(trusted),
            "" if not others else " as the highest-ranked source")
    reason = item.get("reason")
    return "%s%s." % (head, "; the reason on record is: %s" % reason.rstrip(".") if reason else "")


def _who_acted(timeline: List[Mapping], policy_rows: List[Mapping]) -> str:
    acts = []
    for e in timeline:
        if not e["allowed"] or e["action"] == "create":
            continue
        verb = _VERBS.get(e["action"], e["action"])
        if e["action"] == "approve" and (e.get("evidence") or {}).get("resolution") == "upheld":
            verb = "upheld the hold"
        elif e["action"] == "approve" and (e.get("evidence") or {}).get("resolution") == "pay_as_billed":
            verb = "overrode the hold to pay as billed"
        elif e["action"] == "propose":
            verb = "proposed %s" % ((e.get("diff") or {}).get("set") or {}).get("proposal", "it")
        acts.append("%s %s on %s" % (_who(e), verb, _day(e["at"])))
    if not acts:
        return "Nobody has acted on it yet."
    s = "On record: " + "; ".join(acts)
    cited = [p for p in policy_rows if p.get("kind") == "policy"]
    if cited:
        s += ", citing policy %s" % ", ".join("%s v%s" % (p["name"], p["version"]) for p in cited)
    return s + "."


def _refusals(denied: List[Mapping]) -> str:
    if not denied:
        return "No attempt on it was refused."
    parts = ["%s tried to %s (%s)" % (_who(e), e["action"], (e.get("reason") or "refused").rstrip("."))
             for e in denied[:3]]
    more = " and %d more" % (len(denied) - 3) if len(denied) > 3 else ""
    return "%d refused attempt%s %s on record: %s%s." % (
        len(denied), "" if len(denied) == 1 else "s", "is" if len(denied) == 1 else "are",
        "; ".join(parts), more)


def _known(known_rows: List[Mapping], denied: List[Mapping]) -> str:
    versions = [r for r in known_rows if r.get("kind") == "lease_version"]
    as_of = versions[0]["as_of"] if versions else "then"
    known = [v for v in versions if v["known"]]
    tail = "" if not denied else " (%d refused attempt%s on record)" % (
        len(denied), "" if len(denied) == 1 else "s")
    if not known:
        return "As of %s no version of the lease had been confirmed%s; %s." % (
            as_of, tail, BITEMPORAL_NOTE)
    v = known[-1]
    terms = sum(1 for r in known_rows if r.get("kind") == "lease_term")
    return "As of %s we relied on lease %s v%s, confirmed by %s on %s, with %d terms%s; %s." % (
        as_of, v["lease_id"], v["version"], v["confirmed_by"], str(v["confirmed_at"])[:10],
        terms, tail, BITEMPORAL_NOTE)


_VERBS = {"approve": "approved", "reject": "rejected", "hold": "held it", "resume": "resumed it",
          "ask": "asked a question", "answer": "answered", "post": "posted it",
          "close": "closed it"}


# ------------------------------------------------------------- LLM phrasing

class WhyPhrasing(BaseModel):
    answer: str = Field(description="Two or three plain sentences, using only facts in the rows")


def _default_llm():
    from ..llm.client import LLM
    from ..llm.registry import PromptRegistry

    return LLM(registry=PromptRegistry(PROMPTS_DIR))


def _phrase(client: Any, rows: List[Mapping]):
    """(answer, path) from the model, or None to keep the template. The
    model sees only the rows, fenced as untrusted data by the client."""
    try:
        payload = json.dumps(rows, sort_keys=True, default=str)
        out, meta = client.structured(PROMPT_ID, WhyPhrasing,
                                      documents=[("why-tool-rows", payload)], effort="low",
                                      max_tokens=2000)
        answer = " ".join(str(out.answer).split())
    except Exception:  # noqa: BLE001 — any failure keeps the deterministic answer
        return None
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", answer) if s.strip()]
    if not answer or not 1 <= len(sentences) <= 3:
        return None
    return answer, "llm:%s" % getattr(meta, "model_ref", "unknown")


# ---------------------------------------------------------------- helpers

def _item(conn: Connection, item_id: Any) -> Dict[str, Any]:
    try:
        iid = int(item_id)
    except (TypeError, ValueError):
        raise WhyError("not a work item id: %r" % (item_id,)) from None
    row = conn.execute(text("""
        SELECT w.*, c.name AS clinic_name
          FROM work_item w LEFT JOIN clinic c ON c.id = w.clinic_id
         WHERE w.id = :id
    """), {"id": iid}).mappings().first()
    if row is None:
        raise WhyError("no work item %s" % iid)
    return dict(row)


def _event_row(tool: str, r: Mapping) -> Dict[str, Any]:
    diff = r["diff"] if isinstance(r["diff"], Mapping) else None
    return {
        "tool": tool, "kind": "event", "seq": r["seq"], "at": _plain(r["at"]),
        "actor_id": r["actor_id"], "actor_name": r["actor_name"], "actor_role": r["actor_role"],
        "action": r["action"], "subject_type": r["subject_type"], "subject_id": r["subject_id"],
        "allowed": r["allowed"], "reason": r["reason"],
        "from_state": (diff or {}).get("from"), "to_state": (diff or {}).get("to"),
        "diff": _plain(diff), "evidence": _plain(r["evidence"]),
        "policy_ref": r["policy_ref"], "model_ref": r["model_ref"],
        "hash": (r["hash"] or "").strip() or None,
    }


def _decision_day(timeline: List[Mapping], item: Mapping) -> str:
    for e in reversed(timeline):
        if e["allowed"] and e["action"] in ("approve", "reject", "propose"):
            return str(e["at"])[:10]
    return (item.get("updated_at") or datetime.now(timezone.utc)).date().isoformat()


def _who(e: Mapping) -> str:
    name = e.get("actor_name")
    return "%s (%s)" % (e["actor_id"], name) if name and name != e["actor_id"] else e["actor_id"]


def _source_name(s: Mapping) -> str:
    return str(_first(s, "label", "source", "kind", "source_id") or s.get("rank_name") or "a source")


def _first(m: Mapping, *keys: str) -> Any:
    for k in keys:
        if m.get(k) is not None:
            return m[k]
    return None


def _rank_key(rank: Any) -> int:
    return rank if isinstance(rank, int) and not isinstance(rank, bool) else 99


def _show(v: Any) -> str:
    if v is None or isinstance(v, bool):
        return str(v)
    try:
        Decimal(str(v))
    except Exception:  # noqa: BLE001 — not a number: show it as it is
        return str(v)
    return _money(v)


def _dec(v: Any) -> Optional[Decimal]:
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v))
    except Exception:  # noqa: BLE001 — not a number
        return None
    return d.quantize(Decimal("0.01")) if d.is_finite() else None


def _amount(v: Any) -> Optional[str]:
    """Money as an exact string with cents, the same whether it came from a
    numeric column or a JSON float."""
    d = _dec(v)
    return None if d is None else str(d)


def _money(v: Any) -> str:
    d = _dec(v)
    if d is None:
        return "an unknown amount"
    return "−${:,.2f}".format(abs(d)) if d < 0 else "${:,.2f}".format(d)


def _charge_name(value: Any) -> str:
    return {"base_rent": "base rent", "cam_estimate": "operating expense estimate"}.get(
        str(value), str(value).replace("_", " "))


def _day(at: Any) -> str:
    return str(at)[:10]


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _like_prefix(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _plain(v: Any) -> Any:
    """JSON-safe: money as a string (exact), dates as ISO strings."""
    if isinstance(v, Mapping):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v
