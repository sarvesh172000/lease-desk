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
"""

from typing import Callable, Optional

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.engine import Engine

from ..db.engine import engine
from ..settings import Settings, get_settings
from .sessions import COOKIE_NAME, SessionActor, load_session_actor, read_token

__all__ = ["SessionActor", "api_engine", "auth_settings", "current_actor", "require_role"]


def api_engine() -> Engine:
    return engine("lease_api")


def auth_settings() -> Settings:
    return get_settings()


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")


def current_actor(
    session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    eng: Engine = Depends(api_engine),
    settings: Settings = Depends(auth_settings),
) -> SessionActor:
    """The signed-in actor, re-read from the database on this request."""
    actor_id = read_token(settings.session_secret, session)
    if actor_id is None:
        raise _unauthorized()
    with eng.connect() as conn:
        actor = load_session_actor(conn, actor_id)
    if actor is None:           # deleted, deactivated, or somehow an agent
        raise _unauthorized()
    return actor


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
