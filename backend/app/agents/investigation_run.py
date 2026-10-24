"""Run the modification investigation for one exception and shape what it found.

The agent in `modification.py` is the whole of the thinking; this module only
gives it the corpus and the lease, and turns its result into the investigation
shape §16 puts on the money screen. Nothing here decides anything: the model
nominates documents, `trust.py` ranks them, and the engine computes the
remeasurement, exactly as the eval runs it.

The corpus is the mailbox. It is generated rather than stored because the
emails are the one input that never came through a system of record — that is
the premise of the product, and `jobs/monthly.py` builds the lease rules the
same way.
"""

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..engine.remeasurement import Proposal
from ..llm.client import LLM
from .modification import SETTLED, Investigation, investigate

log = logging.getLogger(__name__)

# The books are closed through here, so a remeasurement lands in an open
# period. Matches eval/run.py, which is the reference run.
BOOKS_CLOSED_THROUGH = date(2026, 9, 1)


class NoModel(RuntimeError):
    """No model client and nothing cached: the investigation cannot run.

    Not an application error. A cache hit never reaches the network, so a
    warmed cache runs this offline forever; a cold one needs a key once.
    """


def build_llm() -> LLM:
    """Cache-first, network only on a miss (the eval's rule, same reasons)."""
    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        return LLM()
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - the package is a dependency
        raise NoModel("the anthropic package is not installed") from exc
    # A key that cannot work: a cache hit still answers, a miss fails loudly
    # rather than silently inventing an explanation.
    return LLM(client=anthropic.Anthropic(api_key="cache-only-no-network"))


def corpus() -> Tuple[Any, List[Tuple[str, str]], Dict[str, dict]]:
    """The company, its mailbox as (id, text), and the facts ranking needs."""
    from datagen.company import build_company
    from datagen.emails import build_emails

    company = build_company()
    emails = build_emails(company)
    serra = company.landlord("LL-SERRA")
    documents = [(m.message_id, m.to_eml()) for m in emails]
    senders = {
        m.message_id: {
            "sender": m.sender, "body": m.body, "sent": m.sent,
            "has_attachment": m.has_attachment,
            "authorized_rep_email": serra.authorized_rep_email,
            "landlord_domain": "serramonteretail.example",
        } for m in emails
    }
    return company, documents, senders


def lease_payload(company, lease_id: str) -> Optional[dict]:
    from datagen.leases import build_leases

    for lease in build_leases(company):
        if lease.lease_id == lease_id:
            return lease.to_engine_json(company)
    return None


def variance_sentence(lease_id: str, period: date, expected: Optional[float],
                      actual: Optional[float], delta: Optional[float]) -> str:
    """What the agent is asked to explain, in the eval's wording."""
    month = period.strftime("%b %Y") if period else "the period"
    if expected is None or actual is None or delta is None:
        return "%s %s: a charge does not match the lease." % (lease_id, month)
    direction = "overpaid" if delta > 0 else "underpaid"
    return "%s %s: expected $%s, paid $%s (%s $%s)" % (
        lease_id, month, "{:,.2f}".format(expected), "{:,.2f}".format(actual),
        direction, "{:,.2f}".format(abs(delta)))


def run(lease_id: str, period: date, expected: Optional[float], actual: Optional[float],
        delta: Optional[float], llm: Optional[LLM] = None) -> Tuple[Investigation, int]:
    """Investigate one variance. Returns the result and the corpus size."""
    company, documents, senders = corpus()
    payload = lease_payload(company, lease_id)
    if payload is None:
        raise NoModel("no lease %r in the register" % lease_id)
    try:
        return _investigate(llm or build_llm(), lease_id, period, expected, actual,
                            delta, documents, senders, payload), len(documents)
    except Exception as exc:
        if _cache_cold(exc):
            raise NoModel(
                "No model credentials, and this question is not cached yet. Set "
                "ANTHROPIC_API_KEY once and run it again: the answer is then "
                "cached and every later run is offline.") from None
        raise


def _cache_cold(exc: Exception) -> bool:
    """True when the only thing missing was the network, not the logic.

    Same test the eval uses to report a section as skipped rather than failed.
    """
    text = str(exc).lower()
    return any(m in text for m in (
        "anthropic_api_key", "authentication", "invalid bearer token",
        "401", "could not resolve", "connection", "timed out"))


def _investigate(llm, lease_id, period, expected, actual, delta,
                 documents, senders, payload) -> Investigation:
    return investigate(
        llm=llm,
        lease_id=lease_id,
        period=period,
        variance_text=variance_sentence(lease_id, period, expected, actual, delta),
        documents=documents,
        senders=senders,
        lease_payload=payload,
        books_closed_through=BOOKS_CLOSED_THROUGH,
        variance=delta or 0.0,
    )


# --- shaping -------------------------------------------------------------------

def to_payload(result: Investigation) -> dict:
    """The §16 `investigation` object, written as recorded.

    Every figure comes off the engine's proposal; nothing is recomputed, and a
    field with nothing behind it stays null rather than becoming a zero.
    """
    proposal: Optional[Proposal] = result.proposal
    return {
        "root_cause": _root_cause(result),
        "confidence": round(result.confidence, 4),
        "explains_variance": result.explains,
        "evidence": [_evidence(s) for s in result.sources],
        "liability_before": _money(proposal.liability_before) if proposal else None,
        "liability_after": _money(proposal.liability_after) if proposal else None,
        "rou_before": _money(proposal.rou_before) if proposal else None,
        "rou_after": _money(proposal.rou_after) if proposal else None,
        "liability_delta": _money(proposal.liability_delta) if proposal else None,
        "rou_delta": _money(proposal.rou_delta) if proposal else None,
        "entries": [
            {"account": e["account"], "debit": _money(e["debit"]), "credit": _money(e["credit"])}
            for e in (proposal.entries if proposal else [])
        ],
        "balanced": bool(proposal.balanced) if proposal else None,
        "outcome": result.outcome,
        "reasons": list(result.reasons),
        "searched": result.searched,
    }


def _root_cause(result: Investigation) -> Optional[str]:
    if result.outcome == SETTLED:
        return "amendment"
    return result.outcome or None


def _evidence(source) -> dict:
    """One ranked source. `page`/`box` stay null: these are emails, not pages
    of a stored PDF, so there is nothing to box."""
    return {
        "doc_id": source.source_id,
        "date": source.sent.isoformat() if isinstance(source.sent, date) else None,
        "source": source.sender,
        "trust_rank": source.rank,
        "quote": source.quote,
        "page": None,
        "box": None,
    }


def _money(value) -> Optional[float]:
    return None if value is None else round(float(value), 2)


def events(payload: dict, searched: int) -> Sequence[dict]:
    """The four SSE stages of §16, read off the finished investigation.

    They are emitted as each becomes known rather than on a timer; a stage the
    investigation never reached is simply not sent.
    """
    out: List[dict] = [
        {"stage": "searching", "message": "Searching %s documents…" % "{:,}".format(searched)},
    ]
    evidence = payload.get("evidence") or []
    if payload.get("explains_variance") and evidence:
        first = evidence[0]
        out.append({"stage": "found", "doc_id": first["doc_id"], "quote": first["quote"],
                    "confidence": payload.get("confidence") or 0.0})
    if payload.get("liability_delta") is not None:
        out.append({"stage": "remeasured",
                    "liability_delta": payload["liability_delta"],
                    "rou_delta": payload.get("rou_delta")})
    if payload.get("entries"):
        out.append({"stage": "complete", "entries": len(payload["entries"]),
                    "balanced": bool(payload.get("balanced"))})
    return out
