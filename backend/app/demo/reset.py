"""`make demo-reset`: put the demo database back to the snapshot, verified, in under 30 s.

    LEASEDESK_DB_PORT=5432 LEASEDESK_DB_NAME=leasedesk_demo make demo-reset   # host Postgres
    make demo-reset                                                            # Compose (:5433)

!!! DEMO DATABASE ONLY. A reset REPLACES audit_event. !!!
The audit stream is append-only everywhere else in Lease Desk: no role may
UPDATE, DELETE or TRUNCATE it and a trigger refuses even the owner. A reset
drops the table and restores the snapshot's copy, so every event since the
snapshot (approvals, denials, judge-provided studio input) is gone. That is
the point of a demo reset and is acceptable for the demo database alone, so
it refuses unless LEASEDESK_DEMO_MODE=1. Never point it at a database whose
history matters.

What it does, all as the database owner:

1. Checks the snapshot: the dump exists, matches its manifest's sha256, and
   was taken at the migration the code is at (else it is stale: rebuild it
   with `make demo-snapshot`; `make demo-reset` does that by itself).
2. Creates the database if it is missing and makes sure the four roles exist
   (they are cluster-wide, so the dump's GRANTs need them).
3. `pg_restore --clean --if-exists --no-owner --single-transaction`: one
   transaction, so a failure (say a worker holding a lock past
   lock_timeout) leaves the database exactly as it was.
4. Re-applies db/roles.sql, so the grants are the code's, not just the dump's.
5. Verifies: audit_verify_chain() is clean, every table's row count equals the
   manifest's, and the chain head (seq, hash) is the manifest's. Reports how
   many judge-provided events the reset cleared, and how long it all took.
"""

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import create_engine, text

from ..db.bootstrap import ROLES_SQL, apply_sql_file, execute_raw
from ..settings import DB_ROLES, get_settings
from .snapshot import (
    REPO_ROOT,
    SnapshotError,
    Target,
    code_head,
    load_manifest,
    owner_engine,
    pg_tool,
    snapshot_path,
    state,
    target,
)

BUDGET_SECONDS = 30.0
LOCK_TIMEOUT_MS = 15000


class ResetRefused(RuntimeError):
    """Demo mode is off: nothing was touched."""


class ResetFailed(RuntimeError):
    """pg_restore failed; its single transaction rolled back, nothing changed."""


@dataclass
class ResetResult:
    database: str
    seconds: float                 # the whole reset, checks included
    restore_seconds: float         # pg_restore alone
    snapshot: Dict[str, Any]       # created_at, git_sha, chain_head, file
    chain_ok: bool
    counts_match: bool
    head_match: bool
    judge_provided_cleared: int
    mismatches: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.chain_ok and self.counts_match and self.head_match

    @property
    def within_budget(self) -> bool:
        return self.seconds < BUDGET_SECONDS

    def as_dict(self) -> Dict[str, Any]:
        return {"database": self.database, "seconds": round(self.seconds, 3),
                "restore_seconds": round(self.restore_seconds, 3),
                "budget_seconds": BUDGET_SECONDS, "within_budget": self.within_budget,
                "snapshot": self.snapshot, "verified": self.ok, "chain_ok": self.chain_ok,
                "counts_match": self.counts_match, "head_match": self.head_match,
                "judge_provided_cleared": self.judge_provided_cleared,
                "mismatches": self.mismatches}


_ENSURE_ROLES = "DO $$ DECLARE r text; BEGIN FOREACH r IN ARRAY ARRAY[%s] LOOP " \
                "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN " \
                "EXECUTE format('CREATE ROLE %%I LOGIN', r); END IF; END LOOP; END $$;" \
                % ", ".join("'%s'" % r for r in DB_ROLES)


def check_snapshot(dump: Path) -> Dict[str, Any]:
    """The manifest of a usable snapshot, or SnapshotError saying why not."""
    manifest = load_manifest(dump)
    head = code_head()
    if manifest.get("alembic_version") != head:
        raise SnapshotError("snapshot %s was taken at migration %s, the code is at %s; "
                            "run `make demo-snapshot`" % (dump, manifest.get("alembic_version"), head))
    return manifest


def _ensure_database(t: Target) -> None:
    admin = create_engine(t.url("postgres"), isolation_level="AUTOCOMMIT",
                          connect_args={"connect_timeout": 5})
    try:
        with admin.connect() as conn:
            if conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"),
                            {"n": t.database}).first() is None:
                conn.execute(text('CREATE DATABASE "%s"' % t.database))
    finally:
        admin.dispose()


def reset_database(t: Target, dump: Path, *, demo_mode: bool,
                   lock_timeout_ms: int = LOCK_TIMEOUT_MS) -> ResetResult:
    """Restore `dump` over the database `t` and verify it against the manifest.

    DEMO DATABASE ONLY: this replaces audit_event (see the module docstring).
    Raises ResetRefused (demo mode off), SnapshotError (missing or stale
    snapshot, nothing touched) or ResetFailed (restore rolled back)."""
    if not demo_mode:
        raise ResetRefused("refusing to reset %s: a reset replaces the audit stream and is only "
                           "for the demo database with LEASEDESK_DEMO_MODE=1" % t.database)
    started = time.perf_counter()
    dump = Path(dump)
    manifest = check_snapshot(dump)
    restore_tool = pg_tool("pg_restore")

    _ensure_database(t)
    eng = owner_engine(t)
    try:
        with eng.begin() as conn:
            execute_raw(conn, _ENSURE_ROLES)
            had_audit = conn.execute(text("SELECT to_regclass('public.audit_event')")).scalar()
            judge_before = state(conn)["judge_provided"] if had_audit else 0

        r0 = time.perf_counter()
        proc = subprocess.run(
            [restore_tool, "--clean", "--if-exists", "--no-owner", "--single-transaction",
             "--exit-on-error", *t.cli_args(), str(dump)],
            env=t.env(PGOPTIONS="-c lock_timeout=%d" % lock_timeout_ms),
            capture_output=True, text=True)
        restore_seconds = time.perf_counter() - r0
        if proc.returncode != 0:
            raise ResetFailed("pg_restore into %s failed and rolled back: %s"
                              % (t.database, proc.stderr.strip()[-2000:]))

        with eng.begin() as conn:
            apply_sql_file(conn, ROLES_SQL)
        with eng.connect() as conn:
            now = state(conn)
    finally:
        eng.dispose()

    mismatches: Dict[str, Any] = {}
    counts = {k: (manifest["counts"].get(k), now["counts"].get(k))
              for k in set(manifest["counts"]) | set(now["counts"])}
    bad_counts = {k: {"snapshot": a, "now": b} for k, (a, b) in sorted(counts.items()) if a != b}
    if bad_counts:
        mismatches["counts"] = bad_counts
    if now["chain_head"] != manifest["chain_head"]:
        mismatches["chain_head"] = {"snapshot": manifest["chain_head"], "now": now["chain_head"]}
    if not now["chain_ok"]:
        mismatches["chain"] = "audit_verify_chain() reports a broken link"

    return ResetResult(
        database=t.database,
        seconds=time.perf_counter() - started,
        restore_seconds=restore_seconds,
        snapshot={"file": str(dump), "created_at": manifest.get("created_at"),
                  "git_sha": manifest.get("git_sha"), "chain_head": manifest.get("chain_head"),
                  "alembic_version": manifest.get("alembic_version")},
        chain_ok=now["chain_ok"],
        counts_match=not bad_counts,
        head_match=now["chain_head"] == manifest["chain_head"],
        judge_provided_cleared=max(0, judge_before - now["judge_provided"]),
        mismatches=mismatches,
    )


# ----------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Restore the demo snapshot (make demo-reset)")
    parser.add_argument("--snapshot", default=None, help="default: LEASEDESK_DEMO_SNAPSHOT or "
                        "ops/snapshots/demo.dump")
    parser.add_argument("--database", default=None, help="default: LEASEDESK_DB_NAME")
    parser.add_argument("--check", action="store_true",
                        help="only check the snapshot exists and is current (exit 1 if not)")
    args = parser.parse_args(argv)
    dump = Path(args.snapshot) if args.snapshot else snapshot_path()
    if not dump.is_absolute():
        dump = REPO_ROOT / dump

    if args.check:
        try:
            check_snapshot(dump)
        except SnapshotError as exc:
            print("demo-reset: %s; building it" % exc, file=sys.stderr)
            return 1
        return 0

    settings = get_settings()
    try:
        t = target(settings, args.database)
        print("demo-reset: restoring %s on %s:%d from %s" % (t.database, t.host, t.port, dump))
        result = reset_database(t, dump, demo_mode=settings.demo_mode)
    except (ResetRefused, SnapshotError, ResetFailed) as exc:
        print("demo-reset: %s" % exc, file=sys.stderr)
        return 1

    head = result.snapshot["chain_head"] or {}
    print("demo-reset: %s restored in %.2f s (pg_restore %.2f s; budget %.0f s: %s)" % (
        result.database, result.seconds, result.restore_seconds, BUDGET_SECONDS,
        "OK" if result.within_budget else "OVER"))
    print("  snapshot %s, git %s; chain head #%s %s" % (
        result.snapshot["created_at"], (result.snapshot["git_sha"] or "?")[:12], head.get("seq"),
        (head.get("hash") or "")[:16]))
    print("  chain verified: %s; row counts match manifest: %s; chain head matches: %s; "
          "judge-provided events cleared: %d" % (
              "yes" if result.chain_ok else "NO", "yes" if result.counts_match else "NO",
              "yes" if result.head_match else "NO", result.judge_provided_cleared))
    if not result.ok:
        print("demo-reset: verification FAILED: %s" % result.mismatches, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
