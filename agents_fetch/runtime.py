"""The uAgents layer: three agents, the Chat Protocol, agent messaging.

    python -m agents_fetch.front_desk        "Northbay Lease Desk"   (ASI:One talks to this one)
    python -m agents_fetch.rulebook_agent    lease_desk_rulebook
    python -m agents_fetch.approvals_agent   lease_desk_approvals
    python -m agents_fetch.runtime bureau    all three in one process, for a laptop

This file is deliberately thin. Everything an agent decides is in
front_desk.py / rulebook_agent.py / approvals_agent.py as plain functions,
tested without uagents; here is only the wiring:

- the front desk implements the Agent Chat Protocol (`chat_protocol_spec`):
  it acknowledges every ChatMessage (ChatAcknowledgement), greets on
  StartSessionContent, forgets session context on EndSessionContent, reads
  TextContent, and reads Interactive Card button presses from MetadataContent;
- it routes to a specialist with `ctx.send_and_receive` (SpecialistRequest ->
  SpecialistReply, wire.py) and answers the chat with TextContent plus the
  card as MetadataContent;
- the specialists accept requests only from the front desk's address (when
  configured), and also speak the Chat Protocol so a direct message gets a
  pointer to the front desk instead of silence.

Configuration is environment only (README.md, .env.example). Seeds are
secrets — they *are* the agents' identities — and are never committed.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .client import LeaseDeskClient
from .grammar import APPROVALS, RULEBOOK
from .protocol import Reply

log = logging.getLogger("agents_fetch")

README = Path(__file__).resolve().parent / "README.md"

ENV_SEED = {"front_desk": "LEASEDESK_FRONT_DESK_SEED", RULEBOOK: "LEASEDESK_RULEBOOK_SEED",
            APPROVALS: "LEASEDESK_APPROVALS_SEED"}
ENV_ADDRESS = {"front_desk": "LEASEDESK_FRONT_DESK_ADDRESS", RULEBOOK: "LEASEDESK_RULEBOOK_ADDRESS",
               APPROVALS: "LEASEDESK_APPROVALS_ADDRESS"}
DEFAULT_PORT = {"front_desk": 8101, RULEBOOK: 8102, APPROVALS: 8103}
SPECIALIST_TIMEOUT_S = 60


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name, "").strip()
    return value or default


def seed_for(role: str) -> str:
    seed = _env(ENV_SEED[role])
    if not seed:
        raise SystemExit("%s is not set. Each agent's seed is its identity (and its Agentverse "
                         "address): generate one with `python3 -c \"import secrets; "
                         "print(secrets.token_urlsafe(32))\"`, keep it out of git, and set it in "
                         "your shell or .env." % ENV_SEED[role])
    return seed


def address_for(role: str) -> Optional[str]:
    """The configured address, or the one this process can derive from the
    role's seed when that seed is set here too (the one-laptop setup)."""
    address = _env(ENV_ADDRESS[role])
    if address:
        return address
    seed = _env(ENV_SEED[role])
    if seed:
        from uagents_core.identity import Identity

        return Identity.from_seed(seed, 0).address
    return None


def api_client() -> LeaseDeskClient:
    return LeaseDeskClient(_env("LEASEDESK_API_URL", "http://localhost:8000"),
                           client_key=_env("LEASEDESK_PAIRING_CLIENT_KEY"))


def make_agent(role: str, name: str, description: str, *, port: Optional[int] = None,
               seed: Optional[str] = None):
    from uagents import Agent

    mailbox = _env("LEASEDESK_AGENT_MAILBOX", "0") == "1"
    port = port or int(_env("LEASEDESK_%s_PORT" % role.upper(), str(DEFAULT_PORT[role])))
    kwargs: Dict[str, Any] = dict(name=name, seed=seed or seed_for(role), port=port,
                                  description=description, publish_agent_details=True)
    if README.exists():
        kwargs["readme_path"] = str(README)
    if mailbox:
        kwargs["mailbox"] = True
    else:
        kwargs["endpoint"] = ["http://127.0.0.1:%d/submit" % port]
    return Agent(**kwargs)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def chat_reply(reply: Reply, end_session: bool = False):
    from uagents_core.contrib.protocols.chat import (
        ChatMessage,
        EndSessionContent,
        MetadataContent,
        TextContent,
    )

    content: list = [TextContent(text=reply.text)]
    if reply.card and isinstance(reply.card.get("metadata"), dict):
        content.append(MetadataContent(metadata=reply.card["metadata"]))
    if end_session:
        content.append(EndSessionContent())
    return ChatMessage(content=content)


# --- the front desk -------------------------------------------------------------------

def build_front_desk(api: Optional[LeaseDeskClient] = None, *, seed: Optional[str] = None,
                     port: Optional[int] = None, addresses: Optional[Dict[str, str]] = None,
                     store=None):
    from uagents import Context, Protocol
    from uagents_core.contrib.protocols.chat import (
        ChatAcknowledgement,
        ChatMessage,
        EndSessionContent,
        MetadataContent,
        StartSessionContent,
        TextContent,
        chat_protocol_spec,
    )

    from .cards import selection_from_metadata
    from .front_desk import AGENT_NAME, DESCRIPTION, FrontDesk, Route
    from .pairing import KeyValuePairingStore
    from .wire import SpecialistReply, SpecialistRequest

    api = api or api_client()
    agent = make_agent("front_desk", AGENT_NAME, DESCRIPTION, port=port, seed=seed)
    targets = addresses or {RULEBOOK: address_for(RULEBOOK), APPROVALS: address_for(APPROVALS)}
    desks: Dict[str, FrontDesk] = {}

    def desk_for(ctx: Context) -> FrontDesk:
        if "desk" not in desks:
            desks["desk"] = FrontDesk(api, store if store is not None else KeyValuePairingStore(ctx.storage),
                                      dispatch=lambda *_: {})   # agent messaging below, never local
        return desks["desk"]

    chat = Protocol(spec=chat_protocol_spec)

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=_now(), acknowledged_msg_id=msg.msg_id))
        desk = desk_for(ctx)
        texts, selection, started, ended = [], None, False, False
        for item in msg.content:
            if isinstance(item, StartSessionContent):
                started = True
            elif isinstance(item, EndSessionContent):
                ended = True
            elif isinstance(item, TextContent):
                texts.append(item.text)
            elif isinstance(item, MetadataContent):
                selection = selection_from_metadata(item.metadata) or selection

        if started and not texts and selection is None:
            await ctx.send(sender, chat_reply(desk.start_session(sender)))
            return
        if started:
            desk.start_session(sender)
        if not texts and selection is None:
            if ended:
                desk.end_session(sender)
            return

        routed = await asyncio.to_thread(desk.route, sender, "\n".join(texts) if texts else None, selection)
        if isinstance(routed, Route):
            reply = await _ask_specialist(ctx, desk, sender, routed, targets, SpecialistRequest,
                                          SpecialistReply)
        else:
            reply = routed
        await ctx.send(sender, chat_reply(reply, end_session=ended))
        if ended:
            desk.end_session(sender)

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        ctx.logger.debug("chat ack from %s for %s", sender, msg.acknowledged_msg_id)

    agent.include(chat, publish_manifest=True)
    return agent


async def _ask_specialist(ctx, desk, sender, routed, targets, request_model, reply_model) -> Reply:
    address = targets.get(routed.specialist)
    if not address:
        return Reply("The %s agent isn't configured (set %s)." % (routed.specialist,
                                                                  ENV_ADDRESS[routed.specialist]),
                     outcome="error")
    req = routed.request
    response, status = await ctx.send_and_receive(
        address,
        request_model(request_id=req["request_id"], chat_user=req["chat_user"], token=req["token"],
                      command_json=json.dumps(req["command"])),
        response_type=reply_model, timeout=SPECIALIST_TIMEOUT_S)
    if not isinstance(response, reply_model) or response.request_id != req["request_id"]:
        ctx.logger.warning("no reply from %s: %s", routed.specialist, status)
        return desk.finish(sender, routed, None)
    card = None
    if response.card_json:
        try:
            card = json.loads(response.card_json)
        except ValueError:
            card = None
    return desk.finish(sender, routed, {"request_id": response.request_id, "text": response.text,
                                        "outcome": response.outcome, "card": card,
                                        "audit_seq": response.audit_seq})


# --- the specialists ------------------------------------------------------------------

def build_specialist(role: str, name: str, description: str,
                     handle_request: Callable[[Dict[str, Any], LeaseDeskClient], Dict[str, Any]],
                     api: Optional[LeaseDeskClient] = None, *, seed: Optional[str] = None,
                     port: Optional[int] = None, front_desk: Optional[str] = None):
    from uagents import Context, Protocol
    from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, chat_protocol_spec

    from .wire import SpecialistReply, SpecialistRequest, specialist_protocol

    api = api or api_client()
    agent = make_agent(role, name, description, port=port, seed=seed)
    allowed_sender = front_desk or address_for("front_desk")
    if not allowed_sender:
        log.warning("%s: no front desk address configured; accepting requests from any agent "
                    "(each still needs a valid pairing token)", name)
    proto = specialist_protocol()

    @proto.on_message(SpecialistRequest, replies=SpecialistReply)
    async def on_request(ctx: Context, sender: str, req: SpecialistRequest):
        if allowed_sender and sender != allowed_sender:
            ctx.logger.warning("refusing a request from %s: not the front desk", sender)
            await ctx.send(sender, SpecialistReply(request_id=req.request_id, outcome="refused",
                                                   text="Only Northbay Lease Desk may ask me."))
            return
        try:
            command = json.loads(req.command_json)
        except ValueError:
            command = {}
        out = await asyncio.to_thread(handle_request, {
            "request_id": req.request_id, "chat_user": req.chat_user, "token": req.token,
            "command": command if isinstance(command, dict) else {}}, api)
        await ctx.send(sender, SpecialistReply(
            request_id=req.request_id, text=out["text"], outcome=out["outcome"],
            card_json=json.dumps(out["card"]) if out.get("card") else None,
            audit_seq=out.get("audit_seq")))

    chat = Protocol(spec=chat_protocol_spec)

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=_now(), acknowledged_msg_id=msg.msg_id))
        await ctx.send(sender, chat_reply(Reply(
            "I work behind **Northbay Lease Desk**. Message it instead%s — pairing and "
            "permissions live there." % (" (%s)" % allowed_sender if allowed_sender else ""))))

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        return None

    agent.include(proto, publish_manifest=True)
    agent.include(chat, publish_manifest=True)
    return agent


def run_front_desk() -> None:  # pragma: no cover - long-running
    build_front_desk().run()


def run_specialist(role: str, name: str, description: str, handle_request) -> None:  # pragma: no cover
    build_specialist(role, name, description, handle_request).run()


def build_bureau():
    """All three agents in one process (local endpoints, no mailbox)."""
    from uagents import Bureau

    from . import approvals_agent, rulebook_agent

    api = api_client()
    desk_address = address_for("front_desk")
    bureau = Bureau()
    bureau.add(build_front_desk(api))
    bureau.add(build_specialist(RULEBOOK, rulebook_agent.AGENT_NAME, rulebook_agent.DESCRIPTION,
                                rulebook_agent.handle_request, api, front_desk=desk_address))
    bureau.add(build_specialist(APPROVALS, approvals_agent.AGENT_NAME, approvals_agent.DESCRIPTION,
                                approvals_agent.handle_request, api, front_desk=desk_address))
    return bureau


def print_addresses() -> None:
    from uagents_core.identity import Identity

    for role, env in ENV_SEED.items():
        seed = _env(env)
        print("%-11s %s" % (role, Identity.from_seed(seed, 0).address if seed else "(%s not set)" % env))


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "bureau":
        build_bureau().run()
    elif arg == "addresses":
        print_addresses()
    else:
        print("usage: python -m agents_fetch.runtime bureau|addresses", file=sys.stderr)
        sys.exit(2)
