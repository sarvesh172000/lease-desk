"""investigation_agent: finds out why a charge is off.

    investigate 42          (or "why is 42 off?", "look into exc_42")

Runs POST /api/exceptions/exc_42/investigate as the paired person. The API
streams the investigation as frames — searching, found (one per ranked
source) or not_found, remeasured (only when the engine recorded balances
before and after), complete, and error when the mailbox could not be
searched — and this agent records each frame on the live feed the moment it
arrives, under its own name and the chat message's run id, then answers with
what was found, the remeasurement and the proposed entries.

An investigation proposes; it never posts. The reply ends with the review
card for the item, so approving is still a separate, typed (or pressed)
command that the approvals agent carries out under can().

Every figure is the API's: this agent formats, it does not add, net or round
anything the engine did not.

Run it:   python -m agents_fetch.run             (all four agents; README.md)
Logic:    handle(client, command, feed, run_id) -> Reply, no uAgents needed.
"""

from typing import Any, Dict, List, Mapping, Optional

import httpx

from .cards import held_item_card
from .client import ApiError, LeaseDeskClient, PairedClient
from .grammar import Command
from .live import Feed
from .protocol import ERROR, INVALID, NOT_FOUND, REFUSED, UNPAIRED, Reply

AGENT_NAME = "lease_desk_investigation"
DESCRIPTION = ("Finds out why a Northbay Coffee landlord charge disagrees with its lease: searches the mailbox "
               "for an amendment or side letter, and has the engine remeasure the lease if it changed. "
               "Proposes, never posts. Reached through the Northbay Lease Desk agent.")
FEED_NAME = "investigation"


def _money(v: Any) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    return "%s$%s" % ("+" if n > 0 else "−" if n < 0 else "", format(abs(n), ",.2f"))


def _clip(s: Any, n: int = 280) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def frame_line(f: Mapping[str, Any]) -> str:
    """One frame as a line on the live feed."""
    stage = f.get("stage")
    if stage == "found":
        return "%s: %s" % (f.get("source") or f.get("doc_id") or "document", _clip(f.get("quote"), 200))
    if stage == "remeasured":
        return "liability %s, ROU %s" % (_money(f.get("liability_delta")), _money(f.get("rou_delta")))
    if stage == "complete":
        return "%s entries proposed%s" % (f.get("entries", 0), ", balanced" if f.get("balanced") else "")
    return str(f.get("message") or stage or "")


def summarize(item_id: int, frames: List[Mapping[str, Any]]) -> str:
    found = [f for f in frames if f.get("stage") == "found"]
    remeasured = next((f for f in frames if f.get("stage") == "remeasured"), None)
    complete = next((f for f in frames if f.get("stage") == "complete"), None)
    errors = [str(f.get("message") or "the investigation could not run")
              for f in frames if f.get("stage") == "error"]

    lines = ["**Investigation · #%d**" % item_id, ""]
    if found:
        lines.append("Found what explains it:")
        for f in found:
            lines.append("- **%s**%s: “%s”" % (
                f.get("source") or f.get("doc_id") or "a document",
                " (trust rank %s)" % f["trust_rank"] if f.get("trust_rank") else "", _clip(f.get("quote"))))
    else:
        lines.append("Nothing in the mailbox explains this variance, so the lease stands as written.")
    if remeasured:
        lines += ["", "The lease changed, so the engine remeasured it: liability %s, ROU asset %s." % (
            _money(remeasured.get("liability_delta")), _money(remeasured.get("rou_delta")))]
    if complete and complete.get("entries"):
        lines.append("%d adjusting entr%s proposed%s." % (
            complete["entries"], "y" if complete["entries"] == 1 else "ies",
            ", balanced" if complete.get("balanced") else ""))
    for e in errors:
        lines += ["", "Note: %s" % e]
    lines += ["", "Nothing has been posted. To act, send e.g. `uphold %d <reason>` or `hold %d <reason>`, "
                  "or use the card's buttons." % (item_id, item_id)]
    return "\n".join(lines)


def investigate(client: PairedClient, item_id: int, feed: Feed, run_id: str) -> Reply:
    exc_id = "exc_%d" % item_id
    # The item first, through the items API, which scopes by region and
    # entity: /api/exceptions does not, and an investigation may run a model
    # and record what it finds, so nobody investigates what they cannot see.
    detail = client.item(item_id)
    if (detail.get("item") or {}).get("kind") != "CHARGE_CHECK":
        return Reply("#%d isn't a charge check, so there is nothing to investigate." % item_id,
                     outcome=INVALID)
    feed.step(run_id, FEED_NAME, "start", "investigating %s" % exc_id, exc_id)
    frames: List[Dict[str, Any]] = []
    try:
        for frame in client.investigate(item_id):
            frames.append(frame)
            feed.step(run_id, FEED_NAME, str(frame.get("stage") or "frame"), frame_line(frame), exc_id)
    except httpx.HTTPError as exc:
        feed.step(run_id, FEED_NAME, "error", "stream broke off", exc_id)
        if not frames:
            return Reply("The investigation stream broke off (%s). Nothing was changed." % exc, outcome=ERROR)
        frames.append({"stage": "error", "message": "the stream broke off before the end"})
    try:
        card = held_item_card(client.item(item_id))     # re-read: allowed actions as of now
    except ApiError:
        card = None          # the findings stand without the card
    return Reply(summarize(item_id, frames), card=card)


def handle(client: PairedClient, command: Command, feed: Optional[Feed] = None, run_id: str = "") -> Reply:
    if command.name != "investigate" or not command.item_id:
        return Reply("The investigation agent only investigates an item.", outcome=INVALID)
    feed = feed or Feed()
    try:
        return investigate(client, command.item_id, feed, run_id)
    except ApiError as exc:
        feed.step(run_id, FEED_NAME, "error", "Lease Desk answered %d" % exc.status, "exc_%d" % command.item_id)
        if exc.unpaired:
            return Reply("This chat's pairing has expired or was revoked. Pair again from Today.",
                         outcome=UNPAIRED)
        if exc.refused:
            return Reply("Lease Desk refused: %s" % exc.detail, outcome=REFUSED)
        if exc.status == 404:
            return Reply("There is no item #%d that you can see, so there is nothing to investigate."
                         % command.item_id, outcome=NOT_FOUND)
        return Reply("Lease Desk couldn't investigate that (%s)." % exc.detail, outcome=ERROR)


def handle_request(request: Mapping[str, Any], api: LeaseDeskClient, feed: Optional[Feed] = None) -> Dict[str, Any]:
    """One SpecialistRequest (protocol.py) -> one SpecialistReply dict."""
    command = Command.from_dict(request.get("command") or {})
    reply = handle(api.paired(str(request.get("token") or ""), str(request.get("chat_user") or "")),
                   command, feed, str(request.get("run_id") or ""))
    reply.request_id = request.get("request_id")
    return reply.as_dict()


def main() -> None:  # pragma: no cover - needs uagents and the network
    from .runtime import run_specialist

    run_specialist("investigation", AGENT_NAME, DESCRIPTION, handle_request)


if __name__ == "__main__":  # pragma: no cover
    main()
