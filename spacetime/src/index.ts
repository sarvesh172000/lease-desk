// leasedesk-live: what the Lease Desk agents are doing, pushed to every open
// screen as it happens.
//
// This is a live feed, not the books. Postgres holds the ledger, the work
// states and the audit trail; nothing here is read back to decide anything.
// The agents write a line per step (agent_step) and the latest state of each
// exception they touched (desk_status); browsers subscribe to both.
//
// Writes come only from publishers the owner has authorized. Reducers are
// callable by anyone over HTTP, so without that check a stranger could put
// words in the agents' mouths on the demo screen.
//
//   spacetime publish leasedesk-live           (the publisher of record is the owner)
//   spacetime call leasedesk-live authorize_publisher <hex identity>

import { schema, table, t, SenderError } from 'spacetimedb/server';
import { Identity } from 'spacetimedb';

const owner = table(
  { name: 'owner' },
  {
    id: t.u8().primaryKey(),
    identity: t.identity(),
  }
);

const publisher = table(
  { name: 'publisher' },
  {
    identity: t.identity().primaryKey(),
  }
);

// One line per thing an agent did. `run_id` groups the lines of one request
// (one chat message), so a screen can show a run as a timeline.
const agentStep = table(
  { name: 'agent_step', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    run_id: t.string().index('btree'),
    agent: t.string(),          // coordinator | investigation | ...
    kind: t.string(),           // intent | searching | found | remeasured | complete | action | error
    detail: t.string(),
    exception_id: t.string(),   // "" when the step is about no one exception
    at: t.timestamp(),
  }
);

// The latest the agents know of each exception, so a screen updates the moment
// something is approved or held from ASI:One. Figures are as the API gave them.
const deskStatus = table(
  { name: 'desk_status', public: true },
  {
    exception_id: t.string().primaryKey(),
    lease_id: t.string(),
    charge_type: t.string(),
    billed: t.f64(),
    supported: t.f64(),
    status: t.string(),         // exception | pending_review | escalated | balanced
    updated_by: t.string(),
    at: t.timestamp(),
  }
);

const spacetimedb = schema({ owner, publisher, agentStep, deskStatus });
export default spacetimedb;

function requirePublisher(ctx: { sender: Identity; db: any }) {
  if (!ctx.db.publisher.identity.find(ctx.sender)) {
    throw new SenderError('not an authorized publisher');
  }
}

function clip(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n - 1) + '…';
}

// Whoever publishes the module owns it.
export const init = spacetimedb.init(ctx => {
  ctx.db.owner.insert({ id: 0, identity: ctx.sender });
});

export const authorizePublisher = spacetimedb.reducer(
  { identity: t.string() },
  (ctx, { identity }) => {
    const row = ctx.db.owner.id.find(0);
    if (!row || !row.identity.isEqual(ctx.sender)) {
      throw new SenderError('only the owner authorizes publishers');
    }
    const who = Identity.fromString(identity);
    if (!ctx.db.publisher.identity.find(who)) {
      ctx.db.publisher.insert({ identity: who });
    }
  }
);

export const recordStep = spacetimedb.reducer(
  {
    run_id: t.string(),
    agent: t.string(),
    kind: t.string(),
    detail: t.string(),
    exception_id: t.string(),
  },
  (ctx, { run_id, agent, kind, detail, exception_id }) => {
    requirePublisher(ctx);
    ctx.db.agentStep.insert({
      id: 0n,
      run_id: clip(run_id, 64),
      agent: clip(agent, 40),
      kind: clip(kind, 40),
      detail: clip(detail, 2000),
      exception_id: clip(exception_id, 40),
      at: ctx.timestamp,
    });
  }
);

export const upsertStatus = spacetimedb.reducer(
  {
    exception_id: t.string(),
    lease_id: t.string(),
    charge_type: t.string(),
    billed: t.f64(),
    supported: t.f64(),
    status: t.string(),
    updated_by: t.string(),
  },
  (ctx, args) => {
    requirePublisher(ctx);
    const row = { ...args, at: ctx.timestamp };
    if (ctx.db.deskStatus.exception_id.find(args.exception_id)) {
      ctx.db.deskStatus.exception_id.update(row);
    } else {
      ctx.db.deskStatus.insert(row);
    }
  }
);
