"""The uAgents message models between the front desk and the specialists.

Imported only by runtime.py, so the rest of the package (and the test suite)
runs without uagents installed. The payload is protocol.py's plain dicts,
JSON-encoded: one schema digest for every command, and nothing in a message
the specialists cannot re-validate.
"""

from typing import Optional

from uagents import Model, Protocol

SPECIALIST_PROTOCOL = "LeaseDeskSpecialist"
SPECIALIST_PROTOCOL_VERSION = "0.1.0"


class SpecialistRequest(Model):
    request_id: str
    chat_user: str
    token: str          # the chat user's scoped pairing token; the API checks it on every call
    command_json: str   # grammar.Command.as_dict(), re-validated by Command.from_dict


class SpecialistReply(Model):
    request_id: str
    text: str
    outcome: str
    card_json: Optional[str] = None
    audit_seq: Optional[int] = None


def specialist_protocol() -> Protocol:
    return Protocol(name=SPECIALIST_PROTOCOL, version=SPECIALIST_PROTOCOL_VERSION)
