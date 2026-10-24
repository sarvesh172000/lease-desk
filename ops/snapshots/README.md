# Demo snapshots

`make demo-reset` puts the demo database back to the state a judge should see
first (the twelve January charges checked, five held for $25,736.36) in about
a second. The budget is 30 seconds (docs/PLAN.md, C2).

```bash
# host Postgres 16 on :5432, a demo database of its own
LEASEDESK_DB_PORT=5432 LEASEDESK_DB_NAME=leasedesk_demo make demo-reset

# Compose (`make up`): the database is on :5433, the default
make demo-reset                       # same as LEASEDESK_DB_PORT=5433
```

It prints the time and what it verified:

```
demo-reset: leasedesk_demo restored in 0.64 s (pg_restore 0.29 s; budget 30 s: OK)
  snapshot 2026-10-24T18:47:21Z, git 418b1198072b; chain head #78 eaca6e5eb9f23bf8
  chain verified: yes; row counts match manifest: yes; chain head matches: yes; judge-provided events cleared: 0
```

## What the files are

| File | What |
|---|---|
| `demo.dump` | `pg_dump --format=custom` of a freshly built demo database |
| `demo.manifest.json` | git sha, created at, migration, row count of every table, audit chain head (seq + hash), the dump's sha256 |

Both are generated and gitignored. Nothing here is committed but this README
and the `.gitignore`.

## `make demo-snapshot`

1. drops and creates a scratch database, `<LEASEDESK_DB_NAME>_snapshot`
   (only names ending in `_snapshot` can be dropped this way),
2. runs the existing `make demo-data` sequence in it (migrate, seed,
   dev passwords, `run-month 2026-01`, the Bay Area manager confirms the five
   leases, `run-month` again),
3. dumps it to `DEMO_SNAPSHOT` (default `ops/snapshots/demo.dump`) with the
   manifest, refusing if the chain does not verify or the data moved during
   the dump,
4. drops the scratch database.

The demo database itself is never touched by taking a snapshot.

## `make demo-reset`

Builds the snapshot first if it is missing, does not match its manifest, or
was taken at another migration than the code's. Then, as the database owner:

1. creates the database if missing and makes sure the four roles exist
   (roles are cluster-wide; the dump's GRANTs need them),
2. `pg_restore --clean --if-exists --no-owner --single-transaction`, with a
   15 s `lock_timeout`: a worker holding a lock makes it fail and roll back,
   never half-restore,
3. re-applies `backend/app/db/roles.sql`, so the grants are exactly the code's,
4. checks `audit_verify_chain()`, every table's row count against the
   manifest, and the chain head (seq and hash) against the manifest. Any
   mismatch exits non-zero.

**A reset replaces `audit_event`.** Everywhere else the audit stream is
append-only (no grant, and a trigger refuses even the owner). A reset drops
it and restores the snapshot's, so approvals, denials and judge-provided
studio input since the snapshot are gone. That is only acceptable for the
demo database, so it refuses unless `LEASEDESK_DEMO_MODE=1`. Never point it
at a database whose history matters.

## From the app

`POST /api/demo/reset` does the same for a signed-in controller
(`backend/app/api/demo.py`): 404 when demo mode is off, 403 plus an
`allowed = false` `demo_reset` event for anyone else, and for the controller
a `demo_reset` event right after the restored history, so the timeline shows
who reset it. 409 when there is no usable snapshot (run `make demo-snapshot`).
The frontend calls it with `resetDemo()` / `useDemoReset()` from
`frontend/lib`.

The API needs `pg_restore` 16+ and the snapshot file where it runs. On the
host (`make api`, `make demo`) both are there. The Compose `api` image has
neither the PostgreSQL client nor `ops/`, so there the button answers 409
(no snapshot) or, given one via `LEASEDESK_DEMO_SNAPSHOT`, 503 (no
`pg_restore`): use `make demo-reset` from the host against :5433 until the image ships them.

## Tools

`pg_dump` / `pg_restore` 16 or newer: `LEASEDESK_PG_BIN` (a directory) if
set, else `PATH`, else `/usr/lib/postgresql/16/bin` and the Homebrew
`postgresql@16` locations. Use the same major for dump and restore: an older
`pg_restore` cannot read a newer `pg_dump`'s archive. To use a different
snapshot file, set `DEMO_SNAPSHOT=path` for make or `LEASEDESK_DEMO_SNAPSHOT`
for the API.

## Judge-provided input

The scenario studio tags every event made from a judge's input with
`{"judge_provided": true}` in its evidence (`backend/app/demo/judge.py`:
`judge_evidence()`, `append_judge_event()`). The snapshot is taken before any
judge touches anything, so a reset clears them all; it prints how many.
