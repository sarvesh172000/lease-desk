"""What each specialist agent does with a request, without the agent framework.

Three specialists sit behind the coordinator, each with one job and only the
operations that job needs:

    reconciliation  open, detail        what's on hold, and one exception's evidence
    investigation   investigate         search the mailbox for what explains a variance
    approvals       approve, hold       sign off as the configured person

A request is `(op, args)`; a reply is a dict, `{"ok": True, "data": ...}` or
`{"ok": False, "status": <http status or None>, "error": "..."}`, so a refusal
from Lease Desk (a 403 on record, a 409 on the wrong state) travels back to
the coordinator intact instead of turning into a generic failure.

The investigation and approvals agents record their own work on the live
feed as they do it: the investigation frame by frame while it streams, the
approval the moment Lease Desk answers. That is what makes the feed show
several agents working, not one agent narrating after the fact.

agents.py wraps `handle` in uAgents; tests/test_fetch_specialists.py drives it directly.
"""

from typing import Any, Dict

from .api import DeskError, LeaseDeskAPI
from .desk import frame_line
from .live import Feed

OPS = {
    "reconciliation": ("open", "detail"),
    "investigation": ("investigate",),
    "approvals": ("approve", "hold"),
}


def handle(agent: str, api: LeaseDeskAPI, feed: Feed, op: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if op not in OPS.get(agent, ()):
        return {"ok": False, "status": 400, "error": "the %s agent does not do %r" % (agent, op)}
    try:
        return {"ok": True, "data": _do(agent, api, feed, op, args)}
    except DeskError as exc:
        return {"ok": False, "status": exc.status, "error": str(exc)}
    except (KeyError, TypeError) as exc:
        return {"ok": False, "status": 400, "error": "bad request: %s" % exc}


def _do(agent: str, api: LeaseDeskAPI, feed: Feed, op: str, args: Dict[str, Any]) -> Any:
    run_id = args.get("run_id") or ""
    if op == "open":
        return api.exceptions()
    if op == "detail":
        return api.exception(args["exception_id"])
    if op == "investigate":
        exc_id = args["exception_id"]
        frames = []
        for frame in api.investigate(exc_id):
            feed.step(run_id, agent, frame.get("stage") or "frame", frame_line(frame), exc_id)
            frames.append(frame)
        return frames
    # approve | hold
    exc_id = args["exception_id"]
    act = api.approve if op == "approve" else api.hold
    result = act(exc_id, args.get("reason"))
    who = (api.actor or {}).get("name", "unknown")
    feed.step(run_id, agent, "action", "%s by %s: %s" % (
        "Approved" if op == "approve" else "Put on hold", who, result.get("state")), exc_id)
    item = args.get("item") or {"exception_id": exc_id}
    feed.status(item, result.get("status") or "", who)
    return {"result": result, "actor": api.actor}
