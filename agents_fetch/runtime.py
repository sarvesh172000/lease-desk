"""The uAgents layer: four agents, the Chat Protocol, agent messaging.

    python -m agents_fetch.run               all four in one Bureau, on Agentverse mailboxes (run.py)
    python -m agents_fetch.run --offline     the same with local endpoints only
    python -m agents_fetch.runtime addresses the four agent1q... addresses from the seeds

    front desk      "Northbay Lease Desk"       AGENT_SEED_COORDINATOR    (ASI:One talks to this one)
    rulebook        lease_desk_rulebook         AGENT_SEED_RECONCILIATION
    investigation   lease_desk_investigation    AGENT_SEED_INVESTIGATION
    approvals       lease_desk_approvals        AGENT_SEED_APPROVALS

The seed variable names predate this package: those four agents were
registered on Agentverse under them, and a seed is an address, so the names
stay and the addresses with them.

This file is deliberately thin. Everything an agent decides is in
front_desk.py and the *_agent.py specialists as plain functions, tested
without uagents; here is only the wiring:

- the front desk implements the Agent Chat Protocol (`chat_protocol_spec`):
  it acknowledges every ChatMessage (ChatAcknowledgement), greets on
  StartSessionContent, forgets session context on EndSessionContent, reads
  TextContent, and reads Interactive Card button presses from MetadataContent;
- it routes to a specialist with `ctx.send_and_receive` (SpecialistRequest ->
  SpecialistReply, wire.py) and answers the chat with TextContent plus the
  card as MetadataContent;
- the specialists accept requests only from the front desk's address, and
  refuse to start without one: any agent on Agentverse can message any other,
  and a specialist that answered strangers would be a side door. They also
  speak the Chat Protocol so a direct message gets a pointer to the front
  desk instead of silence;
- one live feed (live.py) per process and, when ASI_ONE_API_KEY is set, the
  asi1 reader (understand.py) for the front desk.

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

from . import live
from .client import LeaseDeskClient
from .grammar import APPROVALS, INVESTIGATION, RULEBOOK
from .protocol import Reply

log = logging.getLogger("agents_fetch")

PROFILES = Path(__file__).resolve().parent / "profiles"
PROFILE = {"front_desk": "front_desk.md", RULEBOOK: "rulebook.md", INVESTIGATION: "investigation.md",
           APPROVALS: "approvals.md"}

ENV_SEED = {"front_desk": "AGENT_SEED_COORDINATOR", RULEBOOK: "AGENT_SEED_RECONCILIATION",
            INVESTIGATION: "AGENT_SEED_INVESTIGATION", APPROVALS: "AGENT_SEED_APPROVALS"}
ENV_ADDRESS = {"front_desk": "LEASEDESK_FRONT_DESK_ADDRESS", RULEBOOK: "LEASEDESK_RULEBOOK_ADDRESS",
               INVESTIGATION: "LEASEDESK_INVESTIGATION_ADDRESS", APPROVALS: "LEASEDESK_APPROVALS_ADDRESS"}
DEFAULT_PORT = {"front_desk": 8101, RULEBOOK: 8102, APPROVALS: 8103, INVESTIGATION: 8104}
# Seconds the front desk waits for a specialist. An investigation may run a
# model over the mailbox; the rest are one or two API calls.
SPECIALIST_TIMEOUT_S = {INVESTIGATION: 600}
DEFAULT_TIMEOUT_S = 60


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
                                  description=description, publish_agent_details=mailbox)
    profile = PROFILES / PROFILE[role]
    if profile.exists():
        kwargs["readme_path"] = str(profile)
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
                     store=None, feed: Optional[live.Feed] = None, understand=None):
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
    feed = feed if feed is not None else live.Feed()
    agent = make_agent("front_desk", AGENT_NAME, DESCRIPTION, port=port, seed=seed)
    targets = addresses or {role: address_for(role) for role in (RULEBOOK, INVESTIGATION, APPROVALS)}
    desks: Dict[str, FrontDesk] = {}

    def desk_for(ctx: Context) -> FrontDesk:
        if "desk" not in desks:
            desks["desk"] = FrontDesk(api, store if store is not None else KeyValuePairingStore(ctx.storage),
                                      dispatch=lambda *_: {},   # agent messaging below, never local
                                      feed=feed, understand=understand)
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
        if isinstance(routed, Route) and routed.specialist == INVESTIGATION:
            # Minutes, possibly: say who has it so the chat shows work happening.
            await ctx.send(sender, chat_reply(Reply(
                "Handed to the investigation agent: it is searching the mailbox for what explains "
                "#%d. This can take a minute." % routed.command.item_id)))
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
                      command_json=json.dumps(req["command"]), run_id=req.get("run_id") or ""),
        response_type=reply_model, timeout=SPECIALIST_TIMEOUT_S.get(routed.specialist, DEFAULT_TIMEOUT_S))
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
                     handle_request: Callable[..., Dict[str, Any]],
                     api: Optional[LeaseDeskClient] = None, *, seed: Optional[str] = None,
                     port: Optional[int] = None, front_desk: Optional[str] = None,
                     feed: Optional[live.Feed] = None):
    from uagents import Context, Protocol
    from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, chat_protocol_spec

    from .wire import SpecialistReply, SpecialistRequest, specialist_protocol

    api = api or api_client()
    feed = feed if feed is not None else live.Feed()
    allowed_sender = front_desk or address_for("front_desk")
    if not allowed_sender:
        raise SystemExit("%s answers only the front desk: set %s (or %s) so it knows the front desk's "
                         "address." % (name, ENV_SEED["front_desk"], ENV_ADDRESS["front_desk"]))
    agent = make_agent(role, name, description, port=port, seed=seed)
    proto = specialist_protocol()

    @proto.on_message(SpecialistRequest, replies=SpecialistReply)
    async def on_request(ctx: Context, sender: str, req: SpecialistRequest):
        if sender != allowed_sender:
            ctx.logger.warning("refusing a request from %s: not the front desk", sender)
            await ctx.send(sender, SpecialistReply(request_id=req.request_id, outcome="refused",
                                                   text="Only Northbay Lease Desk may ask me."))
            return
        try:
            command = json.loads(req.command_json)
        except ValueError:
            command = {}
        out = await asyncio.to_thread(handle_request, {
            "request_id": req.request_id, "run_id": req.run_id, "chat_user": req.chat_user,
            "token": req.token, "command": command if isinstance(command, dict) else {}}, api, feed)
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
            "permissions live there." % (" (%s)" % allowed_sender))))

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        return None

    agent.include(proto, publish_manifest=True)
    agent.include(chat, publish_manifest=True)
    return agent


def run_front_desk() -> None:  # pragma: no cover - long-running
    from .understand import from_env

    build_front_desk(feed=live.from_env(), understand=from_env()).run()


def run_specialist(role: str, name: str, description: str, handle_request) -> None:  # pragma: no cover
    build_specialist(role, name, description, handle_request, feed=live.from_env()).run()


def build_agents(api: Optional[LeaseDeskClient] = None, feed: Optional[live.Feed] = None,
                 understand=None) -> Dict[str, Any]:
    """The four agents, wired to each other, sharing one API client and one
    live feed (so the feed's single sender keeps every agent's steps in order)."""
    from . import approvals_agent, investigation_agent, rulebook_agent

    api = api or api_client()
    feed = feed if feed is not None else live.Feed()
    desk_address = address_for("front_desk")
    agents: Dict[str, Any] = {"front_desk": build_front_desk(api, feed=feed, understand=understand)}
    for role, module in ((RULEBOOK, rulebook_agent), (INVESTIGATION, investigation_agent),
                         (APPROVALS, approvals_agent)):
        agents[role] = build_specialist(role, module.AGENT_NAME, module.DESCRIPTION, module.handle_request,
                                        api, front_desk=desk_address, feed=feed)
    return agents


def build_bureau(port: Optional[int] = None):
    """All four agents in one process. LEASEDESK_AGENT_MAILBOX=1 gives each its
    Agentverse mailbox (run.py sets it); otherwise local endpoints only."""
    from uagents import Bureau

    from .understand import from_env

    feed = live.from_env()
    bureau = Bureau(port=port or int(_env("AGENT_PORT", "8001")))
    for agent in build_agents(feed=feed, understand=from_env()).values():
        bureau.add(agent)
    log.info("live feed %s; asi1 reader %s", "on" if feed.enabled else "off",
             "on" if _env("ASI_ONE_API_KEY") else "off (grammar only)")
    return bureau


def print_addresses() -> None:
    from uagents_core.identity import Identity

    for role, env in ENV_SEED.items():
        seed = _env(env)
        print("%-14s %-26s %s" % (role, env, Identity.from_seed(seed, 0).address if seed else "(not set)"))


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "addresses":
        from .run import load_dotenv

        load_dotenv()
        print_addresses()
    else:
        print("usage: python -m agents_fetch.runtime addresses   (to run the agents: python -m agents_fetch.run)",
              file=sys.stderr)
        sys.exit(2)
