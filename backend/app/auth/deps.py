"""FastAPI dependencies for every router that needs to know who is asking.

    from app.auth.deps import current_actor, require_role, SessionActor

    @router.get("/items")
    def items(actor: SessionActor = Depends(current_actor)): ...

    @router.post("/batches", dependencies=[Depends(require_role("ap_clerk"))])
    def release(): ...

`current_actor` is 401 without a valid session; `require_role` is 403 for a
signed-in actor of another role. Role is the coarse gate only: region, entity
and separation of duties are `can()`'s job in work/roles.py.

The database engine and settings are dependencies too (`api_engine`,
`auth_settings`), so tests swap them with `app.dependency_overrides` instead
of patching modules. The engine is always `lease_api`.

A request may instead carry a chat pairing token (`Authorization: Bearer
ldp_...` plus `X-LeaseDesk-Chat-User`), which is how the Fetch.ai front desk
acts for a paired person (auth/pairing.py). It resolves to the same
SessionActor, re-read on every request, but only on the routes in
`pairing.PAIRED_ROUTES`; anywhere else it is 403. When a Bearer header is present
the cookie is ignored, so a request is never half one session and half
another. The pairing is left on `request.state.pairing`.
"""

from typing import Callable, Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.engine import Engine

from ..db.engine import engine
from ..settings import Settings, get_settings
from . import pairing
from .sessions import COOKIE_NAME, SessionActor, load_session_actor, read_token

__all__ = ["SessionActor", "api_engine", "auth_settings", "current_actor", "require_role"]


def api_engine() -> Engine:
    return engine("lease_api")


def auth_settings() -> Settings:
    return get_settings()


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")


def current_actor(
    request: Request,
    session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    authorization: Optional[str] = Header(default=None),
    chat_user: Optional[str] = Header(default=None, alias=pairing.CHAT_USER_HEADER),
    eng: Engine = Depends(api_engine),
    settings: Settings = Depends(auth_settings),
) -> SessionActor:
    """The signed-in actor, re-read from the database on this request."""
    if pairing.is_pairing_token(authorization):
        return _paired_actor(request, authorization, chat_user, eng)
    request.state.pairing = None
    actor_id = read_token(settings.session_secret, session)
    if actor_id is None:
        raise _unauthorized()
    with eng.connect() as conn:
        actor = load_session_actor(conn, actor_id)
    if actor is None:           # deleted, deactivated, or somehow an agent
        raise _unauthorized()
    return actor


def _paired_actor(request: Request, authorization: str, chat_user: Optional[str],
                  eng: Engine) -> SessionActor:
    token = pairing.bearer_token(authorization)
    if token is None:
        raise _unauthorized()
    with eng.connect() as conn:
        paired = pairing.session_for_token(conn, token, chat_user)
    if paired is None:
        raise _unauthorized()
    route = request.scope.get("route")
    if not pairing.route_allowed(request.method, getattr(route, "path", None)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "not available to a paired chat session; use the web app")
    request.state.pairing = paired
    return paired.actor


def require_role(*roles: str) -> Callable[..., SessionActor]:
    """A dependency that passes the actor through if their role is one of
    `roles`, and is 403 otherwise (401 still wins when not signed in)."""
    if not roles:
        raise ValueError("require_role() needs at least one role")
    allowed = frozenset(roles)

    def dependency(actor: SessionActor = Depends(current_actor)) -> SessionActor:
        if actor.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "requires role: %s" % ", ".join(sorted(allowed)))
        return actor

    return dependency
