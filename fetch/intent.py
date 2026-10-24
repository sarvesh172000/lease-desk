"""What the person asked for, as one of a few fixed intents.

ASI:One's model (`asi1`, OpenAI-compatible at api.asi1.ai) reads the message
with the open exceptions in view, so "the CAM one" or "LEASE-03" resolves to
an exception id. It only classifies; it never sees a figure it could change,
and its answer is checked against the ids that actually exist.

When the model is unavailable (no key, a timeout, an answer that is not the
JSON asked for), a keyword reader takes over, so the desk still works and
says less cleverly what it understood.
"""

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

INTENTS = ("help", "list", "show", "investigate", "approve", "hold", "confirm", "cancel", "other")
# Intents that need an exception to act on.
TARGETED = ("show", "investigate", "approve", "hold")

ASI_URL = "https://api.asi1.ai/v1/chat/completions"

SYSTEM = """You route messages for Lease Desk, a lease accounting desk.
Open exceptions are landlord charges that disagree with what the lease supports.

Answer with JSON only, no prose: {"intent": ..., "exception_id": ..., "reason": ...}
intent is one of:
  help         what can you do / hello
  list         what's open, what needs attention, any problems
  show         details of one exception
  investigate  why is it wrong, explain it, look into it, search the mailbox
  approve      approve / sign off / accept the hold on one exception
  hold         park it / put it on hold / wait on it
  confirm      yes / go ahead / do it (answering a question the desk asked)
  cancel       no / stop / never mind
  other        anything else
exception_id is one id from the list below, or null. Resolve references like
"the first one", "LEASE-03", "the CAM charge" or "it" (the last one discussed).
reason is the person's own reason if they gave one, else null.

Open exceptions:
%s
Last discussed: %s"""


@dataclass(frozen=True)
class Intent:
    name: str
    exception_id: Optional[str] = None
    reason: Optional[str] = None
    via: str = "keywords"        # "asi1" when the model read it


def interpret(text: str, open_items: List[Dict[str, Any]], last: Optional[str],
              http: Optional[httpx.Client] = None) -> Intent:
    """The model's reading if it gives a valid one, else the keyword reading."""
    key = os.environ.get("ASI_ONE_API_KEY")
    if key:
        try:
            got = _ask_asi(text, open_items, last, key, http or httpx.Client(timeout=20.0))
            if got is not None:
                return got
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            pass
    return by_keywords(text, open_items, last)


def _ask_asi(text: str, open_items: List[Dict[str, Any]], last: Optional[str],
             key: str, http: httpx.Client) -> Optional[Intent]:
    listing = "\n".join(_line(e) for e in open_items) or "(none)"
    r = http.post(ASI_URL, headers={"Authorization": "Bearer %s" % key},
                  json={"model": os.environ.get("ASI_ONE_MODEL", "asi1"), "max_tokens": 200,
                        "messages": [{"role": "system", "content": SYSTEM % (listing, last or "none")},
                                     {"role": "user", "content": text}]})
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        return None
    data = json.loads(match.group(0))
    name = data.get("intent")
    if name not in INTENTS:
        return None
    exc_id = data.get("exception_id")
    known = {e["exception_id"] for e in open_items}
    if exc_id not in known:
        # The model may only point at what exists; an id it made up is no id.
        exc_id = _explicit_id(text) or (last if name in TARGETED else None)
    reason = data.get("reason")
    return Intent(name, exc_id, reason if isinstance(reason, str) and reason.strip() else None, via="asi1")


def _line(e: Dict[str, Any]) -> str:
    return "- %s: %s %s %s, billed %s, lease supports %s" % (
        e["exception_id"], e.get("lease_id"), e.get("clinic_id"), e.get("charge_type"),
        e.get("actual"), e.get("expected"))


# --- the fallback ------------------------------------------------------------

_WORDS = [
    ("cancel", r"^\s*(no|nope|cancel|stop|never ?mind|don'?t)\b"),
    ("confirm", r"^\s*(yes|yep|yeah|y|confirm|go ahead|do it|ok(ay)?|sure)\b"),
    ("investigate", r"\b(why|investigat\w*|explain|look into|dig|search|cause|amendment)\b"),
    ("approve", r"\b(approve|sign ?off|uphold|accept)\b"),
    ("hold", r"\b(hold|park|wait)\b"),
    ("show", r"\b(show|detail|details|open|tell me about|what about)\b"),
    ("list", r"\b(list|open|pending|problems?|exceptions?|attention|anything|wrong)\b"),
    ("help", r"\b(help|hi|hello|hey|what can you do|start)\b"),
]


def by_keywords(text: str, open_items: List[Dict[str, Any]], last: Optional[str]) -> Intent:
    lowered = text.lower()
    exc_id = _explicit_id(text) or _by_lease(lowered, open_items)
    for name, pattern in _WORDS:
        if re.search(pattern, lowered):
            if name in TARGETED and exc_id is None:
                exc_id = last
            # "show me what's open" is a list, not a detail with nothing to show.
            if name == "show" and exc_id is None:
                name = "list"
            return Intent(name, exc_id)
    if exc_id is not None:
        return Intent("show", exc_id)
    return Intent("other")


def _explicit_id(text: str) -> Optional[str]:
    m = re.search(r"\bexc[_ -]?(\d{1,18})\b", text, re.I)
    return "exc_%s" % m.group(1) if m else None


def _by_lease(lowered: str, open_items: List[Dict[str, Any]]) -> Optional[str]:
    for e in open_items:
        for key in ("lease_id", "clinic_id"):
            v = e.get(key)
            if v and v.lower() in lowered:
                return e["exception_id"]
    return None
