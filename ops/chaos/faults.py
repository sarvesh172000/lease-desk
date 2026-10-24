"""Fault injectors, usable from tests and from the command line.

    python -m ops.chaos.faults kill-worker [--when-running] PID
    python -m ops.chaos.faults drop-worker-db            # terminate the worker's DB sessions
    python -m ops.chaos.faults db-proxy --listen 6543 [--down-every 20 --down-for 5]
    python -m ops.chaos.faults duplicate-sync [--data data/generated]
    python -m ops.chaos.faults outbox-down DIR           # block the outbox directory
    python -m ops.chaos.faults outbox-up DIR

Each runs against LEASEDESK_DB_* (the database a running stack uses). None of
them restarts Postgres: the cluster is shared, so a database outage is
simulated per connection instead, either by terminating the worker's own
backends (`drop-worker-db`, what a crashed server or a cut network looks like
to the worker) or by putting a proxy between the worker and Postgres that can
refuse and cut connections (`db-proxy`; point LEASEDESK_DB_PORT at it).

The model provider failing is `ProviderDown` (a client whose every call
raises a connection error, handed to `app.llm.client.LLM(client=...)`), and
the mail/outbox target being down is `outbox_target_down()` (the deliverer
raises ConnectionRefusedError, as an unreachable mail server would) or
`blocked_directory()` (the outbox directory replaced by a file, which fails
every write even for root, unlike chmod).
"""

import argparse
import os
import select
import shutil
import signal
import socket
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from ops.chaos import harness as _h  # noqa: E402,F401  (puts backend/ on sys.path)

# --------------------------------------------------------- model provider


def provider_error() -> Exception:
    """The error the Anthropic SDK raises when the API cannot be reached."""
    try:
        import anthropic
        import httpx

        return anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    except Exception:  # noqa: BLE001 - without the SDK, the plain equivalent
        return ConnectionError("could not reach the model provider")


class _DownMessages:
    def __init__(self, owner: "ProviderDown"):
        self._owner = owner

    def parse(self, **kwargs):
        self._owner.calls += 1
        if self._owner.down:
            raise provider_error()
        return self._owner.answer(kwargs)


class ProviderDown:
    """An Anthropic-shaped client that fails while `down`, and answers with
    `answer(kwargs)` once it is back up."""

    def __init__(self, answer: Optional[Callable] = None, down: bool = True):
        self.down = down
        self.calls = 0
        self.answer = answer or (lambda kwargs: (_ for _ in ()).throw(provider_error()))
        self.messages = _DownMessages(self)


# ---------------------------------------------------------- outbox target

@contextmanager
def outbox_target_down(kind: str = "ap_batch") -> Iterator[List[int]]:
    """While inside, delivering `kind` raises ConnectionRefusedError, as an
    unreachable mail server would. Yields the list of outbox ids it refused."""
    from app.work import gateway

    refused: List[int] = []
    real = gateway.DELIVERERS[kind]

    def down(row, out_dir):
        refused.append(row["id"])
        raise ConnectionRefusedError("outbox target unavailable")

    gateway.DELIVERERS[kind] = down
    try:
        yield refused
    finally:
        gateway.DELIVERERS[kind] = real


def block_directory(path: Path) -> None:
    """Replace the outbox directory with a plain file: every write and every
    mkdir under it fails with an OSError, even as root (chmod would not)."""
    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("outbox target down (ops/chaos/faults.py)\n")


def unblock_directory(path: Path) -> None:
    path = Path(path)
    if path.is_file():
        path.unlink()
    path.mkdir(parents=True, exist_ok=True)


@contextmanager
def blocked_directory(path: Path) -> Iterator[Path]:
    block_directory(path)
    try:
        yield Path(path)
    finally:
        unblock_directory(path)


# ---------------------------------------------------------------- database

def terminate(conn, pid: int) -> bool:
    """pg_terminate_backend(pid). A role may terminate its own backends, so
    a lease_agent connection can cut the worker's without any superuser."""
    return bool(conn.execute(text("SELECT pg_terminate_backend(:p)"), {"p": pid}).scalar())


def worker_backends(conn) -> List[int]:
    """Backends of lease_agent sessions other than this one, on this database."""
    return list(conn.execute(text("""
        SELECT pid FROM pg_stat_activity
         WHERE usename = 'lease_agent' AND datname = current_database()
           AND pid <> pg_backend_pid()
    """)).scalars())


def drop_worker_db(agent: Engine) -> List[int]:
    with agent.connect() as conn:
        pids = worker_backends(conn)
        return [p for p in pids if terminate(conn, p)]


class FlakyProxy:
    """A TCP proxy in front of Postgres that can go down and come back.

    `down()` closes the listening socket and cuts every open connection:
    clients mid-query see the server vanish, new connects are refused.
    `up()` listens again on the same port. The shared Postgres never notices
    anything but clients hanging up."""

    def __init__(self, target_host: str = "127.0.0.1", target_port: int = 5432,
                 listen_port: int = 0):
        self.target = (target_host, target_port)
        self.port = listen_port
        self._listener: Optional[socket.socket] = None
        self._pairs: List[tuple] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.connections = 0

    def up(self) -> "FlakyProxy":
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", self.port))
        sock.listen(64)
        self.port = sock.getsockname()[1]
        self._listener = sock
        self._stop.clear()
        threading.Thread(target=self._accept, args=(sock,), daemon=True).start()
        return self

    def down(self) -> None:
        self._stop.set()
        if self._listener is not None:
            try:
                # close() alone does not wake a thread blocked in accept() on
                # Linux, and the socket would go on accepting; shutdown() does.
                self._listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._listener.close()
            self._listener = None
        with self._lock:
            pairs, self._pairs = self._pairs, []
        for a, b in pairs:
            for s in (a, b):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                s.close()

    def _accept(self, sock: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                client, _ = sock.accept()
            except OSError:
                return
            try:
                server = socket.create_connection(self.target, timeout=5)
                server.settimeout(None)
            except OSError:
                client.close()
                continue
            with self._lock:
                self._pairs.append((client, server))
                self.connections += 1
            threading.Thread(target=self._pump, args=(client, server), daemon=True).start()

    def _pump(self, a: socket.socket, b: socket.socket) -> None:
        try:
            while True:
                ready, _, _ = select.select([a, b], [], [], 0.5)
                for s in ready:
                    data = s.recv(65536)
                    if not data:
                        return
                    (b if s is a else a).sendall(data)
        except (OSError, ValueError):
            return
        finally:
            for s in (a, b):
                try:
                    s.close()
                except OSError:
                    pass
            with self._lock:
                if (a, b) in self._pairs:
                    self._pairs.remove((a, b))


# -------------------------------------------------------------- sync files

def deliver_sync_twice(agent: Engine, data_dir: Path):
    """Ingest the same export files twice, as a re-delivered sync would."""
    from app.records.ingest import ingest_all

    reports = []
    for _ in range(2):
        with agent.begin() as conn:
            reports.append(ingest_all(conn, Path(data_dir)))
    return reports


# --------------------------------------------------------------------- CLI

def _kill_worker(pid: int, when_running: bool, timeout: float) -> int:
    from app.db.engine import engine

    if when_running:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with engine("lease_agent").connect() as conn:
                running = conn.execute(text(
                    "SELECT id, kind FROM job WHERE status = 'running' AND locked_by LIKE :p"),
                    {"p": "%%:%d" % pid}).first()
            if running:
                print("job #%d %s is running in worker %d" % (running.id, running.kind, pid))
                break
            time.sleep(0.01)
        else:
            print("no job ran in worker %d within %ss; killing anyway" % (pid, timeout))
    os.kill(pid, signal.SIGKILL)
    print("SIGKILL sent to %d; restart the worker and it resumes (make logs)" % pid)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Lease Desk fault injection")
    sub = parser.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("kill-worker", help="SIGKILL a worker process")
    k.add_argument("pid", type=int)
    k.add_argument("--when-running", action="store_true", help="wait until it holds a job")
    k.add_argument("--timeout", type=float, default=60)
    sub.add_parser("drop-worker-db", help="terminate every lease_agent session but this one")
    p = sub.add_parser("db-proxy", help="a proxy to Postgres that goes down on a schedule")
    p.add_argument("--listen", type=int, default=6543)
    p.add_argument("--down-every", type=float, default=0, help="seconds up between outages")
    p.add_argument("--down-for", type=float, default=5)
    d = sub.add_parser("duplicate-sync", help="ingest the same sync files twice")
    d.add_argument("--data", default=None)
    for name in ("outbox-down", "outbox-up"):
        o = sub.add_parser(name)
        o.add_argument("dir")
    args = parser.parse_args(argv)

    if args.cmd == "kill-worker":
        return _kill_worker(args.pid, args.when_running, args.timeout)
    if args.cmd == "drop-worker-db":
        from app.db.engine import engine
        print("terminated lease_agent backends: %s" % drop_worker_db(engine("lease_agent")))
        return 0
    if args.cmd == "db-proxy":
        from app.settings import get_settings
        s = get_settings()
        proxy = FlakyProxy(s.db_host, s.db_port, args.listen).up()
        print("proxy :%d -> %s:%d (Ctrl-C to stop)" % (proxy.port, s.db_host, s.db_port))
        try:
            while True:
                if not args.down_every:
                    time.sleep(3600)
                    continue
                time.sleep(args.down_every)
                proxy.down()
                print("down (%d connection(s) cut)" % proxy.connections)
                time.sleep(args.down_for)
                proxy.up()
                print("up")
        except KeyboardInterrupt:
            proxy.down()
        return 0
    if args.cmd == "duplicate-sync":
        from app.db.engine import engine
        from app.settings import get_settings
        data = Path(args.data or get_settings().data_dir)
        first, second = deliver_sync_twice(engine("lease_agent"), data)
        print("delivered twice: %d rows each time (re-ingest adds nothing: ids are "
              "md5(source|source_id))" % second.rows)
        return 0
    if args.cmd == "outbox-down":
        block_directory(Path(args.dir))
        print("%s is now a file: deliveries fail and stay pending" % args.dir)
        return 0
    if args.cmd == "outbox-up":
        unblock_directory(Path(args.dir))
        print("%s is a directory again: the next send delivers" % args.dir)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
