"""The coordinator's view of the specialists: the same calls the desk makes on
the API, answered by other agents instead.

The desk does not know whether it is talking to Lease Desk directly
(api.LeaseDeskAPI) or through the specialists (this class). Here every call
becomes a request to one specialist, through `call(agent, op, args)`, which
agents.py implements with uAgents' send_and_receive. A refusal comes back as
the DeskError it was at the specialist, with its status, so the desk relays
a 403 exactly as it would have directly.
"""

from typing import Any, Callable, Dict, Iterator, List, Optional

from .api import DeskError

Call = Callable[[str, str, Dict[str, Any]], Dict[str, Any]]


class RemoteDesk:
    # The specialists record their own steps on the live feed, so the desk
    # must not record them a second time.
    delegates = True

    def __init__(self, call: Call):
        self.call = call
        self.actor: Optional[Dict[str, Any]] = None

    def _ask(self, agent: str, op: str, **args: Any) -> Any:
        reply = self.call(agent, op, args)
        if not reply.get("ok"):
            raise DeskError(reply.get("error") or "the %s agent could not do that" % agent, reply.get("status"))
        return reply.get("data")

    def exceptions(self) -> List[Dict[str, Any]]:
        return self._ask("reconciliation", "open")

    def exception(self, exc_id: str) -> Dict[str, Any]:
        return self._ask("reconciliation", "detail", exception_id=exc_id)

    def investigate(self, exc_id: str, run_id: str = "") -> Iterator[Dict[str, Any]]:
        return iter(self._ask("investigation", "investigate", exception_id=exc_id, run_id=run_id))

    def approve(self, exc_id: str, reason: Optional[str] = None, run_id: str = "",
                item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._act("approve", exc_id, reason, run_id, item)

    def hold(self, exc_id: str, reason: Optional[str] = None, run_id: str = "",
             item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._act("hold", exc_id, reason, run_id, item)

    def _act(self, op: str, exc_id: str, reason: Optional[str], run_id: str,
             item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        data = self._ask("approvals", op, exception_id=exc_id, reason=reason, run_id=run_id, item=item)
        self.actor = data.get("actor")
        return data["result"]
