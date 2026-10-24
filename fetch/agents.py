"""The four Lease Desk agents, in uAgents.

    lease-desk                 the coordinator; ASI:One talks to it (Agent Chat Protocol)
    lease-desk-reconciliation  what's on hold, and one exception's evidence
    lease-desk-investigation   searches the mailbox for what explains a variance
    lease-desk-approvals       approves or holds, as the configured person

Each is a separate agent with its own seed, address, protocol and Agentverse
mailbox; run.py runs them together in one Bureau so messages between them are
delivered in-process. The coordinator asks a specialist with send_and_receive
and waits for its DeskReply; the work itself is specialists.handle.

A specialist answers only the coordinator. Every agent on Agentverse can
message every other, so without that check anyone could ask the approvals
agent to sign off a charge.
"""

import asyncio
import contextvars
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from uagents import Agent, Context, Model, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from . import live, specialists
from .api import Credentials, LeaseDeskAPI
from .desk import HELP, Desk
from .remote import RemoteDesk

PROFILES = Path(__file__).with_name("profiles")

SPECIALISTS = {
    "reconciliation": "Reads Lease Desk's open exceptions and the evidence behind one: billed, "
                      "what the lease supports, and the clause it rests on.",
    "investigation": "Searches the mailbox for what explains a lease variance (an amendment, a side "
                     "letter), and has the engine remeasure the lease if it changed.",
    "approvals": "Approves or holds a Lease Desk exception as the configured person, under Lease "
                 "Desk's role checks and audit trail.",
}

# Seconds the coordinator waits for a specialist. An investigation may read a
# mailbox with a model behind it; the rest are a single API call.
TIMEOUTS = {"investigation": 600}
DEFAULT_TIMEOUT = 60


class DeskRequest(Model):
    op: str
    args: str        # JSON


class DeskReply(Model):
    reply: str       # JSON: {"ok": true, "data": ...} or {"ok": false, "status": ..., "error": ...}


def _seed(name: str) -> str:
    key = "AGENT_SEED_%s" % name.upper()
    seed = os.environ.get(key)
    if not seed:
        raise SystemExit("set %s (fetch/README.md)" % key)
    return seed


def _agent(name: str, handle: str, description: str, offline: bool, readme: Optional[Path] = None) -> Agent:
    return Agent(
        name=handle,
        seed=_seed(name),
        mailbox=not offline,
        publish_agent_details=not offline,
        readme_path=str(readme) if readme else None,
        description=description,
    )


def build(offline: bool = False) -> Dict[str, Agent]:
    """The four agents, wired to each other. `offline` skips Agentverse (local tests)."""
    feed = live.from_env()
    creds = Credentials.from_env()

    coordinator = _agent(
        "coordinator", "lease-desk",
        "Lease accounting desk: finds landlord charges that disagree with the lease, investigates "
        "why, and signs off adjusting entries.", offline, PROFILES / "coordinator.md")
    agents: Dict[str, Agent] = {"coordinator": coordinator}

    for name, description in SPECIALISTS.items():
        agent = _agent(name, "lease-desk-%s" % name, description, offline, PROFILES / ("%s.md" % name))
        agent.include(_specialist_protocol(name, LeaseDeskAPI(creds), feed, coordinator.address),
                      publish_manifest=True)
        agents[name] = agent

    addresses = {name: a.address for name, a in agents.items() if name != "coordinator"}
    coordinator.include(_chat_protocol(addresses, feed), publish_manifest=True)

    @coordinator.on_event("startup")
    async def announce(ctx: Context):
        ctx.logger.info("Lease Desk on %s as %s; live feed %s", creds.base_url, creds.email,
                        "on" if feed.enabled else "off")
        for name, a in agents.items():
            ctx.logger.info("  %-15s %s", name, a.address)

    return agents


# --- specialists ---------------------------------------------------------------

def _specialist_protocol(name: str, api: LeaseDeskAPI, feed: live.Feed, coordinator: str) -> Protocol:
    proto = Protocol(name="LeaseDesk%s" % name.capitalize(), version="0.1.0")

    @proto.on_message(DeskRequest, replies=DeskReply)
    async def on_request(ctx: Context, sender: str, msg: DeskRequest):
        if sender != coordinator:
            ctx.logger.warning("refused %s from %s: not the coordinator", msg.op, sender)
            reply = {"ok": False, "status": 403, "error": "only the Lease Desk coordinator may ask this agent"}
        else:
            try:
                args = json.loads(msg.args or "{}")
            except ValueError:
                args = None
            if not isinstance(args, dict):
                reply = {"ok": False, "status": 400, "error": "args must be a JSON object"}
            else:
                # Blocking HTTP; off the loop so the Bureau keeps serving the others.
                reply = await asyncio.to_thread(specialists.handle, name, api, feed, msg.op, args)
        await ctx.send(sender, DeskReply(reply=json.dumps(reply, default=str)))

    return proto


# --- the coordinator -----------------------------------------------------------

# The context of the chat message being handled. asyncio.to_thread copies
# context variables into the worker thread, so the desk's blocking calls can
# reach the agent that is answering this message, and no other.
_current: contextvars.ContextVar = contextvars.ContextVar("lease_desk_ctx")


def _chat_protocol(addresses: Dict[str, str], feed: live.Feed) -> Protocol:
    chat = Protocol(spec=chat_protocol_spec)

    def call(agent: str, op: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Ask one specialist and wait for its reply (runs on the desk's worker thread)."""
        ctx, loop = _current.get()
        timeout = TIMEOUTS.get(agent, DEFAULT_TIMEOUT)
        future = asyncio.run_coroutine_threadsafe(ctx.send_and_receive(
            addresses[agent], DeskRequest(op=op, args=json.dumps(args, default=str)), DeskReply,
            timeout=timeout), loop)
        reply, status = future.result(timeout=timeout + 10)
        if reply is None:
            return {"ok": False, "status": None,
                    "error": "the %s agent didn't answer (%s)" % (agent, getattr(status, "detail", status))}
        return json.loads(reply.reply)

    desk = Desk(api=RemoteDesk(call), live=feed)

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc),
                                                   acknowledged_msg_id=msg.msg_id))
        text = "".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
        if any(isinstance(c, EndSessionContent) for c in msg.content):
            desk.end(sender)
        if not text:
            if any(isinstance(c, StartSessionContent) for c in msg.content):
                await ctx.send(sender, _message(HELP))
            return

        loop = asyncio.get_running_loop()
        _current.set((ctx, loop))

        def progress(line: str) -> None:
            asyncio.run_coroutine_threadsafe(ctx.send(sender, _message(line)), loop).result(timeout=30)

        try:
            reply = await asyncio.to_thread(desk.handle, sender, text, progress)
        except Exception:
            ctx.logger.exception("desk failed on %r", text)
            reply = "⚠️ Something went wrong on my side, and nothing was changed. Please try again."
        await ctx.send(sender, _message(reply))

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    return chat


def _message(text: str) -> ChatMessage:
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                       content=[TextContent(type="text", text=text)])
