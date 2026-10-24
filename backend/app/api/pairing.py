"""/api/pairing: link an ASI:One chat user to a person (PHASE_3.md group 9).

    POST /api/pairing/codes          signed in (cookie)  -> {code, expires_at, ttl_seconds, instructions}
    GET  /api/pairing                signed in (cookie)  -> {pairings: [{id, chat_user, claimed_at, expires_at}]}
    POST /api/pairing/{id}/revoke    signed in (cookie)  -> 204; one of your own pairings
    POST /api/pairing/claim          the front desk agent: {code, chat_user} -> {token, expires_at, actor}
    GET  /api/pairing/me             a paired chat session -> who it acts as, until when
    POST /api/pairing/me/revoke      a paired chat session -> 204; "unpair" from chat

The web app's Today screen calls /codes and shows the code; the person sends
`pair <code>` to the "Northbay Lease Desk" agent, which calls /claim. The
claim needs no session (that is the point: the agent has none), only the
code, which works once and for ten minutes. When LEASEDESK_PAIRING_CLIENT_KEY
is set, /claim also needs it in `X-Pairing-Client-Key`, so only the deployed
front desk can redeem codes at all.

A paired session cannot reach /codes, the list or /{id}/revoke (they are not
in auth/pairing.py PAIRED_ROUTES), so a chat session can never mint itself
another pairing. Logic and storage are in auth/pairing.py.
"""

import hmac
import os
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from ..auth import pairing
from ..auth.deps import SessionActor, api_engine, current_actor
from ..auth.routes import ActorOut

router = APIRouter(prefix="/api/pairing", tags=["pairing"])

CLIENT_KEY_ENV = "LEASEDESK_PAIRING_CLIENT_KEY"
FRONT_DESK_NAME = "Northbay Lease Desk"


class CodeOut(BaseModel):
    code: str
    expires_at: datetime
    ttl_seconds: int
    instructions: str


class ClaimBody(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    chat_user: str = Field(min_length=1, max_length=200)


class ClaimOut(BaseModel):
    pairing_id: int
    token: str
    token_type: str = "Bearer"
    expires_at: datetime
    chat_user: str
    actor: ActorOut


class PairingOut(BaseModel):
    id: int
    chat_user: str
    claimed_at: datetime
    expires_at: datetime


class PairingList(BaseModel):
    pairings: List[PairingOut]


class PairedMe(BaseModel):
    pairing_id: int
    chat_user: str
    expires_at: datetime
    actor: ActorOut


def _cookie_session(request: Request, actor: SessionActor = Depends(current_actor)) -> SessionActor:
    """Signed in through the web app, not through a chat pairing. (A paired
    session never gets here: current_actor refuses it off PAIRED_ROUTES.)"""
    if getattr(request.state, "pairing", None) is not None:   # pragma: no cover - belt and braces
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not available to a paired chat session")
    return actor


def _paired_session(request: Request,
                    actor: SessionActor = Depends(current_actor)) -> pairing.PairedSession:
    paired = getattr(request.state, "pairing", None)
    if paired is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "this session is not a chat pairing")
    return paired


@router.post("/codes", response_model=CodeOut, status_code=status.HTTP_201_CREATED)
def create_code(actor: SessionActor = Depends(_cookie_session),
                eng: Engine = Depends(api_engine)) -> CodeOut:
    if actor.role in ("agent", "system"):          # pragma: no cover - they never hold a session
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only people pair a chat account")
    with eng.begin() as conn:
        code, expires_at = pairing.mint_code(conn, actor)
    ttl = int(pairing.CODE_TTL.total_seconds())
    return CodeOut(code=code, expires_at=expires_at, ttl_seconds=ttl,
                   instructions="In ASI:One, send \"pair %s\" to %s within %d minutes. "
                                "The code works once." % (code, FRONT_DESK_NAME, ttl // 60))


@router.get("", response_model=PairingList)
def list_pairings(actor: SessionActor = Depends(_cookie_session),
                  eng: Engine = Depends(api_engine)) -> PairingList:
    with eng.connect() as conn:
        return PairingList(pairings=[PairingOut(**p) for p in pairing.live_pairings(conn, actor)])


@router.post("/{pairing_id:int}/revoke", status_code=status.HTTP_204_NO_CONTENT,
             response_class=Response)
def revoke_pairing(pairing_id: int = PathParam(..., ge=1, le=2**63 - 1),
                   actor: SessionActor = Depends(_cookie_session),
                   eng: Engine = Depends(api_engine)) -> Response:
    with eng.begin() as conn:
        if not pairing.revoke(conn, pairing_id, actor, via="web"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no live pairing %s of yours" % pairing_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _check_client_key(given: Optional[str]) -> None:
    expected = os.environ.get(CLIENT_KEY_ENV, "")
    if expected and not hmac.compare_digest((given or "").encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "pairing client key required")


@router.post("/claim", response_model=ClaimOut)
def claim_code(body: ClaimBody, eng: Engine = Depends(api_engine),
               client_key: Optional[str] = Header(default=None, alias="X-Pairing-Client-Key")
               ) -> ClaimOut:
    _check_client_key(client_key)
    try:
        with eng.begin() as conn:
            claimed = pairing.claim(conn, body.code, body.chat_user)
    except pairing.PairingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return ClaimOut(pairing_id=claimed.pairing_id, token=claimed.token,
                    expires_at=claimed.expires_at, chat_user=claimed.chat_user,
                    actor=ActorOut(**claimed.actor.public()))


@router.get("/me", response_model=PairedMe)
def paired_me(paired: pairing.PairedSession = Depends(_paired_session)) -> PairedMe:
    return PairedMe(pairing_id=paired.pairing_id, chat_user=paired.chat_user,
                    expires_at=paired.expires_at, actor=ActorOut(**paired.actor.public()))


@router.post("/me/revoke", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def unpair_me(paired: pairing.PairedSession = Depends(_paired_session),
              eng: Engine = Depends(api_engine)) -> Response:
    with eng.begin() as conn:
        pairing.revoke(conn, paired.pairing_id, paired.actor, via="chat")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
