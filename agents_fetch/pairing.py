"""Where the front desk keeps each chat user's pairing token.

The server holds the pairing (hashes, expiry, revocation; backend
app/auth/pairing.py). The front desk only needs to remember, per chat user,
the bearer token the claim returned and who it acts as, so it can call the
API for them on the next message. A token is useless without the chat user
it is bound to, expires in seven days, and is revoked by `unpair` or from the
web app; a 401 from the API makes the front desk forget it.

    MemoryPairingStore()          tests, and a single local process
    KeyValuePairingStore(store)   the uAgents agent's `ctx.storage` (persisted
                                  by uAgents next to the agent)
"""

from typing import Any, Dict, Optional, Protocol

_PREFIX = "pairing:"


class PairingStore(Protocol):
    def get(self, chat_user: str) -> Optional[Dict[str, Any]]: ...

    def put(self, chat_user: str, pairing: Dict[str, Any]) -> None: ...

    def drop(self, chat_user: str) -> None: ...


class MemoryPairingStore:
    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}

    def get(self, chat_user: str) -> Optional[Dict[str, Any]]:
        return self._data.get(chat_user)

    def put(self, chat_user: str, pairing: Dict[str, Any]) -> None:
        self._data[chat_user] = dict(pairing)

    def drop(self, chat_user: str) -> None:
        self._data.pop(chat_user, None)


class KeyValuePairingStore:
    """Over anything with get/set/remove, such as uagents' KeyValueStore."""

    def __init__(self, kv: Any) -> None:
        self._kv = kv

    def get(self, chat_user: str) -> Optional[Dict[str, Any]]:
        value = self._kv.get(_PREFIX + chat_user)
        return value if isinstance(value, dict) and value.get("token") else None

    def put(self, chat_user: str, pairing: Dict[str, Any]) -> None:
        self._kv.set(_PREFIX + chat_user, dict(pairing))

    def drop(self, chat_user: str) -> None:
        if self._kv.has(_PREFIX + chat_user):
            self._kv.remove(_PREFIX + chat_user)


def remembered(claim: Dict[str, Any]) -> Dict[str, Any]:
    """What to keep from a POST /api/pairing/claim response."""
    actor = claim.get("actor") or {}
    return {"token": claim["token"], "pairing_id": claim.get("pairing_id"),
            "expires_at": str(claim.get("expires_at")),
            "actor": {k: actor.get(k) for k in ("id", "name", "role", "region_id", "entity_id")}}


def describe_actor(actor: Dict[str, Any]) -> str:
    role = (actor.get("role") or "").replace("_", " ")
    scope = actor.get("region_id") or actor.get("entity_id") or "all entities"
    return "%s (%s, %s)" % (actor.get("name") or actor.get("id"), role, scope)
