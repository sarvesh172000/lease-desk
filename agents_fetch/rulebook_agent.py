"""rulebook_agent: answers lease questions with citations.

    "what is Clinic 03's escalation and where does it say so?"

The answer comes from GET /api/leases/{id}/versions: each term carries the
page and the sentence it was read from, so every value in the reply is
followed by where the lease says it. A term whose quote could not be found on
the page is said to be unverified, never given a guessed page. When a later
version (an amendment) changed the term, the reply says what the earlier
version said too.

Run it:   python -m agents_fetch.rulebook_agent       (README.md has the env vars)
Logic:    handle(client, command) -> Reply, no uAgents needed.
"""

import json
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .client import ApiError, LeaseDeskClient, PairedClient
from .grammar import TOPICS, Command
from .live import Feed, record_step
from .protocol import ERROR, INVALID, NOT_FOUND, REFUSED, UNPAIRED, Reply

FEED_NAME = "rulebook"
AGENT_NAME = "lease_desk_rulebook"
DESCRIPTION = ("Answers questions about Northbay PT's leases (rent, escalation, CAM, term) with the "
               "page and quote each answer comes from. Reached through the Northbay Lease Desk agent.")


def _digits(value: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*$", value or "")
    return int(m.group(1)) if m else None


def resolve_lease(client: PairedClient, ref: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """(lease_id, the clinic's leases) for LEASE-xx or CLINIC-nn."""
    if ref.upper().startswith("LEASE-"):
        return ref.upper(), []
    want = _digits(ref)
    matches = [row for row in client.leases()
               if row.get("clinic_id") and _digits(row["clinic_id"]) == want]
    matches.sort(key=lambda r: r["lease_id"])
    return (matches[0]["lease_id"] if matches else None), matches


def _value(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(", ", ": "))
    return str(value)


def _cite(term: Mapping[str, Any]) -> str:
    if term.get("page") is None or not term.get("quote"):
        return "_not located in the document — treat as unverified_"
    cite = "page %s: “%s”" % (term["page"], " ".join(str(term["quote"]).split()))
    extras = []
    if term.get("document_id"):
        extras.append("document %s…" % term["document_id"][:12])
    if term.get("confidence") is not None:
        extras.append("confidence %.2f" % float(term["confidence"]))
    return cite + (" (%s)" % ", ".join(extras) if extras else "")


def _matches(field: str, topic: Optional[str]) -> bool:
    if topic is None:
        return True
    return any(word in field.lower() for word in TOPICS.get(topic, (topic,)))


def answer(client: PairedClient, command: Command) -> Reply:
    lease_id, clinic_leases = resolve_lease(client, command.lease_ref or "")
    if lease_id is None:
        return Reply("I couldn't find a lease for %s that you can see." % command.lease_ref,
                     outcome=NOT_FOUND)
    versions = client.lease_versions(lease_id)
    if not versions:
        return Reply("%s has no abstracted versions yet, so there is nothing to cite." % lease_id,
                     outcome=NOT_FOUND)

    confirmed = [v for v in versions if v.get("confirmed")]
    current = (confirmed or versions)[-1]
    terms = [t for t in current.get("terms") or [] if _matches(t.get("field", ""), command.topic)]
    label = "%s v%s (effective %s%s)" % (lease_id, current["version"], current["effective_from"],
                                         "" if current.get("confirmed") else ", **not yet confirmed**")
    if not terms:
        fields = ", ".join(sorted(t["field"] for t in current.get("terms") or [])) or "none"
        return Reply("%s has no %s term. Terms on file: %s." % (label, command.topic or "", fields),
                     outcome=NOT_FOUND)

    lines = ["**%s**" % label]
    if len(clinic_leases) > 1:
        lines.append("_%s has %d leases; showing %s (%s)._" % (
            command.lease_ref, len(clinic_leases), lease_id,
            ", ".join(r["lease_id"] for r in clinic_leases)))
    earlier = [v for v in versions if v["version"] < current["version"]]
    for t in terms:
        lines.append("- **%s**: %s — %s" % (t["field"], _value(t.get("value")), _cite(t)))
        for v in reversed(earlier):
            old = next((o for o in v.get("terms") or [] if o.get("field") == t["field"]), None)
            if old is not None and old.get("value") != t.get("value"):
                lines.append("  - changed from %s in v%s (%s)" % (_value(old.get("value")), v["version"],
                                                               _cite(old)))
                break
    return Reply("\n".join(lines))


def handle(client: PairedClient, command: Command) -> Reply:
    if command.name != "lease":
        return Reply("The rulebook agent only answers lease questions.", outcome=INVALID)
    try:
        return answer(client, command)
    except ApiError as exc:
        if exc.unpaired:
            return Reply("This chat's pairing has expired or was revoked. Pair again from Today.",
                         outcome=UNPAIRED)
        if exc.refused:
            return Reply("Lease Desk refused: %s" % exc.detail, outcome=REFUSED)
        if exc.status == 404:
            return Reply("Lease Desk has no %s." % command.lease_ref, outcome=NOT_FOUND)
        return Reply("Lease Desk couldn't answer that (%s)." % exc.detail, outcome=ERROR)


def handle_request(request: Mapping[str, Any], api: LeaseDeskClient, feed: Optional[Feed] = None) -> Dict[str, Any]:
    """One SpecialistRequest (protocol.py) -> one SpecialistReply dict, with
    this agent's step on the live feed under the message's run id."""
    command = Command.from_dict(request.get("command") or {})
    reply = handle(api.paired(str(request.get("token") or ""), str(request.get("chat_user") or "")),
                   command)
    reply.request_id = request.get("request_id")
    record_step(feed, str(request.get("run_id") or ""), FEED_NAME, command, reply)
    return reply.as_dict()


def main() -> None:  # pragma: no cover - needs uagents and the network
    from .runtime import run_specialist

    run_specialist("rulebook", AGENT_NAME, DESCRIPTION, handle_request)


if __name__ == "__main__":  # pragma: no cover
    main()
