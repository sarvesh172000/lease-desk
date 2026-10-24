"""Chat pairing: a one-time code links an ASI:One user to an actor.

    mint_code(conn, actor)              -> (code, expires_at)     the web app's Today screen
    claim(conn, code, chat_user)        -> Claimed(token, ...)    the Fetch.ai front desk
    session_for_token(conn, token, cu)  -> PairedSession | None   every API call it makes
    revoke(conn, pairing_id, by)                                  "unpair", from chat or web

The flow (PHASE_3.md group 9):

1. A signed-in person asks for a code (POST /api/pairing/codes). It is eight
   characters from an alphabet without look-alikes (`K7QM-9XDA`), lives ten
   minutes, and minting a new one voids any unclaimed code they had.
2. They send `pair K7QM-9XDA` to the front desk agent in ASI:One.
3. The agent claims it (POST /api/pairing/claim) with the chat user's address.
   One atomic UPDATE: the code must be unclaimed, unrevoked and unexpired, and
   its actor still an active person. A code works once.
4. The claim returns a bearer token (`ldp_...`, seven days) bound to that actor
   and that chat user. The agent sends it as `Authorization: Bearer ...` with
   `X-LeaseDesk-Chat-User`, and `auth.deps.current_actor` turns it into the
   same SessionActor a cookie would, re-read from `actor` on every request.

The token is a *scoped* session: it reaches only PAIRED_ROUTES, the reads and
the item actions the chat workflow needs. It cannot mint pairing codes, list
or revoke other pairings, switch actors, release batches or reset the demo.
Within that scope can() still decides every action, exactly as for the web
app, and a refusal is on the audit stream either way.

Only sha256 hashes of codes and tokens are stored. Pair and unpair are
audit events (subject_type 'pairing'), so the timeline shows when a person
handed their desk to a chat agent and when they took it back.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import FrozenSet, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..work.events import append_event
from .sessions import SessionActor, load_session_actor

CODE_TTL = timedelta(minutes=10)
TOKEN_TTL = timedelta(days=7)
TOKEN_PREFIX = "ldp_"
CHAT_USER_HEADER = "X-LeaseDesk-Chat-User"
# Crockford-style: no 0/O, 1/I/L or U, so a code read off a screen is typed right.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
CODE_LENGTH = 8

# (method, route template) a paired chat session may call. Everything else is
# 403 for it, whatever the actor's role would allow with a cookie.
PAIRED_ROUTES: FrozenSet[Tuple[str, str]] = frozenset({
    ("GET", "/api/auth/me"),
    ("GET", "/api/pairing/me"),
    ("POST", "/api/pairing/me/revoke"),
    ("GET", "/api/items"),
    ("GET", "/api/items/{item_id}"),
    ("GET", "/api/items/{item_id}/allowed-actions"),
    ("POST", "/api/items/{item_id}/actions/{action}"),
    ("GET", "/api/items/{item_id}/why"),
    ("POST", "/api/items/{item_id}/why"),
    ("GET", "/api/leases"),
    ("GET", "/api/leases/{lease_id}/versions"),
    ("GET", "/api/leases/{lease_id}/schedule"),
    ("GET", "/api/exceptions"),
    ("GET", "/api/exceptions/{exc_id}"),
    ("GET", "/api/audit"),
})


class PairingError(ValueError):
    """A claim that cannot succeed. One message for every reason, so a caller
    guessing codes learns nothing about which part was wrong."""


INVALID_CODE = "invalid or expired pairing code"


@dataclass(frozen=True)
class Claimed:
    pairing_id: int
    token: str
    expires_at: datetime
    actor: SessionActor
    chat_user: str


@dataclass(frozen=True)
class PairedSession:
    pairing_id: int
    actor: SessionActor
    chat_user: str
    expires_at: datetime


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_code(raw: str) -> str:
    """What the person typed, as the code was minted: upper case, with spaces
    and dashes dropped. Anything outside the alphabet makes it unmatchable."""
    return "".join(ch for ch in (raw or "").upper() if ch not in " -\t")


def format_code(code: str) -> str:
    return "%s-%s" % (code[:4], code[4:])


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def mint_code(conn: Connection, actor: SessionActor) -> Tuple[str, datetime]:
    """A fresh one-time code for `actor`, formatted for display. Any code they
    minted earlier and never used stops working."""
    conn.execute(text("""
        UPDATE pairing SET revoked_at = now(), revoked_by = :actor
         WHERE actor_id = :actor AND claimed_at IS NULL AND revoked_at IS NULL
    """), {"actor": actor.id})
    code = new_code()
    expires_at = conn.execute(text("""
        INSERT INTO pairing (actor_id, code_hash, code_expires_at)
        VALUES (:actor, :h, now() + make_interval(secs => :ttl))
        RETURNING code_expires_at
    """), {"actor": actor.id, "h": _sha256(code), "ttl": CODE_TTL.total_seconds()}).scalar_one()
    return format_code(code), expires_at


def claim(conn: Connection, raw_code: str, chat_user: str) -> Claimed:
    """Exchange a code for a token, once. The chat user's earlier pairings,
    if any, are revoked: one chat user speaks for one actor at a time."""
    code = normalize_code(raw_code)
    chat_user = (chat_user or "").strip()
    if len(code) != CODE_LENGTH or any(ch not in CODE_ALPHABET for ch in code):
        raise PairingError(INVALID_CODE)
    if not chat_user or len(chat_user) > 200:
        raise PairingError("chat_user must be 1 to 200 characters")

    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = conn.execute(text("""
        UPDATE pairing p
           SET claimed_at = now(), chat_user = :chat_user, token_hash = :token_hash,
               token_expires_at = now() + make_interval(secs => :ttl)
         WHERE p.code_hash = :code_hash AND p.claimed_at IS NULL AND p.revoked_at IS NULL
           AND p.code_expires_at > now()
           AND EXISTS (SELECT 1 FROM actor a WHERE a.id = p.actor_id AND a.active
                                                AND a.role NOT IN ('agent', 'system'))
        RETURNING p.id, p.actor_id, p.token_expires_at
    """), {"chat_user": chat_user, "token_hash": _sha256(token), "code_hash": _sha256(code),
           "ttl": TOKEN_TTL.total_seconds()}).first()
    if row is None:
        raise PairingError(INVALID_CODE)
    actor = load_session_actor(conn, row.actor_id)
    if actor is None:                        # raced a deactivation; the EXISTS saw it active
        raise PairingError(INVALID_CODE)

    superseded = conn.execute(text("""
        UPDATE pairing SET revoked_at = now(), revoked_by = :actor
         WHERE chat_user = :chat_user AND id <> :id AND revoked_at IS NULL
        RETURNING id
    """), {"chat_user": chat_user, "id": row.id, "actor": actor.id}).scalars().all()
    append_event(conn, actor_id=actor.id, action="pair", subject_type="pairing",
                 subject_id=row.id, reason="paired an ASI:One chat user to this actor",
                 evidence={"chat_user": chat_user, "channel": "asi1",
                           "expires_at": row.token_expires_at.isoformat(),
                           "superseded": list(superseded)})
    return Claimed(pairing_id=row.id, token=token, expires_at=row.token_expires_at,
                   actor=actor, chat_user=chat_user)


def is_pairing_token(authorization: Optional[str]) -> bool:
    return bool(authorization) and authorization.strip().lower().startswith("bearer ")


def bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not is_pairing_token(authorization):
        return None
    token = authorization.strip()[len("bearer "):].strip()
    return token if token.startswith(TOKEN_PREFIX) and 16 < len(token) <= 200 else None


def session_for_token(conn: Connection, token: Optional[str],
                      chat_user: Optional[str]) -> Optional[PairedSession]:
    """The live pairing a token names, or None (unknown, expired, revoked,
    wrong chat user, or its actor deactivated). The actor is re-read now."""
    if not token or not chat_user:
        return None
    row = conn.execute(text("""
        SELECT id, actor_id, chat_user, token_expires_at FROM pairing
         WHERE token_hash = :h AND revoked_at IS NULL AND token_expires_at > now()
    """), {"h": _sha256(token)}).first()
    if row is None or not hmac.compare_digest(row.chat_user.encode(), chat_user.strip().encode()):
        return None
    actor = load_session_actor(conn, row.actor_id)
    if actor is None:
        return None
    return PairedSession(pairing_id=row.id, actor=actor, chat_user=row.chat_user,
                         expires_at=row.token_expires_at)


def route_allowed(method: str, route_path: Optional[str]) -> bool:
    return (method.upper(), route_path or "") in PAIRED_ROUTES


def revoke(conn: Connection, pairing_id: int, by: SessionActor, via: str) -> bool:
    """Revoke one of `by`'s own pairings. False when there is no such live
    pairing of theirs (someone else's looks the same as none)."""
    row = conn.execute(text("""
        UPDATE pairing SET revoked_at = now(), revoked_by = :by
         WHERE id = :id AND actor_id = :by AND revoked_at IS NULL
        RETURNING id, chat_user
    """), {"id": pairing_id, "by": by.id}).first()
    if row is None:
        return False
    append_event(conn, actor_id=by.id, action="unpair", subject_type="pairing",
                 subject_id=row.id, reason="pairing revoked from %s" % via,
                 evidence={"chat_user": row.chat_user, "via": via})
    return True


def live_pairings(conn: Connection, actor: SessionActor) -> List[dict]:
    """The actor's claimed, unrevoked, unexpired pairings, newest first."""
    rows = conn.execute(text("""
        SELECT id, chat_user, claimed_at, token_expires_at AS expires_at FROM pairing
         WHERE actor_id = :a AND claimed_at IS NOT NULL AND revoked_at IS NULL
           AND token_expires_at > now()
         ORDER BY claimed_at DESC, id DESC
    """), {"a": actor.id}).mappings().all()
    return [dict(r) for r in rows]
