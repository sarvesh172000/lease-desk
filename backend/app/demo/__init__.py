"""The demo's own machinery: snapshots, a one-command reset, run summaries.

    snapshot.py   pg_dump of a freshly built demo database + a manifest
    reset.py      restore that snapshot over the demo database, verified, timed
    judge.py      tag events made from scenario-studio input as judge-provided
    summary.py    the month's run summary for the guided stepper

Everything that replaces data here is demo-mode only (LEASEDESK_DEMO_MODE=1)
and meant for the demo database alone: a reset replaces audit_event, which
nothing else in Lease Desk may ever do. See reset.py.
"""
