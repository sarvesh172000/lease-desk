"""ASI:One's model, in front of the grammar, as a suggestion only.

When a paired person's message does not parse under the fixed grammar
(grammar.py) — "the CAM one at Store 3 looks wrong, can you dig in?" — the
front desk may ask ASI:One's `asi1` model (OpenAI-compatible, POST
https://api.asi1.ai/v1/chat/completions, key ASI_ONE_API_KEY) to translate it
into one grammar command. The grammar stays the security boundary:

- The model fills a fixed JSON form (`intent`, `item`, `lease`, `topic`,
  `text`). That form is written out as the one line a person would type
  (grammar.render) and parsed again by grammar.parse; the result must be the
  command the form named, or the reading is dropped.
- The model may only name items the person can see right now (the API's
  own list for their token, plus the item they last looked at). An item it
  made up is no item, and the reading is dropped.
- A read (inbox, review, why, investigate, lease) may then run as if typed.
  An action (approve, uphold, hold, reject, resume, answer) never runs from
  a reading: the front desk replies with the exact line it would run and asks
  the person to send it, or to press a card button that goes through the
  same grammar (front_desk.py). Pairing, unpairing and help are never
  translated.

Without ASI_ONE_API_KEY there is no model and the grammar is all there is.
Any failure (timeout, non-JSON, unknown intent) is the same as no reading.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional

import httpx

from .grammar import ACTIONS, MAX_TEXT, NEEDS_TEXT, READS, TOPICS, Command, parse, render

log = logging.getLogger(__name__)

ASI_URL = "https://api.asi1.ai/v1/chat/completions"
TIMEOUT_S = 20.0

INTENTS = ("inbox", "review", "why", "investigate", "lease") + tuple(ACTIONS) + ("none",)
_LEASE_REF = re.compile(r"^(?:LEASE-[A-Z0-9-]{1,40}|STORE-[0-9]{2,4})$")

SYSTEM = """You translate chat messages for Northbay Lease Desk, a lease accounting desk, into
one command. You never act; a person confirms anything that changes data.

Answer with JSON only, no prose:
{"intent": ..., "item": ..., "lease": ..., "topic": ..., "text": ...}

intent is one of:
  inbox        what needs me / what's open / my queue
  review       show one item's details
  why          why is an item in the state it is in
  investigate  why is a charge off / look into it / search the mailbox for what explains it
  lease        a question about a lease's terms (rent, escalation, CAM, dates, area, renewal)
  approve | uphold | hold | reject | resume | answer   an action on one item
  none         anything else
item is one item number from the list below, or null. Resolve "it" / "that one" to the
last item discussed. Never invent a number that is not listed.
lease is "LEASE-01" style or "STORE-03" style, or null.
topic is one of: %s, or null.
text is the person's own reason or answer, in their words, or null. Never write one for them.

Items this person can see:
%s
Last item discussed: %s"""


@dataclass(frozen=True)
class Reading:
    """What the model read, already re-parsed by the grammar."""
    command: Command
    line: str               # the exact grammar line that gives `command`
    complete: bool = True   # False: an action still missing its reason/answer (line has a placeholder)

    @property
    def is_action(self) -> bool:
        return self.command.name == "act"


Understand = Callable[[str, List[Mapping[str, Any]], Optional[int]], Optional[Reading]]


def from_env(http: Optional[httpx.Client] = None) -> Optional[Understand]:
    """The asi1 reader when ASI_ONE_API_KEY is set, else None (grammar only)."""
    key = os.environ.get("ASI_ONE_API_KEY", "").strip()
    if not key:
        return None
    model = os.environ.get("ASI_ONE_MODEL", "asi1").strip() or "asi1"
    client = http or httpx.Client(timeout=TIMEOUT_S)

    def understand(text: str, items: List[Mapping[str, Any]], last_item: Optional[int]) -> Optional[Reading]:
        try:
            return read(ask_asi1(client, key, model, text, items, last_item), items, last_item)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            log.info("asi1 gave no usable reading: %s", exc)
            return None

    return understand


def ask_asi1(http: httpx.Client, key: str, model: str, text: str, items: List[Mapping[str, Any]],
             last_item: Optional[int]) -> Dict[str, Any]:
    listing = "\n".join(_line(i) for i in items[:50]) or "(none)"
    r = http.post(ASI_URL, headers={"Authorization": "Bearer %s" % key},
                  json={"model": model, "max_tokens": 200, "temperature": 0,
                        "messages": [{"role": "system",
                                      "content": SYSTEM % (", ".join(TOPICS), listing, last_item or "none")},
                                     {"role": "user", "content": text[:MAX_TEXT]}]})
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", content or "", re.S)
    if not match:
        raise ValueError("no JSON in the model's answer")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("the model's JSON is not an object")
    return data


def _line(item: Mapping[str, Any]) -> str:
    return "- #%s %s %s %s: %s" % (item.get("id"), item.get("state"), item.get("clinic_id") or "",
                                   item.get("amount") if item.get("amount") is not None else "",
                                   " ".join(str(item.get("title") or "").split())[:100])


def read(data: Mapping[str, Any], items: List[Mapping[str, Any]], last_item: Optional[int]) -> Optional[Reading]:
    """The model's form -> a grammar command, or None. Pure, so it is tested
    against hostile model answers without a model."""
    intent = data.get("intent")
    if intent not in INTENTS or intent == "none":
        return None
    visible = {int(i["id"]) for i in items if isinstance(i.get("id"), int)}
    if last_item:
        visible.add(int(last_item))
    item = data.get("item")
    if isinstance(item, str) and item.lstrip("#").isdigit():
        item = int(item.lstrip("#"))
    if not isinstance(item, int) or isinstance(item, bool) or item not in visible:
        # The model may only point at what this person can see; anything else is no item.
        item = None
    text = data.get("text")
    text = " ".join(text.split())[:MAX_TEXT] if isinstance(text, str) and text.strip() else None

    if intent == "inbox":
        wanted = Command("inbox")
    elif intent in ("review", "why", "investigate"):
        if item is None:
            return None
        wanted = Command(intent, item_id=item)
    elif intent == "lease":
        ref = str(data.get("lease") or "").upper().strip()
        if not _LEASE_REF.match(ref):
            return None
        topic = data.get("topic")
        wanted = Command("lease", lease_ref=ref, topic=topic if topic in TOPICS else None)
    else:   # an action
        if item is None:
            return None
        wanted = Command("act", item_id=item, action=ACTIONS[intent], verb=intent, text=text)
        if intent in NEEDS_TEXT and text is None:
            # Never write the reason for them: show where it goes.
            return Reading(wanted, "%s %d <your %s>" % (intent, item, "answer" if intent == "answer" else "reason"),
                           complete=False)

    line = render(wanted)
    if line is None:
        return None
    got = parse(line)
    # The grammar has the last word: the line must parse back to what the form named.
    if got.name != wanted.name or got.item_id != wanted.item_id or (
            got.name == "act" and got.verb != wanted.verb) or (
            got.name == "lease" and got.lease_ref != wanted.lease_ref):
        return None
    if got.name not in READS and got.name != "act":
        return None
    return Reading(got, line)
