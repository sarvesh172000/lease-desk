"""The session cookie, and the actor it names.

The cookie holds one thing: an actor id, signed with a timestamp
(itsdangerous `URLSafeTimedSerializer`). There is no server-side session
table. What the signature buys is that nobody can write a cookie naming
someone else; what it does not carry is the actor's role, region or entity.
Those are re-read from `actor` on every request, so deactivating someone or
changing their role takes effect on their very next click, not at expiry.

Cookie attributes: HttpOnly (page scripts cannot read it), SameSite=Lax
(other sites cannot POST with it), twelve-hour lifetime enforced twice, by
the browser's Max-Age and by the signed timestamp, which the browser cannot
extend. Secure is on when `LEASEDESK_COOKIE_SECURE=1`.

Logout deletes the cookie. Because there is no session table a copied cookie
stays valid until it expires; deactivation is the kill switch.
"""

from dataclasses import asdict, dataclass
from typing import Optional

from fastapi import Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import text
from sqlalchemy.engine import Connection

COOKIE_NAME = "leasedesk_session"
MAX_AGE_SECONDS = 12 * 60 * 60
_SALT = "leasedesk.auth.session.v1"     # a cookie signed for another purpose cannot pass as a session


@dataclass(frozen=True)
class SessionActor:
    """The person behind a request. Field-compatible with work/roles.py
    `Actor(id, role, region_id, entity_id)` plus a display name, so the
    swap to `load_actor` is one line."""
    id: str
    name: str
    role: str
    region_id: Optional[str]
    entity_id: Optional[str]

    def public(self) -> dict:
        return asdict(self)


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt=_SALT)


def issue_token(secret: str, actor_id: str) -> str:
    return _serializer(secret).dumps(actor_id)


def read_token(secret: str, token: Optional[str],
               max_age: int = MAX_AGE_SECONDS) -> Optional[str]:
    """The actor id inside a valid, unexpired token; None for anything else
    (missing, tampered, signed with another secret, expired, wrong shape)."""
    if not token:
        return None
    try:
        actor_id = _serializer(secret).loads(token, max_age=max_age)
    except BadSignature:            # SignatureExpired is a subclass
        return None
    return actor_id if isinstance(actor_id, str) and actor_id else None


def set_session_cookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=MAX_AGE_SECONDS, httponly=True,
                        samesite="lax", secure=secure, path="/")


def clear_session_cookie(response: Response, secure: bool) -> None:
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="lax", secure=secure, path="/")


# A person who may hold a session: exists, active, not an agent. The password
# hash is deliberately not selected; only login needs it.
_SESSION_ACTOR = text("""
    SELECT id, name, role, region_id, entity_id FROM actor
    WHERE id = :id AND active AND role <> 'agent'
""")


def load_session_actor(conn: Connection, actor_id: str) -> Optional[SessionActor]:
    row = conn.execute(_SESSION_ACTOR, {"id": actor_id}).first()
    return SessionActor(**row._mapping) if row else None
