"""The four agents as real uAgents, talking the Agent Chat Protocol (C8, S2).

Skipped unless `uagents` is installed (agents_fetch/requirements.txt; the main
install leaves it out). When it is, this runs the front desk and the
rulebook, investigation and approvals agents plus a stand-in ASI:One user in one uAgents Bureau,
in-process: real ChatMessage / ChatAcknowledgement / StartSession, real
agent-to-agent messaging (front desk -> approvals agent -> back), and the
real API on the test database behind it. No Agentverse, no mailbox.

It replays THE acceptance check over the wire: pair as the Desert regional
manager, answer a Bay Area question, get refused, see the denial in the
audit trail. The stand-in user also asks the investigation agent directly,
as any agent on Agentverse could, and is refused: specialists answer only
the front desk.
"""

import asyncio
import os

import pytest

uagents = pytest.importorskip("uagents")

import ledger_world as w  # noqa: E402
from sqlalchemy import text  # noqa: E402
from test_api_write import as_, ask, make_client, open_item, state, world  # noqa: E402,F401
from test_fetch_agents import api_client, fetch_world  # noqa: E402,F401

from agents_fetch import approvals_agent, investigation_agent, rulebook_agent  # noqa: E402
from agents_fetch.client import LeaseDeskClient  # noqa: E402
from agents_fetch.grammar import APPROVALS, INVESTIGATION, RULEBOOK  # noqa: E402
from agents_fetch.pairing import MemoryPairingStore  # noqa: E402
from agents_fetch.runtime import build_front_desk, build_specialist  # noqa: E402

SEEDS = {"front_desk": "test-only front desk seed, never used for real",
         RULEBOOK: "test-only rulebook seed, never used for real",
         APPROVALS: "test-only approvals seed, never used for real",
         INVESTIGATION: "test-only investigation seed, never used for real",
         "user": "test-only asi1 user seed, never used for real"}


def clear_agent_env(monkeypatch):
    """A shell with the real seeds exported must not leak them into a test."""
    for key in list(os.environ):
        if key.startswith("AGENT_SEED_") or (key.startswith("LEASEDESK_") and key.endswith("_ADDRESS")):
            monkeypatch.delenv(key)


def test_the_acceptance_check_over_the_chat_protocol(fetch_world, monkeypatch):  # noqa: F811
    from uagents import Agent, Bureau, Context
    from uagents_core.contrib.protocols.chat import (
        ChatAcknowledgement,
        ChatMessage,
        MetadataContent,
        StartSessionContent,
        TextContent,
        chat_protocol_spec,
    )
    from uagents_core.identity import Identity

    from agents_fetch.wire import SpecialistReply, SpecialistRequest, specialist_protocol

    monkeypatch.setenv("LEASEDESK_AGENT_MAILBOX", "0")
    clear_agent_env(monkeypatch)
    address = {k: Identity.from_seed(s, 0).address for k, s in SEEDS.items()}

    bay = open_item(fetch_world, w.RENT)
    ask(fetch_world, bay, "PER-RM-BAY", body="Is suite 110 the right suite?")
    code = as_(make_client(fetch_world), "PER-RM-DESERT").post("/api/pairing/codes").json()["code"]
    api = LeaseDeskClient(http=api_client(fetch_world))

    desk = build_front_desk(api, seed=SEEDS["front_desk"], port=18101, store=MemoryPairingStore(),
                            addresses={RULEBOOK: address[RULEBOOK], APPROVALS: address[APPROVALS],
                                       INVESTIGATION: address[INVESTIGATION]})
    rulebook = build_specialist(RULEBOOK, rulebook_agent.AGENT_NAME, rulebook_agent.DESCRIPTION,
                                rulebook_agent.handle_request, api, seed=SEEDS[RULEBOOK], port=18102,
                                front_desk=address["front_desk"])
    approvals = build_specialist(APPROVALS, approvals_agent.AGENT_NAME, approvals_agent.DESCRIPTION,
                                 approvals_agent.handle_request, api, seed=SEEDS[APPROVALS], port=18103,
                                 front_desk=address["front_desk"])
    investigation = build_specialist(INVESTIGATION, investigation_agent.AGENT_NAME,
                                     investigation_agent.DESCRIPTION, investigation_agent.handle_request, api,
                                     seed=SEEDS[INVESTIGATION], port=18105, front_desk=address["front_desk"])
    assert desk.address == address["front_desk"] and approvals.address == address[APPROVALS]

    user = Agent(name="asi1-user", seed=SEEDS["user"], port=18104,
                 endpoint=["http://127.0.0.1:18104/submit"])
    replies: "asyncio.Queue" = asyncio.Queue()
    acks = []
    transcript = []
    done = asyncio.Event()
    chat = uagents.Protocol(spec=chat_protocol_spec)

    @chat.on_message(ChatMessage)
    async def on_reply(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        await replies.put(msg)

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        acks.append(msg.acknowledged_msg_id)

    user.include(chat)
    side_door: "asyncio.Queue" = asyncio.Queue()
    direct = specialist_protocol()

    @direct.on_message(SpecialistReply)
    async def on_specialist_reply(ctx: Context, sender: str, msg: SpecialistReply):
        await side_door.put((sender, msg))

    user.include(direct)

    async def say(ctx, *content):
        msg = ChatMessage(content=list(content))
        await ctx.send(address["front_desk"], msg)
        reply = await asyncio.wait_for(replies.get(), timeout=45)
        transcript.append((msg, reply))
        return reply

    async def conversation(ctx: Context):
        try:
            await say(ctx, StartSessionContent())
            await say(ctx, TextContent(text="what needs me this week?"))
            await say(ctx, TextContent(text="pair %s" % code))
            await say(ctx, TextContent(text="answer %d yes, suite 110 is right" % bay))
            await say(ctx, TextContent(text="review %d" % bay))
            # A stranger (any agent on Agentverse) asking a specialist directly.
            await ctx.send(address[INVESTIGATION], SpecialistRequest(
                request_id="side-door", chat_user="x", token="ldp_" + "x" * 40,
                command_json='{"name": "investigate", "item_id": %d}' % bay, run_id="r"))
            transcript.append(await asyncio.wait_for(side_door.get(), timeout=45))
        finally:
            done.set()

    @user.on_event("startup")
    async def start(ctx: Context):
        asyncio.get_running_loop().create_task(conversation(ctx))

    bureau = Bureau(port=18100, endpoint=["http://127.0.0.1:18100/submit"])
    for agent in (desk, rulebook, approvals, investigation, user):
        bureau.add(agent)

    async def run():
        # The bureau's own shutdown waits on Almanac/Agentverse calls that
        # cannot succeed offline, so the test stops driving the loop once the
        # conversation is over instead of shutting the bureau down.
        asyncio.get_running_loop().create_task(bureau.run_async())
        await asyncio.wait_for(done.wait(), timeout=120)

    bureau._loop.run_until_complete(run())

    sender, refusal = transcript.pop()
    assert (sender, refusal.request_id, refusal.outcome) == (address[INVESTIGATION], "side-door", "refused")
    assert "Only Northbay Lease Desk may ask me" in refusal.text
    texts = [reply.text() for _, reply in transcript]
    assert len(texts) == 5, texts
    assert "pair XXXX-XXXX" in texts[0]                       # StartSession -> help
    assert "isn't paired" in texts[1]                         # unpaired: no data
    assert "Desi RM" in texts[2]                              # paired
    assert "Refused" in texts[3] and "region REG-BAY" in texts[3], texts[3]
    assert "no item #%d" % bay in texts[4]                    # cannot even see it
    assert {m.msg_id for m, _ in transcript} <= set(acks), "every chat message acknowledged"
    assert state(fetch_world, bay) == "NEEDS_INFO"

    with fetch_world["owner"].connect() as conn:
        denial = conn.execute(text("""
            SELECT actor_id, action, allowed FROM audit_event
             WHERE subject_type = 'work_item' AND subject_id = :i AND NOT allowed"""),
            {"i": str(bay)}).all()
    assert [tuple(r) for r in denial] == [("PER-RM-DESERT", "answer", False)]
    assert not any(isinstance(c, MetadataContent) for c in transcript[3][1].content)


def test_a_specialist_will_not_start_without_the_front_desks_address(monkeypatch):
    clear_agent_env(monkeypatch)
    with pytest.raises(SystemExit, match="answers only the front desk"):
        build_specialist(INVESTIGATION, investigation_agent.AGENT_NAME, investigation_agent.DESCRIPTION,
                         investigation_agent.handle_request, LeaseDeskClient("http://127.0.0.1:9"),
                         seed=SEEDS[INVESTIGATION], port=18106)


def test_the_seed_variables_are_the_registered_ones():
    """The four agents are registered on Agentverse under these names; a seed
    is an address, so renaming a variable would orphan a registered agent."""
    from agents_fetch.runtime import ENV_SEED

    assert ENV_SEED == {"front_desk": "AGENT_SEED_COORDINATOR", RULEBOOK: "AGENT_SEED_RECONCILIATION",
                        INVESTIGATION: "AGENT_SEED_INVESTIGATION", APPROVALS: "AGENT_SEED_APPROVALS"}
