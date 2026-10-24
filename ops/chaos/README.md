# Chaos

Lease Desk must recover from a killed worker, a dead model provider, a dead
mail server, a lost database connection, a re-delivered sync file and work
arriving out of order, without losing or doubling anything (PHASE_3 group 4,
the C3 gate in docs/PLAN.md: *kill the worker mid-run: it finishes with
identical results*).

```bash
LEASEDESK_DB_PORT=5432 make chaos          # host Postgres 16
make chaos                                 # Compose (:5433)
CHAOS_SOAK=0 make chaos                    # skip the soak

# the same checks as tests
LEASEDESK_DB_PORT=5432 python3 -m pytest -q -p no:cacheprovider backend/tests/platform/test_chaos_*.py
```

`make chaos` creates two scratch databases (`leasedesk_chaos_a_*`,
`leasedesk_chaos_b_*`), migrates and seeds both, runs January on each with a
real `python -m app.jobs.worker` process, compares, and drops them:

```
C3 chaos: kill the worker mid-run, it finishes with identical results

  A  uninterrupted January                         3.9s
  B  January, worker SIGKILLed twice mid-job        6.1s
       kill during abstraction job #2 (abstraction, attempt 1): worker pid 14774, backend 14789 blocked at lease_version|LEASE-03; partial work written: yes; restart exit 0
       kill during checking    job #7 (checking, attempt 1): worker pid 14922, backend 14924 blocked at work_item|CHARGE_CHECK|landlord_charge|0d1f...; partial work written: yes; restart exit 0

  rows compared: lease_version 5, lease_term 65, agent_run 5, work_item 17, question 0, journal_entry 10, journal_line 20, outbox 1, job 4, sync_cursor 4, audit_event 64
  A == B: identical (work items, versions, terms, runs, journal, outbox, jobs, per-subject event sequences)
  A: verify_chain ok, replay == live yes, trial balance 87023.33 / 87023.33 balanced
  B: verify_chain ok, replay == live yes, trial balance 87023.33 / 87023.33 balanced
  soak: January 20 more times on A in 21.4s: nothing grew; chain, replay and trial balance held every run

  PASS in 37.0s
```

"January" is the month as people run it: run (ingest, abstraction drafts the
five lease versions, checking waits), the regional manager confirms, run again
(the re-check proposes twelve charge checks), approve, post, release the AP
batch, send it.

## Scenarios, what must happen, and where it is asserted

| Fault | How it is injected | Must happen | Test |
|---|---|---|---|
| Worker killed mid-month | SIGKILL a real worker process parked *inside* a job with partial work written (`harness.KillPoint`, below) | The restarted worker puts the job back at once and re-runs it; the end state equals an uninterrupted run, row for row and event for event | `test_chaos_acceptance.py`, `make chaos` |
| Worker dies, a job keeps killing it | a claimed job whose backend is terminated, `MAX_ATTEMPTS` times | Put back each time, then dead (never loops) | `test_chaos_worker.py` |
| Model provider errors | `faults.ProviderDown`: every call raises the SDK's `APIConnectionError` | One failed call: that lease falls back to the generator path, on record (`path_note`) and still in front of a person. An outage (breaker open): the job is **held** (requeued until the breaker probes, attempt not spent, everything it drafted rolled back), then finishes on the LLM path when the provider is back. A cached answer is served while the breaker is open. A lease nothing can read becomes a `LEASE_UNREADABLE` item, HELD, never a silent pass | `test_chaos_llm.py` |
| Mail / outbox target down | `faults.outbox_target_down()` (deliverer raises `ConnectionRefusedError`) or `faults.blocked_directory()` (the outbox dir replaced by a file: fails even as root, unlike chmod) | The row stays pending for as many sends as the outage lasts, then is sent exactly once; one file | `test_chaos_outbox.py` |
| DB lost between delivery and record | the sender's backend terminated right after the file is written | Not recorded, so delivered again under the same file name, recorded once | `test_chaos_outbox.py` |
| DB connection lost mid-job | the job's backend terminated mid-transaction | The job's writes roll back, it is retried in the same drain (no backoff for a dropped connection), its writes land once | `test_chaos_worker.py` |
| Database goes away while the worker serves | `faults.FlakyProxy` between worker and Postgres, taken down mid-job, brought back | The worker process stays up, waits, recovers the orphaned job and finishes it once | `test_chaos_worker.py` |
| Same sync file twice | `faults.deliver_sync_twice()`, then `seed` again; and two deliveries at once | Nothing added (ids are `md5(source\|source_id)`), the month's results unchanged | `test_chaos_inputs.py` |
| Jobs and events out of order | a checking job before the month; the month requested twice at once; confirmations and approvals delivered twice; post and release before anything is approved; release before post | Refused or no-ops where early, no duplicates, and the end state equals an orderly month | `test_chaos_inputs.py` |
| Soak | January then 20 more passes (in `make chaos` against a real worker too) | Nothing grows after the first pass; chain, replay, trial balance hold every pass | `test_chaos_soak.py`, `make chaos` |

## Substitutions (and why)

- **"Restart Postgres" is simulated per connection.** The cluster is shared
  with other agents and teammates, so nothing here restarts it. A crashed
  server or a cut network looks the same to the worker as its backend being
  terminated (`pg_terminate_backend`, which a role may do to its own sessions)
  or a proxy dropping every connection and refusing new ones (`FlakyProxy`).
  Both are used. Every database this touches is a throwaway one.
- **"Stop Mailpit"**: Mailpit is not in Compose yet. The outbox delivers AP
  batch files; its target failing is the deliverer raising
  `ConnectionRefusedError`, or the outbox directory being unwritable.
- **"Three simulated years"**: only January is seeded, so the soak repeats
  January instead and checks that nothing grows.

## How a kill lands mid-job, every time

A `KillPoint` holds, on an owner connection, the advisory lock the job will
take next: `lease_version|LEASE-03` (taken by `draft_versions` before drafting
the third lease) or `work_item|CHARGE_CHECK|landlord_charge|<id>` (taken by
`create_item` for the finding the checker records last). The worker blocks
there inside its job's transaction. The harness waits until `pg_locks` shows
that backend waiting on the lock *and* holding `RowExclusiveLock` on the table
it has been writing (proof of uncommitted partial work), then SIGKILLs the
process and lets go of the lock.

## What makes recovery work (backend/app/jobs/recovery.py)

- **Liveness from Postgres.** While a worker runs a job it holds a
  session-level advisory lock on it, taken in the claim's own transaction. A
  dead worker's connection drops and the lock with it, so `recover()` can tell
  a dead worker's job from a live one by trying the lock: no timeout, no
  window. `drain()` and `serve()` recover on start; `serve()` again on every
  heartbeat and after a database outage. `queue.release_stale()` stays as the
  backstop for a worker that is alive but hung.
- **`client_connection_check_interval`** on the job connection, so a killed
  worker's backend that is blocked on a lock notices its client is gone within
  a second and rolls back.
- **Holds.** A handler raising `JobHeld` is requeued for later without
  spending an attempt; the circuit breaker (`backend/app/work/breaker.py`)
  makes a provider outage raise it. Breaker state: `breaker.states()` in
  process, `breaker.read_published(conn)` for the ops page (the worker
  publishes to `sync_cursor` as `breaker:<name>` whenever a breaker changes).

## Fault scripts against a running stack

```bash
python -m ops.chaos.faults kill-worker --when-running <pid>   # SIGKILL once it holds a job
python -m ops.chaos.faults drop-worker-db                     # terminate lease_agent sessions
python -m ops.chaos.faults db-proxy --listen 6543 --down-every 20 --down-for 5
python -m ops.chaos.faults duplicate-sync --data data/generated
python -m ops.chaos.faults outbox-down data/outbox && python -m ops.chaos.faults outbox-up data/outbox
```
