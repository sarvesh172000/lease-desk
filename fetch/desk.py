"""The conversation: one message in, one markdown reply out.

Per person (an ASI:One sender address), the desk remembers the exception last
discussed, so "why?" and "approve it" need no id, and an action waiting for a
yes. Approve and hold are never taken on the first ask: the desk shows what
the action does to the money (what posts, what stays out of the ledger) and
waits for a confirm. A person is approving entries in a ledger from a chat
window; one extra "yes" is cheap.

Every figure in a reply is read off the API. The desk formats; it does not
add, net or round anything the engine did not.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .api import DeskError, LeaseDeskAPI
from .intent import Intent, interpret

HELP = """**Lease Desk** checks every landlord charge against what the lease supports, and \
when they disagree, finds out why.

You can ask me:
- **What's open?** — the charges on hold, and by how much they're off
- **Show exc_4** — one charge: what was billed, what the lease supports, the clause it rests on
- **Why?** — search the mailbox for what explains it (an amendment, a side letter) and \
remeasure the lease if it changed
- **Approve it** / **Hold it** — sign off, after I show you what that posts

I never compute a balance myself: every number comes from Lease Desk's engine, and every \
action goes through the same approvals as the web app."""

CHARGE_NAMES = {
    "base_rent": "base rent",
    "cam_estimate": "CAM estimate",
    "cam_reconciliation": "CAM reconciliation",
    "tax": "property tax",
    "insurance": "insurance",
}


@dataclass
class Conversation:
    last: Optional[str] = None                   # exception last discussed
    pending: Optional[Dict[str, Any]] = None     # {"action", "exception_id", "reason"}


@dataclass
class Desk:
    api: LeaseDeskAPI
    read: Callable[..., Intent] = interpret
    conversations: Dict[str, Conversation] = field(default_factory=dict)

    def end(self, sender: str) -> None:
        self.conversations.pop(sender, None)

    def handle(self, sender: str, text: str, progress: Optional[Callable[[str], None]] = None) -> str:
        """The reply to one message. `progress` gets interim lines for a long step
        (the investigation), so the chat shows work happening."""
        convo = self.conversations.setdefault(sender, Conversation())
        try:
            open_items = self.api.exceptions()
            intent = self.read(text, open_items, convo.last)
            return self._route(convo, intent, open_items, progress)
        except DeskError as exc:
            return _refused(exc)

    # --- routing ---------------------------------------------------------

    def _route(self, convo: Conversation, intent: Intent, open_items: List[Dict[str, Any]],
               progress: Optional[Callable[[str], None]]) -> str:
        if intent.name == "confirm":
            return self._confirm(convo)
        if intent.name == "cancel":
            had = convo.pending is not None
            convo.pending = None
            return "Done, nothing changed." if had else "Nothing is waiting on you."
        # Anything else drops an unanswered question rather than leaving it to
        # be confirmed by a "yes" meant for something later.
        convo.pending = None

        if intent.name == "help":
            return HELP
        if intent.name == "list":
            return self._list(open_items)
        if intent.name == "other":
            return "I'm not sure what you'd like. " + _short_help()

        exc_id = intent.exception_id
        if exc_id is None:
            if len(open_items) == 1:
                exc_id = open_items[0]["exception_id"]
            else:
                return "Which one? " + _pick(open_items)
        convo.last = exc_id

        if intent.name == "show":
            return self._show(exc_id)
        if intent.name == "investigate":
            return self._investigate(exc_id, progress)
        return self._propose(convo, intent.name, exc_id, intent.reason)

    # --- the answers -----------------------------------------------------

    def _list(self, open_items: List[Dict[str, Any]]) -> str:
        if not open_items:
            return "Nothing is open: every charge checked agrees with its lease."
        over = [e["delta"] for e in open_items if e.get("delta") and e["delta"] > 0]
        lines = ["**%d charge%s on hold**%s" % (
            len(open_items), "" if len(open_items) == 1 else "s",
            " — %s billed over what the leases support" % _money(sum(over)) if over else ""), ""]
        lines += ["| Exception | Lease | Charge | Billed | Lease supports | Off by | Status |",
                  "|---|---|---|---|---|---|---|"]
        for e in open_items:
            lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                e["exception_id"], e.get("lease_id") or "—", _charge(e), _money(e.get("actual")),
                _money(e.get("expected")), _signed(e.get("delta")), _status(e.get("status"))))
        lines += ["", "Say **show** or **why** with an id, e.g. *why is %s off?*" % open_items[0]["exception_id"]]
        return "\n".join(lines)

    def _show(self, exc_id: str) -> str:
        d = self.api.exception(exc_id)
        lines = ["**%s · %s · %s %s**" % (exc_id, d.get("lease_id") or "no lease", _charge(d),
                                          _period(d.get("period"))), ""]
        lines.append("- Billed **%s**, the lease supports **%s** (%s)" % (
            _money(d.get("actual")), _money(d.get("expected")), _signed(d.get("delta"))))
        if d.get("reason"):
            lines.append("- Why it's held: %s" % d["reason"])
        cite = d.get("lease_citation") or {}
        if cite.get("quote"):
            lines.append("- The lease (%s): “%s”" % (cite.get("label") or "cited clause", _clip(cite["quote"])))
        lines.append("- Status: %s" % _status(d.get("status")))
        inv = d.get("investigation")
        if inv:
            lines.append("- Investigated: %s" % (inv.get("root_cause") or "no explaining document found"))
        lines += ["", _next_steps(d)]
        return "\n".join(lines)

    def _investigate(self, exc_id: str, progress: Optional[Callable[[str], None]]) -> str:
        found: List[Dict[str, Any]] = []
        remeasured: Optional[Dict[str, Any]] = None
        complete: Optional[Dict[str, Any]] = None
        errors: List[str] = []
        for frame in self.api.investigate(exc_id):
            stage = frame.get("stage")
            if stage == "searching" and progress:
                progress("🔎 %s" % frame.get("message", "Searching the mailbox…"))
            elif stage == "found":
                found.append(frame)
            elif stage == "remeasured":
                remeasured = frame
            elif stage == "complete":
                complete = frame
            elif stage == "error":
                errors.append(frame.get("message", "the investigation could not run"))

        lines = ["**Investigation · %s**" % exc_id, ""]
        if found:
            lines.append("Found what explains it:")
            for f in found:
                src = f.get("source") or f.get("doc_id") or "a document"
                lines.append("- **%s**%s: “%s”" % (
                    src, " (trust rank %s)" % f["trust_rank"] if f.get("trust_rank") else "",
                    _clip(f.get("quote") or "")))
        else:
            lines.append("Nothing in the mailbox explains this variance, so the lease stands as written.")
        if remeasured:
            lines += ["", "The lease changed, so the engine remeasured it: liability %s, ROU asset %s." % (
                _signed(remeasured.get("liability_delta")), _signed(remeasured.get("rou_delta")))]
        if complete and complete.get("entries"):
            lines.append("%d adjusting entr%s proposed%s." % (
                complete["entries"], "y" if complete["entries"] == 1 else "ies",
                ", balanced" if complete.get("balanced") else ""))
        for e in errors:
            lines += ["", "⚠️ %s" % e]
        lines += ["", "Nothing has been posted. Say **approve it** to sign off, or **hold it** to park it."]
        return "\n".join(lines)

    def _propose(self, convo: Conversation, action: str, exc_id: str, reason: Optional[str]) -> str:
        d = self.api.exception(exc_id)
        convo.pending = {"action": action, "exception_id": exc_id, "reason": reason}
        head = "**%s %s?** %s, %s, %s" % (
            "Approve" if action == "approve" else "Hold", exc_id, d.get("lease_id") or "no lease",
            _charge(d), _period(d.get("period")))
        if action == "hold":
            what = "It goes to **on hold** and nothing is posted."
        elif d.get("payable") is None:
            # An API that does not say what approving posts gets no guess from us.
            what = "Lease Desk didn't say what approving posts, so check it in the web app before you sign off."
        elif d.get("proposal") == "hold":
            # Approving a hold upholds it: the undisputed amount posts, the rest stays out.
            what = "That upholds the hold: **%s** posts to AP, **%s** stays out of the ledger as disputed." % (
                _money(d.get("payable")), _money(d.get("disputed")))
        else:
            what = "**%s** posts to AP as billed." % _money(d["payable"])
        return "%s\n\n%s\n\nReply **yes** to go ahead, or **no**." % (head, what)

    def _confirm(self, convo: Conversation) -> str:
        p, convo.pending = convo.pending, None
        if p is None:
            return "Nothing is waiting on a yes. " + _short_help()
        act = self.api.approve if p["action"] == "approve" else self.api.hold
        result = act(p["exception_id"], p.get("reason"))
        who = (self.api.actor or {}).get("name", "you")
        done = "Approved" if p["action"] == "approve" else "Put on hold"
        return "✅ %s %s as %s. Work state: **%s**.%s It's on the audit trail." % (
            done, p["exception_id"], who, result.get("state"), _posting(result.get("posting")))


# --- formatting --------------------------------------------------------------

def _money(v: Optional[float]) -> str:
    return "—" if v is None else "${:,.2f}".format(v)


def _signed(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return "%s%s" % ("+" if v > 0 else "−" if v < 0 else "", "${:,.2f}".format(abs(v)))


def _charge(e: Dict[str, Any]) -> str:
    t = e.get("charge_type")
    return CHARGE_NAMES.get(t, (t or "charge").replace("_", " "))


def _period(p: Optional[str]) -> str:
    return ("for %s" % p[:7]) if p else ""


def _status(s: Optional[str]) -> str:
    return {"exception": "new", "pending_review": "awaiting sign-off", "escalated": "on hold",
            "balanced": "resolved"}.get(s or "", s or "—")


def _clip(s: str, n: int = 280) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _posting(p: Optional[Dict[str, Any]]) -> str:
    if not p:
        return ""
    if p.get("status") == "posted":
        return " Posted %s to Accounts payable%s." % (
            _money(p.get("amount")), "; %s kept out as disputed" % _money(p["disputed"]) if p.get("disputed") else "")
    if p.get("status") == "closed":
        return " Nothing was owed, so nothing posted."
    return " Not posted yet%s." % (": %s" % p["error"] if p.get("error") else "")


def _next_steps(d: Dict[str, Any]) -> str:
    if d.get("status") == "balanced":
        return "This one is resolved."
    return "Ask **why?** to search the mailbox, or say **approve it** / **hold it**."


def _pick(open_items: List[Dict[str, Any]]) -> str:
    if not open_items:
        return "Nothing is open right now."
    return "Open: " + ", ".join("%s (%s %s)" % (e["exception_id"], e.get("lease_id"), _charge(e))
                                for e in open_items)


def _short_help() -> str:
    return "Try **what's open?**, **why is exc_4 off?** or **help**."


def _refused(exc: DeskError) -> str:
    if exc.status == 403:
        return "🚫 Lease Desk refused that: %s. Your role can't make this change; the refusal is on record." % exc
    if exc.status == 409:
        return "That can't be done in its current state: %s" % exc
    if exc.status == 404:
        return "I can't find that: %s" % exc
    return "⚠️ %s" % exc
