"""The Lease Desk agent ASI:One talks to.

    python -m fetch.coordinator

A uAgent with the Agent Chat Protocol, published to Agentverse through a
mailbox so ASI:One can find it and talk to it. Each ChatMessage is
acknowledged, its text handed to the desk (desk.py), and the reply sent
back. A long step (the investigation) sends a progress line first, so the
chat shows work happening rather than a silent wait.

Environment (fetch/README.md has the full setup):
    AGENT_SEED_COORDINATOR   the agent's identity; the same seed is the same address
    LEASEDESK_API_URL        the Lease Desk API (default http://localhost:8000)
    LEASEDESK_EMAIL          the person the agent acts as
    LEASEDESK_PASSWORD
    ASI_ONE_API_KEY          ASI:One's model reads intent; without it, keywords do
    AGENT_PORT               default 8001
"""

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from .api import Credentials, LeaseDeskAPI
from .desk import HELP, Desk

seed = os.environ.get("AGENT_SEED_COORDINATOR")
if not seed:
    raise SystemExit("set AGENT_SEED_COORDINATOR: a long random phrase that becomes the agent's address")

agent = Agent(
    name="lease-desk",
    seed=seed,
    port=int(os.environ.get("AGENT_PORT", "8001")),
    mailbox=True,
    publish_agent_details=True,
    readme_path=str(Path(__file__).with_name("AGENT_PROFILE.md")),
    description="Lease accounting desk: finds landlord charges that disagree with the lease, "
                "investigates why, and signs off adjusting entries.",
)

desk = Desk(api=LeaseDeskAPI(Credentials.from_env()))
chat = Protocol(spec=chat_protocol_spec)


def _message(text: str, end: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


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

    def progress(line: str) -> None:
        # Called from the desk's worker thread; the send belongs on the agent's loop.
        asyncio.run_coroutine_threadsafe(ctx.send(sender, _message(line)), loop).result(timeout=30)

    try:
        # The desk does blocking HTTP (an investigation can take a minute), so
        # it runs off the event loop and the agent keeps answering others.
        reply = await asyncio.to_thread(desk.handle, sender, text, progress)
    except Exception:
        ctx.logger.exception("desk failed on %r", text)
        reply = "⚠️ Something went wrong on my side, and nothing was changed. Please try again."
    await ctx.send(sender, _message(reply))


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(chat, publish_manifest=True)


@agent.on_event("startup")
async def announce(ctx: Context):
    ctx.logger.info("Lease Desk coordinator at %s, acting for %s on %s",
                    agent.address, desk.api.creds.email, desk.api.creds.base_url)


if __name__ == "__main__":
    agent.run()
