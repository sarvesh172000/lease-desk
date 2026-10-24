"""/api/auth: sign in, sign out, who am I, and the demo-only switcher.

    POST /api/auth/login         {email, password} -> sets the cookie, returns the actor
    POST /api/auth/logout        clears the cookie (204)
    GET  /api/auth/me            the signed-in actor, or 401
    GET  /api/auth/demo-actors   DEMO_MODE only: the people you can switch to
    POST /api/auth/demo-switch   DEMO_MODE only: {actor_id} -> become them, no password

Login gives one answer for every failure (unknown email, wrong password,
no password set, deactivated, an agent), and does the same argon2 work in
each case by verifying against a dummy hash when there is no real one. So
neither the message nor the timing tells a caller whether an email has an
account.

The demo routes exist so a reviewer can walk the approval flow as each role
in a minute. With demo mode off they are 404, indistinguishable from routes
that were never there.

Everything reads as `lease_api`, the only application role besides the
gateway that can see `actor.password_hash`.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..settings import Settings
from . import passwords
from .deps import api_engine, auth_settings, current_actor
from .sessions import (
    SessionActor,
    clear_session_cookie,
    issue_token,
    load_session_actor,
    set_session_cookie,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

INVALID_LOGIN = "invalid email or password"


class LoginBody(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class DemoSwitchBody(BaseModel):
    actor_id: str = Field(min_length=1, max_length=200)


class ActorOut(BaseModel):
    id: str
    name: str
    role: str
    region_id: str | None
    entity_id: str | None


_BY_EMAIL = text("""
    SELECT id, name, role, region_id, entity_id, password_hash, active FROM actor
    WHERE lower(email) = lower(:email)
""")

_PEOPLE = text("""
    SELECT id, name, role, region_id, entity_id FROM actor
    WHERE active AND role <> 'agent'
    ORDER BY role, id
""")


def _start_session(response: Response, settings: Settings, actor: SessionActor) -> dict:
    set_session_cookie(response, issue_token(settings.session_secret, actor.id),
                       settings.cookie_secure)
    return actor.public()


@router.post("/login", response_model=ActorOut)
def login(body: LoginBody, response: Response,
          eng: Engine = Depends(api_engine), settings: Settings = Depends(auth_settings)):
    with eng.connect() as conn:
        row = conn.execute(_BY_EMAIL, {"email": body.email.strip()}).first()
    eligible = row is not None and row.active and row.role != "agent" and row.password_hash
    # Always one argon2 verify, real or dummy, so failures cost the same.
    ok = passwords.verify_password(row.password_hash if eligible else passwords.dummy_hash(),
                                   body.password)
    if not (eligible and ok):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_LOGIN)
    actor = SessionActor(id=row.id, name=row.name, role=row.role,
                         region_id=row.region_id, entity_id=row.entity_id)
    return _start_session(response, settings, actor)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(settings: Settings = Depends(auth_settings)) -> Response:
    """Always succeeds, signed in or not: the point is that afterwards you are not."""
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, settings.cookie_secure)
    return response


@router.get("/me", response_model=ActorOut)
def me(actor: SessionActor = Depends(current_actor)):
    return actor.public()


def _demo_only(settings: Settings = Depends(auth_settings)) -> Settings:
    if not settings.demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return settings


@router.get("/demo-actors", response_model=List[ActorOut])
def demo_actors(settings: Settings = Depends(_demo_only), eng: Engine = Depends(api_engine)):
    with eng.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(_PEOPLE)]


@router.post("/demo-switch", response_model=ActorOut)
def demo_switch(body: DemoSwitchBody, response: Response,
                settings: Settings = Depends(_demo_only), eng: Engine = Depends(api_engine)):
    with eng.connect() as conn:
        actor = load_session_actor(conn, body.actor_id)
    if actor is None:       # unknown, deactivated, or an agent: agents never hold a session
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such person")
    return _start_session(response, settings, actor)
