"""approvals_agent: the paired person's queue, from chat.

    what needs me this week?      open items and questions for the paired actor
    review 42                     a held item: amounts, sources, trust, why — as an Interactive Card
    why 42 [question]             POST /api/items/42/why
    answer 42 <text>              POST /api/items/42/actions/answer
    approve|uphold|hold|reject|resume 42 [reason]

Every action is POST /api/items/{id}/actions/{action} as the paired person.
The agent does not pre-check anything: the API runs can(), and a refusal is
a 403 whose allowed = false event is already in the audit stream. The reply
says it was refused, why, and which audit event recorded it — the same event
the web app's audit timeline shows.

Run it:   python -m agents_fetch.approvals_agent      (README.md has the env vars)
Logic:    handle(client, command) -> Reply, no uAgents needed.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional

from .cards import held_item_card, inbox_card, money, source_rows, trust_text
from .client import ApiError, LeaseDeskClient, PairedClient
from .grammar import Command
from .protocol import ERROR, INVALID, NOT_FOUND, REFUSED, UNPAIRED, Reply

AGENT_NAME = "lease_desk_approvals"
DESCRIPTION = ("Lists and answers the open lease-accounting items and questions of the person paired "
               "to this chat, under their Lease Desk permissions. Reached through Northbay Lease Desk.")

OPEN_STATES = ("NEEDS_INFO", "HELD", "PROPOSED")
WEEK = timedelta(days=7)
MAX_LISTED = 10
MAX_DETAILS = 25        # NEEDS_INFO items whose questions are read for due dates

_PAST = {"approve": "approved", "hold": "held", "resume": "resumed", "reject": "rejected",
         "answer": "answered"}


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def inbox(client: PairedClient, now: Optional[datetime] = None) -> Reply:
    now = now or datetime.now(timezone.utc)
    me = client.me()
    queue = client.items(limit=500)["items"]
    open_items = [i for i in queue if i["state"] in OPEN_STATES]

    rows: List[Dict[str, Any]] = []
    details_read = 0
    for item in open_items:
        row = {"item": item, "question": None, "due": None}
        if item["state"] == "NEEDS_INFO" and details_read < MAX_DETAILS:
            details_read += 1
            detail = client.item(item["id"])
            mine = [q for q in detail.get("questions") or []
                    if not q.get("answer") and q.get("asked_to") == me["id"]]
            if mine:
                row["question"] = mine[-1]
                row["due"] = _parse_ts(mine[-1].get("due_at"))
        rows.append(row)

    def urgency(r):
        due = r["due"]
        return (0 if r["question"] else 1 if r["item"]["state"] == "HELD" else 2,
                due or now + timedelta(days=3650), -(r["item"].get("amount") or 0))

    rows.sort(key=urgency)
    this_week = [r for r in rows if r["due"] is None or r["due"] <= now + WEEK]
    if not this_week:
        return Reply("Nothing needs you this week, %s." % me["name"])

    at_stake = sum(abs(r["item"].get("amount") or 0) for r in this_week)
    lines = ["**%d open for you, %s** (%s at stake)" % (len(this_week), me["name"], money(at_stake))]
    for r in this_week[:MAX_LISTED]:
        it = r["item"]
        lines.append("- **#%d** %s · %s · %s — %s" % (
            it["id"], it["state"], it.get("clinic_id") or "—",
            money(it.get("amount")) if it.get("amount") is not None else "—", it.get("title")))
        if r["question"]:
            due = r["due"]
            when = ("" if due is None else " — **overdue**" if due < now
                    else " — due %s" % due.strftime("%a %b %d"))
            lines.append("  - question for you: “%s”%s" % (r["question"]["body"], when))
    if len(this_week) > MAX_LISTED:
        lines.append("_…and %d more in the web app._" % (len(this_week) - MAX_LISTED))
    lines.append("Send `review <number>` to see one, or `answer <number> <text>`.")
    return Reply("\n".join(lines), card=inbox_card([r["item"] for r in this_week]))


def review(client: PairedClient, item_id: int) -> Reply:
    detail = client.item(item_id)
    try:
        why = client.why(item_id, "why is this item where it is?")
    except ApiError:
        why = None
    item, evidence = detail["item"], detail.get("evidence") or {}
    lines = ["**#%d · %s** — %s" % (item_id, item["state"], item.get("title"))]
    if evidence.get("billed") is not None:
        lines.append("Billed %s; the lease supports %s." % (money(evidence["billed"]),
                                                             money(evidence.get("supported"))))
    for row in source_rows(why, evidence):
        lines.append("- %s: %s" % (row["label"], row["value"]))
    trust = trust_text(evidence)
    if trust:
        lines.append("Trust: %s" % trust)
    if why and why.get("answer"):
        lines.append("Why: %s" % why["answer"])
    allowed = detail.get("allowed_actions") or []
    lines.append("You may: %s." % (", ".join(allowed) if allowed else "nothing on this item (read only)"))
    return Reply("\n".join(lines), card=held_item_card(detail, why))


def explain(client: PairedClient, item_id: int, question: Optional[str]) -> Reply:
    why = client.why(item_id, question)
    return Reply("**Why #%d** — %s" % (item_id, why["answer"]))


def _denial_seq(client: PairedClient, me_id: str, item_id: int, action: str) -> Optional[int]:
    """The allowed = false event the refused press just wrote."""
    try:
        events = client.audit("work_item", str(item_id), limit=50)["events"]
    except ApiError:
        return None
    for e in reversed(events):
        if e["actor_id"] == me_id and not e["allowed"] and e["action"] == action:
            return e["seq"]
    return None


def act(client: PairedClient, command: Command) -> Reply:
    item_id, action, verb = command.item_id, command.action, command.verb
    try:
        result = client.act(item_id, action, command.text)
    except ApiError as exc:
        if exc.refused:
            me = client.me()
            seq = _denial_seq(client, me["id"], item_id, action)
            where = (" as audit event #%d (allowed = false)" % seq if seq is not None
                     else " in the audit trail")
            return Reply("**Refused.** Lease Desk would not let you %s #%d: %s.\n"
                         "Nothing changed. The refusal is recorded%s, and shows in the web app's "
                         "audit timeline." % (verb, item_id, exc.detail, where),
                         outcome=REFUSED, audit_seq=seq)
        if exc.status == 404:
            return Reply("There is no item #%d." % item_id, outcome=NOT_FOUND)
        if exc.status == 409:
            return Reply("#%d can't be %s from where it is now: %s" % (item_id, _PAST[action], exc.detail),
                         outcome=INVALID)
        if exc.status == 422:
            return Reply("Lease Desk needs more to %s #%d: %s" % (verb, item_id, exc.detail),
                         outcome=INVALID)
        raise
    lines = ["Done: #%d %s — now **%s**." % (item_id, _PAST[action], result["state"])]
    posting = result.get("posting")
    if posting:
        if posting["status"] == "posted":
            lines.append("Posted journal entry #%s for %s%s." % (
                posting.get("journal_entry_id"), money(posting.get("amount")),
                "; %s disputed stays out of the ledger" % money(posting["disputed"])
                if posting.get("disputed") else ""))
        elif posting["status"] == "closed":
            lines.append("Nothing was owed, so nothing posted; the item is closed.")
        else:
            lines.append("The approval stands; posting is pending (%s)." % posting.get("error"))
    return Reply("\n".join(lines))


def handle(client: PairedClient, command: Command, now: Optional[datetime] = None) -> Reply:
    try:
        if command.name == "inbox":
            return inbox(client, now)
        if command.name == "review":
            return review(client, command.item_id)
        if command.name == "why":
            return explain(client, command.item_id, command.text)
        if command.name == "act":
            return act(client, command)
        return Reply("The approvals agent does not do that.", outcome=INVALID)
    except ApiError as exc:
        if exc.unpaired:
            return Reply("This chat's pairing has expired or was revoked. Pair again from Today.",
                         outcome=UNPAIRED)
        if exc.status == 404:
            return Reply("There is no item #%s that you can see." % command.item_id, outcome=NOT_FOUND)
        if exc.refused:
            return Reply("Lease Desk refused: %s" % exc.detail, outcome=REFUSED)
        return Reply("Lease Desk couldn't do that (%s)." % exc.detail, outcome=ERROR)


def handle_request(request: Mapping[str, Any], api: LeaseDeskClient) -> Dict[str, Any]:
    """One SpecialistRequest (protocol.py) -> one SpecialistReply dict."""
    command = Command.from_dict(request.get("command") or {})
    reply = handle(api.paired(str(request.get("token") or ""), str(request.get("chat_user") or "")),
                   command)
    reply.request_id = request.get("request_id")
    return reply.as_dict()


def main() -> None:  # pragma: no cover - needs uagents and the network
    from .runtime import run_specialist

    run_specialist("approvals", AGENT_NAME, DESCRIPTION, handle_request)


if __name__ == "__main__":  # pragma: no cover
    main()
