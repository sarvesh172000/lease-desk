"""The pieces every chaos scenario is built from.

  ScratchDB            a throwaway database on the configured Postgres:
                       created, migrated from empty, dropped afterwards. Never
                       the shared one, never a restart of the cluster.
  generate / seed_db   the generated company, loaded the way `make seed` does.
  Worker               a real `python -m app.jobs.worker` subprocess against
                       one database, which can be SIGKILLed.
  KillPoint            parks the worker at a known point *inside* a job, so
                       the kill lands mid-transaction with partial work done:
                       it holds the advisory lock the job takes next (the
                       lock `draft_versions` takes per lease, or the one
                       `create_item` takes per work item) on an owner
                       connection, waits until the worker's backend is
                       blocked on it while holding row locks on the table it
                       has been writing, and only then lets the caller kill.
  january              the month as people run it: run, confirm, run again,
                       approve, post, release, send.
  canonical_state      every table January writes, with ids, timestamps and
                       hashes replaced by natural keys, so two databases that
                       did the same work compare equal.
"""

import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
for _p in (str(REPO), str(BACKEND)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.db.engine import make_engine  # noqa: E402
from app.settings import DB_ROLES, get_settings  # noqa: E402

JAN = date(2026, 1, 1)
ENTITY = "ENT-CA"
RM_BAY = "PER-RM-BAY"
AP = "PER-AP"
LEASES = ("LEASE-01", "LEASE-02", "LEASE-03", "LEASE-04", "LEASE-05")


class ChaosError(AssertionError):
    """A scenario did not go the way it must."""


# ------------------------------------------------------------- databases

def admin_engine() -> Engine:
    url = os.environ.get("LEASEDESK_TEST_ADMIN_URL") or get_settings().db_url("owner", "postgres")
    return create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})


def migrate(name: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", get_settings().db_url("owner", name))
    command.upgrade(cfg, "head")


class ScratchDB:
    """`with ScratchDB("a") as db:` -> db.name, db.engines[role]."""

    def __init__(self, tag: str = "x"):
        self.name = "leasedesk_chaos_%s_%s" % (tag, uuid.uuid4().hex[:8])
        self.engines: Dict[str, Engine] = {}
        self._admin = admin_engine()

    def __enter__(self) -> "ScratchDB":
        with self._admin.connect() as conn:
            conn.execute(text('CREATE DATABASE "%s"' % self.name))
        migrate(self.name)
        self.engines = {role: make_engine(role, self.name) for role in DB_ROLES + ("owner",)}
        return self

    def __exit__(self, *exc) -> None:
        for eng in self.engines.values():
            eng.dispose()
        drop_database(self._admin, self.name)
        self._admin.dispose()


def drop_database(admin: Engine, name: str) -> None:
    for attempt in range(30):
        try:
            with admin.connect() as conn:
                conn.execute(text('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % name))
            return
        except ProgrammingError as exc:
            if attempt == 29:
                warnings.warn("could not drop %s: %s" % (name, str(exc.orig).splitlines()[0]),
                              stacklevel=2)
                return
            time.sleep(0.2)


ALL_TABLES = (
    "source_document, raw_row, sync_cursor, entity, region, landlord, center, clinic, "
    "lease, landlord_charge, payment, lease_version, lease_term, agent_run, tool_call, "
    "work_item, question, policy, job, account, period, journal_entry, journal_line, "
    "outbox, audit_event, actor"
)


def truncate_all(engines: Mapping[str, Engine]) -> None:
    """Empty a scratch database (owner only; audit_event's own guard is
    switched off for the one statement, as the platform tests do)."""
    from app.db.bootstrap import execute_raw

    with engines["owner"].begin() as conn:
        execute_raw(conn, "ALTER TABLE audit_event DISABLE TRIGGER audit_event_no_truncate;"
                          "TRUNCATE %s RESTART IDENTITY CASCADE;"
                          "ALTER TABLE audit_event ENABLE TRIGGER audit_event_no_truncate;"
                          % ALL_TABLES)


# ------------------------------------------------------------- the company

def generate(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(out)],
                   cwd=REPO, check=True, capture_output=True)
    return out


def seed_db(engines: Mapping[str, Engine], data_dir: Path) -> dict:
    from app.records.seed import seed

    return seed(Path(data_dir), engines["lease_agent"], engines["lease_gateway"])


# ---------------------------------------------------------------- worker

def worker_env(database: str, data_dir: Path) -> Dict[str, str]:
    """The environment a worker subprocess runs in: this database, the
    generated documents, and no model (no key, no cache): offline and
    deterministic, like the suite."""
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.update(LEASEDESK_DB_NAME=database, LEASEDESK_DATA_DIR=str(data_dir),
               LEASEDESK_LLM_CACHE=str(Path(data_dir) / "no-llm-cache-here"),
               PYTHONPATH=os.pathsep.join([str(BACKEND), str(REPO)]))
    return env


class Worker:
    """A real worker process. `once` drains and exits; otherwise it serves
    until stopped."""

    def __init__(self, database: str, data_dir: Path, log_dir: Path, *, once: bool = True,
                 name: str = "worker"):
        self.log_path = Path(log_dir) / ("%s-%s.log" % (name, uuid.uuid4().hex[:6]))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = open(self.log_path, "wb")
        args = [sys.executable, "-m", "app.jobs.worker"] + (["--once"] if once else [])
        self.proc = subprocess.Popen(args, cwd=REPO, env=worker_env(database, data_dir),
                                     stdout=self._log, stderr=subprocess.STDOUT)

    @property
    def pid(self) -> int:
        return self.proc.pid

    def wait(self, timeout: float = 120) -> int:
        try:
            return self.proc.wait(timeout=timeout)
        finally:
            self._log.close()

    def kill(self) -> int:
        """SIGKILL: no handler runs, nothing is flushed, the connection just drops."""
        self.proc.send_signal(signal.SIGKILL)
        return self.wait(30)

    def log(self) -> str:
        try:
            return self.log_path.read_text(errors="replace")
        except OSError:
            return ""


def run_worker(database: str, data_dir: Path, log_dir: Path) -> None:
    worker = Worker(database, data_dir, log_dir)
    code = worker.wait()
    if code != 0:
        raise ChaosError("worker exited %d:\n%s" % (code, worker.log()[-3000:]))


# ------------------------------------------------------------- kill points

@dataclass
class KillPoint:
    """Hold the advisory lock `key` (hashtext form, as the job takes it) so a
    worker reaching it blocks there, inside its job's transaction."""
    engines: Mapping[str, Engine]
    key: str
    table: str                       # the table the job has been writing before the lock
    _conn: Any = None
    backend_pid: Optional[int] = None

    def __enter__(self) -> "KillPoint":
        self._conn = self.engines["owner"].connect()
        self._conn.execute(text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": self.key})
        self._conn.commit()
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    def release(self) -> None:
        if self._conn is not None:
            self._conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": self.key})
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def wait_blocked(self, timeout: float = 60) -> int:
        """The pid of the backend blocked on our lock, once it is."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.engines["owner"].connect() as conn:
                pid = conn.execute(text("""
                    SELECT l.pid FROM pg_locks l
                     WHERE l.locktype = 'advisory' AND NOT l.granted
                       AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
                       AND l.objsubid = 1 AND l.objid = (hashtext(:k)::bigint & 4294967295)::oid
                     LIMIT 1
                """), {"k": self.key}).scalar()
            if pid is not None:
                self.backend_pid = pid
                return pid
            time.sleep(0.02)
        raise ChaosError("no worker blocked on %r within %ss" % (self.key, timeout))

    def partial_work(self) -> bool:
        """True when the blocked backend has already written to `table` in
        its open transaction (it holds RowExclusiveLock on it)."""
        with self.engines["owner"].connect() as conn:
            return bool(conn.execute(text("""
                SELECT EXISTS (SELECT 1 FROM pg_locks
                                WHERE pid = :pid AND locktype = 'relation' AND granted
                                  AND mode = 'RowExclusiveLock' AND relation = CAST(:t AS regclass))
            """), {"pid": self.backend_pid, "t": self.table}).scalar())


def backend_gone(engines: Mapping[str, Engine], pid: int, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with engines["owner"].connect() as conn:
            if not conn.execute(text("SELECT 1 FROM pg_stat_activity WHERE pid = :p"),
                                {"p": pid}).first():
                return
        time.sleep(0.05)
    raise ChaosError("backend %d of the killed worker is still there after %ss" % (pid, timeout))


@dataclass
class Kill:
    step: str
    key: str
    worker_pid: int
    backend_pid: int
    partial: bool
    job: Dict[str, Any]
    restart_exit: int = 0


def kill_point_for(engines: Mapping[str, Engine], step: str) -> KillPoint:
    """Where to park the worker for a kill during `step`:

      abstraction  the lock draft_versions takes before drafting LEASE-03, so
                   LEASE-01 and LEASE-02 are drafted (uncommitted) at the kill
      checking     the lock create_item takes for the charge whose finding the
                   checker records last, so every item before it is written
                   (uncommitted) at the kill
    """
    if step == "abstraction":
        return KillPoint(engines, "lease_version|%s" % LEASES[2], "lease_version")
    if step == "checking":
        charge = last_finding_charge(engines)
        return KillPoint(engines, "work_item|CHARGE_CHECK|landlord_charge|%s" % charge, "work_item")
    raise ValueError("no kill point for step %r" % step)


def last_finding_charge(engines: Mapping[str, Engine]) -> str:
    """The landlord_charge id of the last finding the re-check will record:
    the checker is deterministic, so ask it, read-only, before the worker runs."""
    from app.agents.checker import check_month
    from app.jobs.lease_versions import confirmed_rules
    from app.jobs.monthly import charge_ids_by_source_id, load_charges

    with engines["lease_agent"].connect() as conn:
        charges = load_charges(conn, ENTITY, JAN)
        confirmed = confirmed_rules(conn, ENTITY)
        ready = [c for c in charges if c.lease_id in confirmed.rules]
        findings = check_month(ready, confirmed.rules, JAN)
        if not findings:
            raise ChaosError("the re-check would record nothing; no kill point inside it")
        last = findings[-1].charge.charge_id
        return charge_ids_by_source_id(conn, [last])[last]


def run_worker_killed_mid(database: str, engines: Mapping[str, Engine], data_dir: Path,
                          log_dir: Path, step: str) -> Kill:
    """Start a worker, SIGKILL it inside `step` with partial work written,
    then restart it and let it finish. Returns what happened."""
    with kill_point_for(engines, step) as point:
        worker = Worker(database, data_dir, log_dir, name="doomed")
        try:
            backend = point.wait_blocked()
        except ChaosError:
            worker.kill()
            raise ChaosError("worker never reached the %s kill point:\n%s"
                             % (step, worker.log()[-3000:])) from None
        partial = point.partial_work()
        with engines["owner"].connect() as conn:
            job = dict(conn.execute(text("""
                SELECT id, kind, status, attempts, locked_by FROM job
                 WHERE status = 'running' ORDER BY id DESC LIMIT 1""")).mappings().first() or {})
        worker.kill()
    # The killed worker's backend is blocked on our lock; once we let go it
    # notices its client is gone (client_connection_check_interval) and exits,
    # rolling back everything the job wrote.
    backend_gone(engines, backend)
    restarted = Worker(database, data_dir, log_dir, name="restarted")
    code = restarted.wait()
    if code != 0:
        raise ChaosError("restarted worker exited %d:\n%s" % (code, restarted.log()[-3000:]))
    return Kill(step, point.key, worker.pid, backend, partial, job, code)


# ---------------------------------------------------------------- January

@dataclass
class MonthLog:
    steps: List[str] = field(default_factory=list)
    kills: List[Kill] = field(default_factory=list)


def enqueue_month(engines: Mapping[str, Engine]) -> Dict[str, int]:
    from app.jobs.monthly import run_month

    with engines["lease_agent"].begin() as conn:
        return run_month(conn, ENTITY, JAN)


def approve_all(engines: Mapping[str, Engine]) -> int:
    """The Bay Area manager approves every proposed charge check: a good
    charge is approved, a hold is upheld."""
    from app.work.charges import approve_charge
    from app.work.roles import load_actor

    with engines["lease_api"].begin() as conn:
        ids = conn.execute(text("SELECT id FROM work_item WHERE kind = 'CHARGE_CHECK' "
                                "AND state = 'PROPOSED' ORDER BY id")).scalars().all()
        actor = load_actor(conn, RM_BAY)
        for item_id in ids:
            approve_charge(conn, actor, item_id)
    return len(ids)


def january(engines: Mapping[str, Engine], worker: Callable[[str], None], out_dir: Path,
            log: Optional[MonthLog] = None, *, send: bool = True) -> MonthLog:
    """One January, start to finish. `worker(step)` drains the queue; `step`
    names the job the caller may want to interrupt ("abstraction" on the
    first run, "checking" on the re-check). send=False stops after the
    release, with the batch still pending in the outbox."""
    from app.work.confirm_leases import confirm_all
    from app.work.gateway import post_approved, release_batch, send_outbox
    from app.work.roles import load_actor

    log = log or MonthLog()
    enqueue_month(engines)
    worker("abstraction")
    log.steps.append("run: ingest, abstraction (drafts), checking (waits)")
    with engines["lease_api"].begin() as conn:
        confirm_all(conn, load_actor(conn, RM_BAY), ENTITY)
    log.steps.append("confirm: %s" % RM_BAY)
    enqueue_month(engines)
    worker("checking")
    log.steps.append("run again: re-check against confirmed terms")
    log.steps.append("approve: %d charge checks" % approve_all(engines))
    with engines["lease_gateway"].begin() as conn:
        posted = post_approved(conn, ENTITY, JAN)
    log.steps.append("post: %d items" % len(posted))
    with engines["lease_gateway"].begin() as conn:
        release_batch(conn, JAN, AP, entity_id=ENTITY)
    if not send:
        log.steps.append("release (not sent)")
        return log
    with engines["lease_gateway"].connect() as conn:
        sent = send_outbox(conn, out_dir)
    log.steps.append("release + send: %d outbox row(s)" % len(sent))
    return log


# -------------------------------------------------------- canonical state

# Columns that are ids, clocks or hashes: compared as "present or not" (clocks)
# or dropped (ids, hashes); never by value.
_DROP = {"id", "seq", "prev_hash", "hash", "password_hash", "last_event_seq"}
_CLOCKS = {"at", "created_at", "updated_at", "confirmed_at", "sent_at", "posted_at",
           "locked_at", "run_after", "finished_at", "started_at", "asked_at", "answered_at",
           "closed_at", "due_at"}
_VOLATILE_JOB = {"attempts", "last_error", "locked_by"}

STATE_TABLES = ("lease_version", "lease_term", "agent_run", "work_item", "question",
                "journal_entry", "journal_line", "outbox", "job", "sync_cursor")


class _Maps:
    """id -> natural key, per table."""

    def __init__(self, conn):
        def pairs(sql):
            return {r[0]: r[1] for r in conn.execute(text(sql))}

        self.lease_version = pairs("SELECT id, lease_id || '/v' || version FROM lease_version")
        self.agent_run = pairs("""
            SELECT r.id, coalesce(min(v.lease_id || '/v' || v.version), 'run') || ':' || r.agent
              FROM agent_run r
              LEFT JOIN lease_term t ON t.extracted_by_run = r.id
              LEFT JOIN lease_version v ON v.id = t.lease_version_id
             GROUP BY r.id, r.agent""")
        self.journal_entry = pairs("SELECT id, idempotency_key FROM journal_entry")
        self.outbox = pairs("SELECT id, idempotency_key FROM outbox")
        self.account = pairs("SELECT id, entity_id || ':' || name FROM account")
        self.job = pairs("SELECT id, coalesce(idempotency_key, kind || '#' || id) FROM job")
        self.question = pairs("""
            SELECT q.id, q.work_item_id::text || '#' ||
                   row_number() OVER (PARTITION BY q.work_item_id ORDER BY q.id) FROM question q""")
        self.work_item = {}
        for wid, kind, st, sid in conn.execute(text(
                "SELECT id, kind, subject_type, subject_id FROM work_item")):
            self.work_item[wid] = "%s|%s|%s" % (kind, st, self.subject(st, sid))

    def subject(self, subject_type: str, subject_id: Any) -> str:
        if subject_type == "lease_version":
            return str(self.lease_version.get(_int(subject_id), subject_id))
        if subject_type == "work_item":
            return str(self.work_item.get(_int(subject_id), "work_item:%s" % subject_id))
        return str(subject_id)

    def fingerprint(self, value: str) -> str:
        """A confirmed-set fingerprint ('3,4,5') or a key ending in one."""
        head, sep, tail = value.rpartition("@") if "@" in value else ("", "", value)
        parts = tail.split(",")
        if parts and all(p.isdigit() for p in parts):
            tail = ",".join(sorted(str(self.lease_version.get(int(p), p)) for p in parts))
        return head + sep + tail


def _int(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


_ID_KEYS = {
    "lease_version_id": "lease_version", "agent_run_id": "agent_run", "extracted_by_run": "agent_run",
    "journal_entry_id": "journal_entry", "outbox_id": "outbox", "work_item_id": "work_item",
    "account_id": "account",
}


def _norm(value: Any, maps: _Maps, key: Optional[str] = None, parent: Optional[Mapping] = None) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _DROP and key in (None, "question"):
                continue
            if k in _CLOCKS:
                out[k] = v is not None
                continue
            out[k] = _norm(v, maps, k, value)
        return out
    if isinstance(value, list):
        if key == "work_item_ids":
            return [maps.work_item.get(_int(v), v) for v in value]
        if key == "depends_on":
            return sorted(maps.job.get(_int(v), v) for v in value)
        return [_norm(v, maps, key, parent) for v in value]
    if key in _ID_KEYS and value is not None:
        return getattr(maps, _ID_KEYS[key]).get(_int(value), value)
    if key == "subject_id" and parent is not None and "subject_type" in parent:
        return maps.subject(parent["subject_type"], value)
    if key in ("confirmed", "idempotency_key") and isinstance(value, str):
        return maps.fingerprint(value)
    if key == "csv" and isinstance(value, str):
        return _norm_csv(value, maps)
    if isinstance(value, str):
        return _norm_text(value, maps)
    return value


_IDS_IN_TEXT = (
    (re.compile(r"\blease_version (\d+)"), "lease_version", "lease_version %s"),
    (re.compile(r"\bwork item (\d+)"), "work_item", "work item %s"),
)


def _norm_text(value: str, maps: _Maps) -> str:
    """Reasons that name a row by id ("lease_version 3 is not confirmed
    (work item 7 is PROPOSED)") name it by its natural key instead."""
    for pattern, table, form in _IDS_IN_TEXT:
        value = pattern.sub(lambda m, t=table, f=form: f % getattr(maps, t).get(int(m.group(1)),
                                                                             m.group(1)), value)
    return value


def _norm_csv(body: str, maps: _Maps) -> str:
    import csv
    import io

    rows = list(csv.reader(io.StringIO(body)))
    if not rows or "work_item_id" not in rows[0]:
        return body
    col = rows[0].index("work_item_id")
    for row in rows[1:]:
        row[col] = maps.work_item.get(_int(row[col]), row[col])
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def _rows(conn, table: str) -> List[dict]:
    return [json.loads(r[0], parse_float=Decimal)
            for r in conn.execute(text("SELECT row_to_json(t)::text FROM %s t" % table))]


def canonical_state(engines: Mapping[str, Engine]) -> Dict[str, Any]:
    """Everything January writes, comparable across databases."""
    with engines["owner"].connect() as conn:
        maps = _Maps(conn)
        state: Dict[str, Any] = {}
        for table in STATE_TABLES:
            rows = []
            for row in _rows(conn, table):
                if table == "job":
                    for k in _VOLATILE_JOB:
                        row.pop(k, None)
                rows.append(json.dumps(_norm(row, maps), sort_keys=True, default=str))
            state[table] = sorted(rows)
        events: Dict[str, List[str]] = {}
        order: List[str] = []
        for row in conn.execute(text("SELECT row_to_json(e)::text FROM audit_event e ORDER BY seq")):
            event = json.loads(row[0], parse_float=Decimal)
            subject = "%s:%s" % (event["subject_type"],
                                 maps.subject(event["subject_type"], event["subject_id"]))
            body = _norm({k: v for k, v in event.items() if k not in ("subject_id",)}, maps)
            events.setdefault(subject, []).append(json.dumps(body, sort_keys=True, default=str))
            order.append("%s %s" % (subject, event["action"]))
        state["audit_event"] = events
        state["audit_order"] = order
    return state


def differences(a: Mapping[str, Any], b: Mapping[str, Any], limit: int = 20) -> List[str]:
    """Human-readable differences between two canonical states."""
    out: List[str] = []
    for table in sorted(set(a) | set(b)):
        x, y = a.get(table), b.get(table)
        if x == y:
            continue
        if isinstance(x, dict) and isinstance(y, dict):
            for subject in sorted(set(x) | set(y)):
                if x.get(subject) != y.get(subject):
                    out.append("%s %s: A=%s B=%s" % (table, subject, x.get(subject), y.get(subject)))
        elif isinstance(x, list) and isinstance(y, list):
            only_a = sorted(set(x) - set(y))
            only_b = sorted(set(y) - set(x))
            out.append("%s: %d vs %d rows; only in A: %s; only in B: %s" % (
                table, len(x), len(y), only_a[:3], only_b[:3]))
        else:
            out.append("%s: A=%r B=%r" % (table, x, y))
        if len(out) >= limit:
            break
    return out


def counts(state: Mapping[str, Any]) -> Dict[str, int]:
    out = {t: len(state[t]) for t in STATE_TABLES}
    out["audit_event"] = len(state["audit_order"])
    return out


# ----------------------------------------------------------------- checks

def integrity(engines: Mapping[str, Engine]) -> Dict[str, Any]:
    """verify_chain(), replay == live (rolled back), the trial balance."""
    from app.ledger.trial_balance import trial_balance
    from app.work.events import verify_chain
    from app.work.replay import replay

    with engines["lease_reader"].connect() as conn:
        broken = verify_chain(conn)
        tb = trial_balance(conn, ENTITY, JAN)
    with engines["owner"].connect() as conn:
        with conn.begin() as tx:
            report = replay(conn)
            tx.rollback()
    return {"chain": broken is None, "chain_break": broken,
            "replay_identical": report.identical, "replay_differences": report.differences[:5],
            "tb_debits": tb.total_debits, "tb_credits": tb.total_credits,
            "tb_balanced": tb.total_debits == tb.total_credits}


@contextmanager
def scratch_month(tag: str, data_dir: Path):
    """A seeded scratch database."""
    with ScratchDB(tag) as db:
        seed_db(db.engines, data_dir)
        yield db
