"""front_desk: "Northbay Lease Desk", the ASI:One entry point.

It speaks the Agent Chat Protocol to people in ASI:One (runtime.py wires it
into uAgents: acknowledgements, StartSession/EndSession, Interactive Cards),
pairs a chat user to a Lease Desk person with a one-time code, and routes
everything else over agent messaging to the three specialists:

    rulebook_agent       lease questions, answered with page and quote
    approvals_agent      the paired person's queue, reviews, answers and actions
    investigation_agent  why a charge is off: the mailbox search and remeasurement

It never touches the database and never holds a password. Its only
credential per chat user is the scoped pairing token the API issued, and the
API checks every call made with it (can(), the gateway, the audit stream).

Untrusted input: every chat message goes through grammar.parse(), a fixed
grammar, before anything happens. One message is at most one command; an
action runs only when the message starts with its verb and item number.
An unpaired chat user gets help text and nothing else — no Lease Desk call
is made for them at all except the pairing claim.

ASI:One's model (understand.py) is optional, and only for a paired person's
message the grammar could not parse. Its reading is re-parsed by the grammar;
a read then runs as if typed, with a note saying how the message was read,
while an action never runs from it: the reply is the exact line to send, and
a card button that sends that same command through the same grammar.

Each message gets one run id; the front desk records its own steps on the
live feed (live.py) under it and hands it to the specialist, which records
its steps under the same id.

Logic here is plain Python (`FrontDesk.route` / `FrontDesk.handle`), so the
whole conversation is tested against the real API without uAgents.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Union

from .cards import suggested_action_card
from .client import ApiError, LeaseDeskClient
from .grammar import APPROVALS, DESK, HELP, INVESTIGATION, RULEBOOK, Command, from_selection, parse, render
from .live import Feed
from .pairing import MemoryPairingStore, PairingStore, describe_actor, remembered
from .protocol import ERROR, INVALID, UNPAIRED, Reply
from .understand import Reading, Understand

AGENT_NAME = "Northbay Lease Desk"
DESCRIPTION = ("Lease accounting for Northbay PT inside ASI:One: what needs you this week, review a "
               "held charge with its sources and trust explanation, answer it, and ask why — under "
               "your own Lease Desk permissions. Pair first with a one-time code from the web app.")

NOT_PAIRED = ("This chat isn't paired with a Lease Desk account yet, so I can't show or change "
              "anything. In Lease Desk, open your name (top right) → *Connect chat* and send `pair XXXX-XXXX` here.")
BAD_CODE = ("That code didn't work: it may be mistyped, already used, or older than ten minutes. "
            "Get a fresh one in Lease Desk: your name (top right) → *Connect chat*.")

FEED_NAME = "front_desk"
SPECIALISTS = (APPROVALS, RULEBOOK, INVESTIGATION)

Dispatch = Callable[[str, Dict[str, Any]], Dict[str, Any]]


@dataclass
class Route:
    """Send `request` to `specialist` and hand its reply to FrontDesk.finish()."""
    specialist: str
    request: Dict[str, Any]
    command: Command
    note: Optional[str] = None      # how ASI:One's model read the message, shown above the reply


class FrontDesk:
    def __init__(self, api: LeaseDeskClient, store: Optional[PairingStore] = None,
                 dispatch: Optional[Dispatch] = None, feed: Optional[Feed] = None,
                 understand: Optional[Understand] = None):
        self.api = api
        self.store = store if store is not None else MemoryPairingStore()
        self.feed = feed if feed is not None else Feed()
        self.dispatch = dispatch if dispatch is not None else local_dispatch(api, self.feed)
        # None: the grammar only (no ASI_ONE_API_KEY). Never consulted for an unpaired chat user.
        self.understand = understand
        self.sessions: Dict[str, Dict[str, Any]] = {}

    # --- chat sessions ---------------------------------------------------------------

    def start_session(self, chat_user: str) -> Reply:
        self.sessions[chat_user] = {"last_item": None}
        paired = self.store.get(chat_user)
        if paired:
            return Reply("Hi — you're paired as %s. Try `what needs me this week?`"
                         % describe_actor(paired["actor"]))
        return Reply(HELP)

    def end_session(self, chat_user: str) -> None:
        self.sessions.pop(chat_user, None)

    # --- one message -----------------------------------------------------------------

    def route(self, chat_user: str, text: Optional[str] = None,
              selection: Optional[Mapping[str, Any]] = None) -> Union[Reply, Route]:
        command = from_selection(selection) if selection is not None else parse(text)
        session = self.sessions.setdefault(chat_user, {"last_item": None})
        run_id = uuid.uuid4().hex[:12]
        if (command.name == "unknown" and selection is None and session.get("last_item")
                and (text or "").strip().lower().startswith("why")):
            # "why was this held?" right after reviewing an item: a read, so context is fine.
            command = Command("why", item_id=session["last_item"], text=(text or "").strip()[:1000])
        self._step(run_id, command, "button" if selection is not None else "typed")

        if command.name == "help":
            return Reply(HELP)
        if command.name == "pair":
            return self._pair(chat_user, command.text or "")

        paired = self.store.get(chat_user)
        note = None
        if command.name == "unknown" and paired is not None and selection is None and self.understand:
            read = self._understand(chat_user, paired, text or "", session, run_id)
            if isinstance(read, Reply):
                return read
            if read is not None:
                command, note = read.command, "_(I read that as `%s`.)_" % read.line
        if command.name == "unknown":
            hint = ("%s\n\n" % command.problem) if command.problem else ""
            return Reply("%sI only understand a few exact commands. Send `help` to see them."
                         % hint, outcome=INVALID)
        if paired is None:
            return Reply(NOT_PAIRED, outcome=UNPAIRED)
        if command.name == "unpair":
            return self._unpair(chat_user, paired)
        if command.name == "whoami":
            return self._whoami(chat_user, paired)

        if command.item_id:
            session["last_item"] = command.item_id
        specialist = command.specialist
        if specialist not in SPECIALISTS:        # pragma: no cover - grammar guarantees it
            return Reply(HELP)
        self.feed.step(run_id, FEED_NAME, "route", "to the %s agent" % specialist, _exc(command.item_id))
        return Route(specialist, {"request_id": str(uuid.uuid4()), "run_id": run_id, "chat_user": chat_user,
                                  "token": paired["token"], "command": command.as_dict()}, command, note)

    def _step(self, run_id: str, command: Command, how: str) -> None:
        """The front desk's own step: what the message was, as a command. A
        pairing code, a reason or an answer is never put on the (public) feed."""
        if command.name in ("act", "review", "why", "investigate"):
            what = "%s #%s" % (command.verb or command.name, command.item_id)
        elif command.name == "lease":
            what = "lease %s" % command.lease_ref
        else:
            what = command.name
        self.feed.step(run_id, FEED_NAME, how, what, _exc(command.item_id))

    def _understand(self, chat_user: str, paired: Mapping[str, Any], text: str,
                    session: Dict[str, Any], run_id: str) -> Union[Reply, Reading, None]:
        """Ask ASI:One's model what an unparsed message meant. A read comes
        back as a Reading to route; an action comes back as a Reply that shows
        the exact command and runs nothing."""
        try:
            items = self.api.paired(paired["token"], chat_user).items(limit=200)["items"]
        except ApiError as exc:
            if exc.unpaired:
                self.store.drop(chat_user)
                return Reply("This chat's pairing has expired or was revoked. " + NOT_PAIRED,
                             outcome=UNPAIRED)
            items = []
        reading = self.understand(text, items, session.get("last_item"))
        if reading is None:
            self.feed.step(run_id, FEED_NAME, "asi1", "no reading")
            return None
        self.feed.step(run_id, FEED_NAME, "asi1", "read as: %s" % render_safe(reading),
                       _exc(reading.command.item_id))
        if not reading.is_action:
            return reading
        if reading.command.item_id:
            session["last_item"] = reading.command.item_id
        if not reading.complete:
            return Reply("That sounds like an action, and I never act on my reading of a message. "
                         "To do it, send it in this form, with your own words in place of the brackets:"
                         "\n\n`%s`" % reading.line)
        return Reply("That sounds like an action, and I never act on my reading of a message. "
                     "If it's what you want, send exactly:\n\n`%s`\n\nor press the button below. "
                     "Lease Desk checks it against your role and region either way." % reading.line,
                     card=suggested_action_card(reading.command, reading.line))

    def finish(self, chat_user: str, route: Route, reply: Optional[Mapping[str, Any]]) -> Reply:
        if reply is None:
            return Reply("The %s agent didn't answer in time. Nothing was changed by me; "
                         "try again in a moment." % route.specialist, outcome=ERROR)
        out = Reply.from_dict(reply)
        if out.outcome == UNPAIRED:
            self.store.drop(chat_user)
        if route.note:
            out.text = "%s\n\n%s" % (route.note, out.text)
        return out

    def handle(self, chat_user: str, text: Optional[str] = None,
               selection: Optional[Mapping[str, Any]] = None) -> Reply:
        """route() + dispatch + finish(), synchronously (tests, local runs)."""
        routed = self.route(chat_user, text, selection)
        if isinstance(routed, Reply):
            return routed
        return self.finish(chat_user, routed, self.dispatch(routed.specialist, routed.request))

    # --- the desk's own commands -----------------------------------------------------

    def _pair(self, chat_user: str, code: str) -> Reply:
        try:
            claim = self.api.claim(code, chat_user)
        except ApiError as exc:
            if exc.status in (400, 422):
                return Reply(BAD_CODE, outcome=INVALID)
            return Reply("Pairing failed (%s). Try again in a moment." % exc.detail, outcome=ERROR)
        kept = remembered(claim)
        self.store.put(chat_user, kept)
        return Reply("Paired. You're acting as **%s** until %s. Lease Desk checks every action "
                     "against that role and records it, refusals included. Send `unpair` to stop."
                     % (describe_actor(kept["actor"]), kept["expires_at"][:10]))

    def _unpair(self, chat_user: str, paired: Mapping[str, Any]) -> Reply:
        try:
            self.api.paired(paired["token"], chat_user).unpair()
        except ApiError as exc:
            if not exc.unpaired:
                return Reply("Couldn't unpair (%s); try again, or revoke it in the web app."
                             % exc.detail, outcome=ERROR)
        self.store.drop(chat_user)
        return Reply("Unpaired. This chat can no longer see or change anything in Lease Desk.")

    def _whoami(self, chat_user: str, paired: Mapping[str, Any]) -> Reply:
        try:
            info = self.api.paired(paired["token"], chat_user).pairing()
        except ApiError as exc:
            if exc.unpaired:
                self.store.drop(chat_user)
                return Reply("This chat's pairing has expired or was revoked. " + NOT_PAIRED,
                             outcome=UNPAIRED)
            return Reply("Couldn't check (%s)." % exc.detail, outcome=ERROR)
        return Reply("Paired as **%s** until %s." % (describe_actor(info["actor"]),
                                                     str(info["expires_at"])[:16]))


def _exc(item_id: Optional[int]) -> str:
    return "exc_%d" % item_id if item_id else ""


def render_safe(reading: Reading) -> str:
    """A reading for the public feed: the command without its free text."""
    c = reading.command
    if c.name == "act":
        return "%s #%d" % (c.verb, c.item_id)
    return render(c) or c.name


def local_dispatch(api: LeaseDeskClient, feed: Optional[Feed] = None) -> Dispatch:
    """Call the specialists' logic in-process: the same handle_request the
    uAgents specialists run, minus the network hop."""
    from . import approvals_agent, investigation_agent, rulebook_agent

    handlers = {APPROVALS: approvals_agent.handle_request, RULEBOOK: rulebook_agent.handle_request,
                INVESTIGATION: investigation_agent.handle_request}

    def dispatch(specialist: str, request: Dict[str, Any]) -> Dict[str, Any]:
        if specialist == DESK or specialist not in handlers:   # pragma: no cover
            raise ValueError("no specialist %r" % specialist)
        return handlers[specialist](request, api, feed)

    return dispatch


def main() -> None:  # pragma: no cover - needs uagents and the network
    from .runtime import run_front_desk

    run_front_desk()


if __name__ == "__main__":  # pragma: no cover
    main()
