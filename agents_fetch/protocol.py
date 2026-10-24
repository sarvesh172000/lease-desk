"""What the four agents say to each other, as plain data.

The front desk turns a chat message into a Command (grammar.py) and, for
anything but pairing and help, sends a SpecialistRequest to the rulebook,
investigation or approvals agent over agent messaging. The specialist calls the Lease Desk API
with the paired person's token and answers with a SpecialistReply. In the
uAgents runtime these dicts ride inside the `wire.py` models; in tests they
are passed directly, so the logic is the same code either way.

    request = {"request_id", "run_id", "chat_user", "token", "command": Command.as_dict()}
    reply   = {"request_id", "text", "card": {"card_kind", "payload", "metadata"} | None,
               "outcome": "ok" | "refused" | "not_found" | "unpaired" | "error" | "invalid",
               "audit_seq": int | None}
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

OK, REFUSED, NOT_FOUND, UNPAIRED, ERROR, INVALID = (
    "ok", "refused", "not_found", "unpaired", "error", "invalid")


@dataclass
class Reply:
    text: str
    card: Optional[Dict[str, Any]] = None
    outcome: str = OK
    audit_seq: Optional[int] = None
    request_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"request_id": self.request_id, "text": self.text, "card": self.card,
                "outcome": self.outcome, "audit_seq": self.audit_seq}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Reply":
        card = data.get("card")
        return cls(text=str(data.get("text") or ""), card=card if isinstance(card, dict) else None,
                   outcome=str(data.get("outcome") or OK),
                   audit_seq=data.get("audit_seq") if isinstance(data.get("audit_seq"), int) else None,
                   request_id=data.get("request_id"))
