"""`make prove-limits`: the demo's "Limits" beat, live, against any database.

Three things that must never work, tried for real, each refused by a
different layer and each left in the audit timeline:

  (a) the agent tries to approve an item         can() refuses: agents propose, people approve
  (b) a manager approves the item they answered   can() refuses: separation of duties
  (c) raw SQL INSERT INTO journal_entry as the    Postgres refuses: lease_agent was never
      agent's own database role                   granted it, whatever the Python above says

    python -m app.work.limits            (LEASEDESK_DEMO_MODE=1, the default)

It needs an item to try them on, so it opens a throwaway LIMITS_DEMO work
item in the manager's region (the agent creates and proposes it, then asks
the manager a question, which the manager answers). When the three refusals
are on record, a controller rejects and closes it, so it leaves the open
queue. Nothing is deleted: every step is a hash-chained event, the history is
append-only, and replay rebuilds the item like any other. Running it again
opens a new item and adds three new refusals; nothing else in the database
changes (the journal, the outbox, golden records and periods are untouched,
and the script checks that).

The DB refusal in (c) leaves no event by itself, because the statement never
ran. The agent records it afterwards, as an allowed = false event on the
item, so all three refusals read in one timeline.
"""

import argparse
import sys
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from .events import append_event, verify_chain
from .roles import Actor, load_actor
from .transitions import Denied, create_item, transition

DEMO_KIND = "LIMITS_DEMO"
DEMO_SUBJECT = "limits_demo"

ROLES = ("lease_agent", "lease_api", "lease_reader")

# What the agent's raw statement is; never parameterised from outside.
RAW_SQL = ("INSERT INTO journal_entry (entity_id, date, period, memo, idempotency_key) "
           "VALUES ('ENT-CA', '2026-01-31', '2026-01-01', 'the agent posts', "
           "'limits-demo-raw-sql')")

# Tables the demo must leave exactly as it found them.
UNTOUCHED = ("journal_entry", "journal_line", "outbox", "period", "account", "payment",
             "landlord_charge", "lease_version")


class LimitsError(RuntimeError):
    """The database lacks what the demo needs (no agent, manager or controller)."""


@dataclass(frozen=True)
class Refusal:
    label: str          # (a), (b), (c)
    layer: str          # who refused: can() or Postgres
    seq: int            # the allowed = false audit_event
    actor_id: str
    action: str
    reason: str


@dataclass
class LimitsResult:
    item_id: int
    refusals: List[Refusal] = field(default_factory=list)
    allowed: List[str] = field(default_factory=list)   # anything that should have failed and did not
    chain_ok: bool = False
    chain_problem: Optional[str] = None
    counts_before: Dict[str, int] = field(default_factory=dict)
    counts_after: Dict[str, int] = field(default_factory=dict)
    final_state: Optional[str] = None

    @property
    def ok(self) -> bool:
        return (len(self.refusals) == 3 and not self.allowed and self.chain_ok
                and self.counts_before == self.counts_after)


# ------------------------------------------------------------------ helpers

def table_footprint(conn: Connection, exclude: Tuple[str, ...] = ()) -> Dict[str, Tuple[int, str]]:
    """(row count, md5 of every row) for every table in the public schema, so
    a test can show that nothing at all changed. Needs a role that can read
    whole rows of every table: the owner, in tests."""
    tables = conn.execute(text("""
        SELECT table_name FROM information_schema.tables
         WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
           AND table_name <> 'alembic_version'
         ORDER BY table_name
    """)).scalars().all()
    out = {}
    for table in tables:
        if table in exclude:
            continue
        row = conn.execute(text(
            'SELECT count(*), md5(coalesce(string_agg(t::text, %s ORDER BY t::text), %s)) '
            'FROM "%s" t' % ("'|'", "''", table))).one()
        out[table] = (row[0], row[1])
    return out


def _counts(conn: Connection) -> Dict[str, int]:
    return {t: conn.execute(text("SELECT count(*) FROM %s" % t)).scalar_one() for t in UNTOUCHED}


def _pick(conn: Connection, role: str, prefer: str, *, need_region: bool = False,
          global_scope: bool = False) -> Actor:
    row = conn.execute(text("""
        SELECT id FROM actor
         WHERE active AND role = :role
           AND (NOT :need_region OR region_id IS NOT NULL)
           AND (NOT :global_scope OR entity_id IS NULL)
         ORDER BY id = :prefer DESC, id LIMIT 1
    """), {"role": role, "prefer": prefer, "need_region": need_region,
           "global_scope": global_scope}).scalar()
    if row is None:
        raise LimitsError("no active %s actor; run `make seed` first" % role)
    return load_actor(conn, row)


def _entity_of_region(conn: Connection, region_id: str) -> Optional[str]:
    return conn.execute(text("""
        SELECT entity_id FROM clinic WHERE region_id = :r ORDER BY id LIMIT 1
    """), {"r": region_id}).scalar()


def _attempt(eng: Engine, actor: Actor, item_id: int, action: str) -> Optional[Denied]:
    """One action that should be refused, in a transaction of its own. The
    refusal's event commits on its own connection (transitions._record_denial),
    so it survives this rollback."""
    with eng.connect() as conn:
        try:
            with conn.begin():
                transition(conn, actor, item_id, action)
        except Denied as exc:
            return exc
    return None


# --------------------------------------------------------------------- run

def prove_limits(engines: Optional[Mapping[str, Engine]] = None) -> LimitsResult:
    """Run the three attempts and return what happened. `engines` maps role
    names to engines (tests pass their own); default: the configured ones."""
    if engines is None:
        from ..db.engine import engine
        engines = {role: engine(role) for role in ROLES}
    agent_db, api_db, reader_db = (engines[r] for r in ROLES)

    with reader_db.connect() as conn:
        agent = _pick(conn, "agent", "agent:checker")
        manager = _pick(conn, "regional_manager", "PER-RM-BAY", need_region=True)
        controller = _pick(conn, "controller", "PER-CTRL", global_scope=True)
        entity_id = manager.entity_id or _entity_of_region(conn, manager.region_id)
        before = _counts(conn)

    # The throwaway item: created and proposed by the agent, in the manager's region.
    with agent_db.begin() as conn:
        item = create_item(
            conn, agent, kind=DEMO_KIND, subject_type=DEMO_SUBJECT,
            subject_id="run-%s" % uuid.uuid4().hex[:12],
            title="Limits demo: a throwaway item to try forbidden actions on",
            entity_id=entity_id, region_id=manager.region_id,
            evidence={"purpose": "make prove-limits; not real work"})
        transition(conn, agent, item["id"], "propose", reason="ready for review",
                   patch={"proposal": "approve"})
    item_id = item["id"]
    result = LimitsResult(item_id=item_id, counts_before=before)

    # (a) The agent approves.
    refused = _attempt(agent_db, agent, item_id, "approve")
    if refused is None:
        result.allowed.append("(a) the agent approved item %s" % item_id)
    else:
        result.refusals.append(Refusal("(a)", "can()", refused.event.seq, agent.id,
                                       "approve", refused.reason))

    # (b) The agent asks the manager; the manager answers, then approves.
    with agent_db.begin() as conn:
        transition(conn, agent, item_id, "ask", patch={
            "asked_to": manager.id, "body": "Is this charge expected this month?"})
    with api_db.begin() as conn:
        transition(conn, manager, item_id, "answer", reason="Yes, it is expected.")
    refused = _attempt(api_db, manager, item_id, "approve")
    if refused is None:
        result.allowed.append("(b) %s approved the item they answered" % manager.id)
    else:
        result.refusals.append(Refusal("(b)", "can()", refused.event.seq, manager.id,
                                       "approve", refused.reason))

    # (c) The agent's own database role writes the ledger directly.
    with agent_db.connect() as conn:
        try:
            with conn.begin():
                conn.execute(text(RAW_SQL))
            db_error = None
        except DBAPIError as exc:
            db_error = str(exc.orig).splitlines()[0]
    if db_error is None:
        result.allowed.append("(c) lease_agent inserted into journal_entry")
    else:
        with agent_db.begin() as conn:
            state = conn.execute(text("SELECT state FROM work_item WHERE id = :i"),
                                 {"i": item_id}).scalar_one()
            event = append_event(
                conn, actor_id=agent.id, action="post", subject_type="work_item",
                subject_id=item_id, allowed=False,
                reason="database refused: %s" % db_error,
                diff={"from": state, "to": state, "set": {}},
                evidence={"db_role": "lease_agent", "sql": RAW_SQL})
        result.refusals.append(Refusal("(c)", "Postgres", event.seq, agent.id, "post",
                                       event.reason))

    # Out of the open queue: a controller rejects it and closes it.
    with api_db.begin() as conn:
        transition(conn, controller, item_id, "reject",
                   reason="Limits demo item; nothing to decide.")
        transition(conn, controller, item_id, "close", reason="Limits demo complete.")

    with reader_db.connect() as conn:
        stored = conn.execute(text("""
            SELECT seq, actor_id, action, allowed, reason FROM audit_event
             WHERE seq = ANY (:seqs) ORDER BY seq
        """), {"seqs": [r.seq for r in result.refusals]}).mappings().all()
        if any(row["allowed"] for row in stored) or len(stored) != len(result.refusals):
            result.allowed.append("a refusal is missing from the audit timeline")
        broken = verify_chain(conn)
        result.chain_ok = broken is None
        result.chain_problem = None if broken is None else "seq %s: %s" % (broken.seq,
                                                                            broken.problem)
        result.counts_after = _counts(conn)
        result.final_state = conn.execute(text("SELECT state FROM work_item WHERE id = :i"),
                                          {"i": item_id}).scalar_one()
    return result


def report(result: LimitsResult) -> str:
    lines = ["Limits demo on work item %s (%s)" % (result.item_id, DEMO_KIND), ""]
    lines.append("Refusals, as the audit timeline records them:")
    for r in result.refusals:
        lines.append("  %s seq %-6d %-14s %-8s refused by %-8s  %s"
                     % (r.label, r.seq, r.actor_id, r.action, r.layer, r.reason))
    for what in result.allowed:
        lines.append("  ALLOWED: %s" % what)
    lines.append("")
    changed = [t for t in UNTOUCHED
               if result.counts_before.get(t) != result.counts_after.get(t)]
    lines.append("Ledger, outbox, periods, payments, charges, lease versions: %s"
                 % ("unchanged" if not changed else "CHANGED: %s" % ", ".join(changed)))
    lines.append("Demo item: %s (rejected and closed by the controller)" % result.final_state)
    lines.append("verify_chain(): %s" % ("OK" if result.chain_ok else
                                          "BROKEN at %s" % result.chain_problem))
    lines.append("")
    lines.append("Every forbidden action was refused and is on record." if result.ok else
                 "A forbidden action was NOT refused. The limits are misconfigured.")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    from ..settings import get_settings
    if not get_settings().demo_mode:
        print("prove-limits: acts in a manager's name; refused unless LEASEDESK_DEMO_MODE=1",
              file=sys.stderr)
        return 2
    try:
        result = prove_limits()
    except LimitsError as exc:
        print("prove-limits: %s" % exc, file=sys.stderr)
        return 2
    print(report(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
