"""`make demo-snapshot`: a pg_dump of a freshly built demo database, plus a manifest.

    python -m app.demo.snapshot fresh-db leasedesk_snapshot     # drop + create the scratch db
    make demo-data LEASEDESK_DB_NAME=leasedesk_snapshot          # the existing demo sequence
    python -m app.demo.snapshot dump --database leasedesk_snapshot --out ops/snapshots/demo.dump
    python -m app.demo.snapshot drop-db leasedesk_snapshot

(`make demo-snapshot` runs exactly those four.) The snapshot is built in a
scratch database of its own, never in the demo database, so taking one cannot
damage the state a person is looking at. The dump is pg_dump's custom format
(-Fc); next to it, `demo.manifest.json` records what the restore must give
back:

    {"format": 1, "database": "leasedesk_snapshot", "created_at": "...Z",
     "git_sha": "418b119...", "git_dirty": false, "alembic_version": "0003",
     "counts": {"audit_event": 39, "work_item": 17, ...},
     "chain_head": {"seq": 39, "hash": "..."}, "chain_ok": true,
     "dump": {"file": "demo.dump", "bytes": 121929, "sha256": "..."}}

The dump and the manifest are generated files (ops/snapshots/.gitignore).
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from ..settings import Settings, get_settings
from .judge import count_judge_provided

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "backend"
DEFAULT_SNAPSHOT = REPO_ROOT / "ops" / "snapshots" / "demo.dump"
MANIFEST_FORMAT = 1
MIN_PG_MAJOR = 16

# Where pg_dump/pg_restore live when they are not first on PATH (or PATH has
# an older major): Debian/Ubuntu, Homebrew on Intel and Apple silicon.
PG_BIN_DIRS = ("/usr/lib/postgresql/16/bin", "/usr/local/opt/postgresql@16/bin",
               "/opt/homebrew/opt/postgresql@16/bin")

_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
SCRATCH_SUFFIX = "_snapshot"


class SnapshotError(RuntimeError):
    """The snapshot is missing, unreadable, stale, or could not be taken."""


# --------------------------------------------------------------- where things are

def snapshot_path() -> Path:
    """LEASEDESK_DEMO_SNAPSHOT, or ops/snapshots/demo.dump. Relative paths are
    relative to the repository root, where make runs."""
    raw = os.environ.get("LEASEDESK_DEMO_SNAPSHOT")
    if not raw:
        return DEFAULT_SNAPSHOT
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def manifest_path(dump: Path) -> Path:
    return dump.with_name(dump.stem + ".manifest.json")


def pg_tool(name: str) -> str:
    """The path of pg_dump / pg_restore, major version 16 or newer.

    LEASEDESK_PG_BIN (a directory) wins; then PATH; then the usual install
    locations. A dump made by a newer pg_dump cannot be read by an older
    pg_restore, so use the same major on both sides."""
    candidates: List[str] = []
    if os.environ.get("LEASEDESK_PG_BIN"):
        candidates.append(os.path.join(os.environ["LEASEDESK_PG_BIN"], name))
    found = shutil.which(name)
    if found:
        candidates.append(found)
    candidates.extend(os.path.join(d, name) for d in PG_BIN_DIRS)
    seen = []
    for path in candidates:
        if not os.access(path, os.X_OK):
            continue
        major = _major(path)
        seen.append("%s (%s)" % (path, major))
        if major is not None and major >= MIN_PG_MAJOR:
            return path
    raise SnapshotError("no %s %d+ found (tried: %s); install the PostgreSQL %d client "
                        "or set LEASEDESK_PG_BIN" % (name, MIN_PG_MAJOR, ", ".join(seen) or "none",
                                                     MIN_PG_MAJOR))


def _major(path: str) -> Optional[int]:
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"(\d+)(?:\.\d+)?", out)
    return int(match.group(1)) if match else None


# ------------------------------------------------------------------ the database

@dataclass(frozen=True)
class Target:
    """One database, reached as its owner (the only role that may restore)."""
    host: str
    port: int
    database: str
    user: str
    password: str

    def url(self, database: Optional[str] = None) -> str:
        return "postgresql+psycopg://%s:%s@%s:%d/%s" % (
            self.user, self.password, self.host, self.port, database or self.database)

    def cli_args(self) -> List[str]:
        return ["-h", self.host, "-p", str(self.port), "-U", self.user, "-d", self.database]

    def env(self, **extra: str) -> Dict[str, str]:
        env = dict(os.environ, PGPASSWORD=self.password, PGCONNECT_TIMEOUT="5")
        env.update(extra)
        return env


def target(settings: Optional[Settings] = None, database: Optional[str] = None) -> Target:
    settings = settings or get_settings()
    name = database or settings.db_name
    if not _NAME.match(name):
        raise SnapshotError("refusing an unusual database name %r" % name)
    return Target(settings.db_host, settings.db_port, name, settings.db_owner,
                  settings.db_owner_password)


def owner_engine(t: Target, database: Optional[str] = None, **kwargs: Any) -> Engine:
    return create_engine(t.url(database), connect_args={"connect_timeout": 5}, **kwargs)


def table_counts(conn: Connection) -> Dict[str, int]:
    """Row count of every table in the public schema, by name."""
    names = conn.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")).scalars()
    return {n: conn.execute(text('SELECT count(*) FROM public."%s"' % n)).scalar_one() for n in names}


def chain_head(conn: Connection) -> Optional[Dict[str, Any]]:
    """The newest audit event's seq and hash: two databases with the same head
    and a verified chain hold the same history."""
    if conn.execute(text("SELECT to_regclass('public.audit_event')")).scalar() is None:
        return None
    row = conn.execute(text("SELECT seq, hash FROM audit_event ORDER BY seq DESC LIMIT 1")).first()
    return {"seq": row.seq, "hash": row.hash} if row else None


def chain_ok(conn: Connection) -> bool:
    if conn.execute(text("SELECT to_regprocedure('public.audit_verify_chain()')")).scalar() is None:
        return False
    return conn.execute(text("SELECT broken_seq FROM audit_verify_chain()")).first() is None


def alembic_version(conn: Connection) -> Optional[str]:
    if conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar() is None:
        return None
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def code_head() -> Optional[str]:
    """The migration the code is at; a snapshot from another one is stale."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_current_head()


def state(conn: Connection) -> Dict[str, Any]:
    """What a snapshot promises and a reset is checked against."""
    has_audit = conn.execute(text("SELECT to_regclass('public.audit_event')")).scalar() is not None
    return {
        "alembic_version": alembic_version(conn),
        "counts": table_counts(conn),
        "chain_head": chain_head(conn),
        "chain_ok": chain_ok(conn),
        "judge_provided": count_judge_provided(conn) if has_audit else 0,
    }


def read_state(t: Target) -> Dict[str, Any]:
    eng = owner_engine(t)
    try:
        with eng.connect() as conn:
            return state(conn)
    finally:
        eng.dispose()


# --------------------------------------------------------------------- dump

def git_sha() -> Dict[str, Any]:
    def git(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
                                 timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    sha = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    return {"git_sha": sha, "git_dirty": None if dirty is None else bool(dirty)}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def take_snapshot(t: Target, out: Path) -> Dict[str, Any]:
    """pg_dump -Fc the target to `out` and write the manifest beside it.

    Refuses a database whose chain does not verify: a snapshot is the state
    every reset returns to, so it must be one worth returning to. The state is
    read before and after the dump and must not move in between."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    before = read_state(t)
    if not before["chain_ok"]:
        raise SnapshotError("the audit chain of %s does not verify; not snapshotting it" % t.database)
    if before["alembic_version"] is None:
        raise SnapshotError("%s has no schema; run the demo build first" % t.database)

    partial = out.with_name(out.name + ".partial")
    proc = subprocess.run([pg_tool("pg_dump"), "--format=custom", "--file", str(partial),
                           *t.cli_args()], env=t.env(), capture_output=True, text=True)
    if proc.returncode != 0:
        partial.unlink(missing_ok=True)
        raise SnapshotError("pg_dump failed: %s" % proc.stderr.strip()[-2000:])
    after = read_state(t)
    if after != before:
        partial.unlink(missing_ok=True)
        raise SnapshotError("%s changed while it was being dumped; stop the worker and retry"
                            % t.database)
    os.replace(partial, out)

    manifest = {
        "format": MANIFEST_FORMAT,
        "database": t.database,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **git_sha(),
        "alembic_version": before["alembic_version"],
        "counts": before["counts"],
        "chain_head": before["chain_head"],
        "chain_ok": before["chain_ok"],
        "judge_provided": before["judge_provided"],
        "dump": {"file": out.name, "bytes": out.stat().st_size, "sha256": sha256_file(out)},
    }
    tmp = manifest_path(out).with_suffix(".json.partial")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, manifest_path(out))
    return manifest


def load_manifest(dump: Path) -> Dict[str, Any]:
    """The manifest of `dump`, checked against the dump on disk."""
    dump = Path(dump)
    if not dump.is_file():
        raise SnapshotError("no snapshot at %s; run `make demo-snapshot`" % dump)
    path = manifest_path(dump)
    try:
        manifest = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise SnapshotError("snapshot manifest %s unreadable (%s); run `make demo-snapshot`"
                            % (path, exc)) from None
    if manifest.get("format") != MANIFEST_FORMAT:
        raise SnapshotError("snapshot manifest %s is format %r, expected %d; run `make demo-snapshot`"
                            % (path, manifest.get("format"), MANIFEST_FORMAT))
    if manifest.get("dump", {}).get("sha256") != sha256_file(dump):
        raise SnapshotError("%s does not match its manifest (was it replaced?); run `make demo-snapshot`"
                            % dump)
    return manifest


# ----------------------------------------------------------- scratch database

def _scratch_name(name: str) -> str:
    if not _NAME.match(name) or not name.endswith(SCRATCH_SUFFIX):
        raise SnapshotError("a scratch database name must end in %r, got %r" % (SCRATCH_SUFFIX, name))
    return name


def _admin(settings: Settings) -> Engine:
    return create_engine(settings.db_url("owner", "postgres"), isolation_level="AUTOCOMMIT",
                         connect_args={"connect_timeout": 5})


def drop_database(name: str, settings: Optional[Settings] = None) -> None:
    """Drop a scratch database (only names ending in `_snapshot`)."""
    name = _scratch_name(name)
    admin = _admin(settings or get_settings())
    try:
        with admin.connect() as conn:
            conn.execute(text('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % name))
    finally:
        admin.dispose()


def fresh_database(name: str, settings: Optional[Settings] = None) -> None:
    """Drop and create a scratch database, empty, for the demo build."""
    settings = settings or get_settings()
    drop_database(name, settings)
    admin = _admin(settings)
    try:
        with admin.connect() as conn:
            conn.execute(text('CREATE DATABASE "%s"' % name))
    finally:
        admin.dispose()


# ----------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Demo snapshots (make demo-snapshot)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fresh-db", help="drop and create an empty scratch database (*_snapshot)")
    p.add_argument("name")
    p = sub.add_parser("drop-db", help="drop a scratch database (*_snapshot)")
    p.add_argument("name")
    p = sub.add_parser("dump", help="pg_dump a database to the snapshot file, with its manifest")
    p.add_argument("--database", default=None, help="default: LEASEDESK_DB_NAME")
    p.add_argument("--out", default=None, help="default: LEASEDESK_DEMO_SNAPSHOT or %s"
                   % DEFAULT_SNAPSHOT.relative_to(REPO_ROOT))
    args = parser.parse_args(argv)

    try:
        if args.cmd == "fresh-db":
            fresh_database(args.name)
            print("demo-snapshot: scratch database %s is empty" % args.name)
        elif args.cmd == "drop-db":
            drop_database(args.name)
            print("demo-snapshot: scratch database %s dropped" % args.name)
        else:
            out = Path(args.out) if args.out else snapshot_path()
            if not out.is_absolute():
                out = REPO_ROOT / out
            m = take_snapshot(target(database=args.database), out)
            head = m["chain_head"] or {}
            print("demo-snapshot: %s -> %s (%d bytes)\n  git %s%s, migration %s, %d tables, "
                  "%d events, chain head #%s %s" % (
                      m["database"], out, m["dump"]["bytes"], (m["git_sha"] or "?")[:12],
                      " (dirty)" if m["git_dirty"] else "", m["alembic_version"], len(m["counts"]),
                      m["counts"].get("audit_event", 0), head.get("seq"), (head.get("hash") or "")[:16]))
    except SnapshotError as exc:
        print("demo-snapshot: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
