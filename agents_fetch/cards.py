"""ASI1 Interactive Cards for the chat workflow.

A card travels in a chat message as a `MetadataContent` block (uagents_core
`chat.cards`, wire version "1"): the metadata says it is a card, which kind,
and carries the payload as JSON. This module builds those metadata dicts with
plain Python, so it is testable without uagents installed; when uagents_core
is installed, `validate()` checks a payload against its own schema, and the
front desk wraps the dict in `MetadataContent(metadata=...)`.

`held_item_card(detail, why)` is the review card for one work item: what was
billed and what the lease supports, the sources by trust rank, the trust
explanation and confidence when the evidence has them, and one button per
action can() allows the paired person (the item's `allowed_actions`). A
button for an action the person may not take is never drawn, and pressing
any button still goes through the API, which checks again.
"""

import json
import uuid
from typing import Any, Dict, List, Mapping, Optional

CARD_PROTOCOL_VERSION = "1"

# API action -> (chat verb, button label). Approving a charge check whose
# proposal is a hold upholds the hold (api/items.py), so it is labelled so.
_BUTTONS = (
    ("approve", "approve", "Approve"),
    ("answer", "answer", "Answer the question"),
    ("hold", "hold", "Hold"),
    ("resume", "resume", "Resume"),
    ("reject", "reject", "Reject"),
)


def money(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    return ("-$%s" if n < 0 else "$%s") % format(abs(n), ",.2f")


def _short(value: Any, limit: int = 160) -> str:
    s = " ".join(str(value).split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def card_metadata(card_kind: str, payload: Mapping[str, Any], card_id: Optional[str] = None,
                  is_terminal: bool = False) -> Dict[str, str]:
    """The MetadataContent.metadata for a card request (uagents_core
    `create_card_content`, wire version 1)."""
    metadata = {
        "card_protocol_version": CARD_PROTOCOL_VERSION,
        "requires_card_interaction": "true",
        "card_kind": card_kind,
        "card_payload": json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        "card_id": card_id or str(uuid.uuid4()),
    }
    if is_terminal:
        metadata["is_terminal"] = "true"
    return metadata


def selection_from_metadata(metadata: Mapping[str, str]) -> Optional[Dict[str, Any]]:
    """A card *response* (a button press) -> its selection dict, else None.
    Requests (they carry card_kind) and anything malformed are None."""
    if metadata.get("card_protocol_version") != CARD_PROTOCOL_VERSION or "card_kind" in metadata:
        return None
    raw = metadata.get("selection")
    if raw is None:
        return None
    try:
        selection = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(selection, dict):
        return None
    if not all(isinstance(v, (str, int, float, bool)) for v in selection.values()):
        return None
    return selection


def validate(card_kind: str, payload: Mapping[str, Any]) -> bool:
    """True when uagents_core accepts the payload; True also when uagents_core
    is not installed (the wire format is all this module promises then)."""
    try:
        from uagents_core.contrib.protocols.chat.cards import validate_card_payload
    except ImportError:
        return True
    validate_card_payload(card_kind, dict(payload))
    return True


def _verb(api_action: str, item: Mapping[str, Any]) -> str:
    if api_action == "approve" and item.get("kind") == "CHARGE_CHECK" and item.get("proposal") == "hold":
        return "uphold"
    return api_action


def _label(api_action: str, item: Mapping[str, Any], default: str) -> str:
    if _verb(api_action, item) == "uphold":
        return "Uphold the hold (pay the undisputed part)"
    return default


def source_rows(why: Optional[Mapping[str, Any]], evidence: Mapping[str, Any]) -> List[Dict[str, str]]:
    """The sources, highest trust first: the why answer's `sources_for` rows
    when there are any, else what the evidence recorded."""
    rows = [r for r in (why or {}).get("rows") or [] if r.get("tool") == "sources_for"]
    if not rows and isinstance(evidence.get("sources"), list):
        rows = [s for s in evidence["sources"] if isinstance(s, Mapping)]
    out = []
    for i, r in enumerate(rows[:4], start=1):
        rank = r.get("rank_name") or r.get("source") or r.get("kind") or "source"
        where = []
        if r.get("section"):
            where.append("§%s" % r["section"])
        if r.get("page"):
            where.append("p.%s" % r["page"])
        claim = r.get("claims") if r.get("claims") is not None else r.get("amount")
        bits = [" ".join(where)] if where else []
        if claim is not None:
            bits.append("%s %s" % (r.get("claim_label") or "says", money(claim)))
        if r.get("quote"):
            bits.append("“%s”" % _short(r["quote"], 120))
        elif r.get("claim"):
            bits.append(_short(r["claim"], 120))
        out.append({"label": "Source %d · %s" % (i, _short(rank, 40)),
                    "value": " · ".join(b for b in bits if b) or "—"})
    return out


def trust_text(evidence: Mapping[str, Any]) -> Optional[str]:
    for key in ("trust_explanation", "explanation"):
        if evidence.get(key):
            return _short(evidence[key], 300)
    trust = evidence.get("trust")
    if isinstance(trust, Mapping) and trust.get("explanation"):
        return _short(trust["explanation"], 300)
    if isinstance(trust, str) and trust:
        return _short(trust, 300)
    return None


def held_item_card(detail: Mapping[str, Any], why: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """{"card_kind", "payload", "metadata"} for one item, from GET
    /api/items/{id} (and optionally POST /api/items/{id}/why)."""
    item = detail.get("item") or {}
    evidence = detail.get("evidence") or {}
    item_id = int(item["id"])
    allowed = list(detail.get("allowed_actions") or [])

    rows = [
        {"label": "State", "value": "%s%s" % (item.get("state"),
                                             " · proposal: %s" % item["proposal"] if item.get("proposal") else "")},
        {"label": "Clinic · period", "value": "%s · %s" % (item.get("clinic_id") or "—",
                                                          str(item.get("period") or "—")[:7])},
    ]
    if evidence.get("billed") is not None:
        rows.append({"label": "Billed", "value": money(evidence["billed"])})
    if evidence.get("supported") is not None:
        rows.append({"label": "Lease supports", "value": money(evidence["supported"])})
    if evidence.get("billed") is not None and evidence.get("supported") is not None:
        try:
            rows.append({"label": "At stake", "value": money(float(evidence["billed"])
                                                             - float(evidence["supported"]))})
        except (TypeError, ValueError):
            pass
    elif item.get("amount") is not None:
        rows.append({"label": "Amount", "value": money(item["amount"])})
    rows.extend(source_rows(why, evidence))
    trust = trust_text(evidence)
    if trust:
        rows.append({"label": "Trust", "value": trust})
    confidence = evidence.get("confidence")
    if isinstance(confidence, (int, float)):
        rows.append({"label": "Confidence", "value": "%.2f" % confidence})
    if why and why.get("answer"):
        rows.append({"label": "Why", "value": _short(why["answer"], 300)})
    open_q = [q for q in detail.get("questions") or [] if not q.get("answer")]
    if open_q:
        rows.append({"label": "Open question", "value": _short(open_q[-1].get("body"), 200)})

    ctas = []
    for api_action, _verb_default, label in _BUTTONS:
        if api_action in allowed:
            ctas.append({"label": _label(api_action, item, label),
                         "selection": {"cmd": _verb(api_action, item), "item_id": item_id},
                         "primary": not ctas})
    ctas.append({"label": "Why is it here?", "selection": {"cmd": "why", "item_id": item_id},
                 "primary": False})

    payload = {"title": "#%d · %s" % (item_id, _short(item.get("title") or item.get("kind"), 80)),
               "summary_rows": rows, "ctas": ctas}
    validate("detail", payload)
    return {"card_kind": "detail", "payload": payload,
            "metadata": card_metadata("detail", payload)}


def inbox_card(items: List[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """A carousel of up to ten open items, each with a Review button."""
    if not items:
        return None
    carousel = []
    for it in items[:10]:
        carousel.append({
            "id": str(it["id"]),
            "title": "#%d · %s" % (it["id"], _short(it.get("title") or it.get("kind"), 60)),
            "subtitle": "%s · %s" % (it.get("state"), it.get("clinic_id") or "—"),
            "secondary_text": money(it.get("amount")) if it.get("amount") is not None else None,
            "primary_cta": {"label": "Review", "selection": {"cmd": "review", "item_id": int(it["id"])}},
        })
    for c in carousel:
        if c["secondary_text"] is None:
            del c["secondary_text"]
    payload = {"title": "Needs you", "items": carousel}
    validate("carousel", payload)
    return {"card_kind": "carousel", "payload": payload,
            "metadata": card_metadata("carousel", payload)}
