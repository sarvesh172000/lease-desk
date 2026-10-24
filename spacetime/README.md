# leasedesk-live (SpacetimeDB)

The live feed behind Lease Desk's agents. While someone talks to the agent in
ASI:One, every step it takes (what it understood, each document the
investigation found, the remeasurement, an approval) lands here, and every
browser subscribed to the module sees it at once.

It is a feed, not the books. Postgres keeps the ledger, the work states and the
audit trail; nothing reads this module back to decide anything, and the agent
carries on unchanged if SpacetimeDB is down.

## Tables

| Table | Public | Row |
|---|---|---|
| `agent_step` | yes | one thing an agent did: `run_id` (one chat message), `agent`, `kind`, `detail`, `exception_id`, `at` |
| `desk_status` | yes | latest known state of each exception: figures as the API gave them, `status`, `updated_by`, `at` |
| `owner` | no | whoever published the module |
| `publisher` | no | identities allowed to write |

Reducers: `record_step`, `upsert_status` (authorized publishers only),
`authorize_publisher` (owner only). Anyone can call a reducer over HTTP, so
without the publisher check a stranger could write lines on the demo screen.

## Set up

```bash
# the CLI: https://spacetimedb.com/install (2.13.0, matching package.json)
cd spacetime && npm install && npm run typecheck
spacetime login
spacetime publish -p spacetime leasedesk-live     # Maincloud, from the repo root
```

Locally, on 3100 so it doesn't collide with the web app on 3000:

```bash
spacetime start --listen-addr 127.0.0.1:3100
spacetime publish -s http://127.0.0.1:3100 -p spacetime -y leasedesk-live
```

Pass the same `-s http://127.0.0.1:3100` to `call`, `sql` and `generate`
below, and set `SPACETIME_HOST=http://127.0.0.1:3100` for the agent.

A publisher for the agent, once:

```bash
python -m fetch.live identity          # prints an identity and its token
spacetime call leasedesk-live authorize_publisher <identity>
```

Then run the agent with:

| Variable | |
|---|---|
| `SPACETIME_DB` | `leasedesk-live` |
| `SPACETIME_TOKEN` | the token printed above (secret) |
| `SPACETIME_HOST` | default `https://maincloud.spacetimedb.com`; `http://localhost:3000` for a local server |

Watch it work:

```bash
spacetime sql leasedesk-live "SELECT * FROM agent_step"
```

## In the browser

Generate typed bindings and subscribe with the React hooks from
`spacetimedb/react`:

```bash
spacetime generate --lang typescript --out-dir <app>/src/module_bindings --module-path spacetime
```

```ts
DbConnection.builder()
  .withUri('ws://127.0.0.1:3100')            // wss://maincloud.spacetimedb.com on Maincloud
  .withDatabaseName('leasedesk-live')
  .onConnect(conn => {
    conn.db.agentStep.onInsert((_ctx, s) => show(s));
    conn.subscriptionBuilder().subscribe([tables.agentStep, tables.deskStatus]);
  })
  .build();
```

The generated client is camelCase throughout: the tables are
`agentStep` / `deskStatus`, and the fields are `runId`, `exceptionId`,
`updatedBy` and so on. The snake_case names are only the server's and
the HTTP API's.

## Verified locally

With a local server, the agent pointed at the real Lease Desk API, and a
WebSocket subscriber built from these bindings:

- An unauthorized identity, an anonymous caller, and a publisher trying to
  authorize itself are all refused (HTTP 530). After the owner authorizes the
  publisher, its writes land.
- Each step and status reached the subscriber about 10–40 ms after the agent
  sent it, with no failed sends.
