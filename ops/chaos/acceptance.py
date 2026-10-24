"""`make chaos`: the C3 gate. Kill the worker mid-run; it finishes with
identical results.

    python -m ops.chaos.acceptance [--soak 20] [--keep-logs DIR]

  A  January on a scratch database, uninterrupted.
  B  January on another scratch database, the worker SIGKILLed twice with
     partial work written (inside the abstraction job, after two of five
     leases were drafted; inside the re-check, after items were created),
     restarted each time.
  =  The two databases end identical: every work item, lease version and
     term, agent run, journal entry and line, outbox payload, job result,
     and each subject's sequence of audit events (ids, clocks and hashes
     replaced by natural keys). Both chains verify, replay equals live
     state on both, both trial balances balance.
  S  Soak: on A, January again N times (run, confirm, run, approve, post,
     release, send); nothing grows after the first pass, chain, replay and
     trial balance hold every time.

Both databases are throwaway ones on the configured Postgres
(LEASEDESK_DB_*), created, migrated and dropped here. The shared cluster is
never restarted. Exit 0 only if every check holds.
"""

import argparse
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.chaos import harness as h  # noqa: E402


def run_a(db, data_dir: Path, work: Path):
    h.january(db.engines, lambda step: h.run_worker(db.name, data_dir, work / "logs-a"),
              work / "outbox-a")
    return h.canonical_state(db.engines)


def run_b(db, data_dir: Path, work: Path):
    log = h.MonthLog()

    def worker(step):
        log.kills.append(h.run_worker_killed_mid(db.name, db.engines, data_dir, work / "logs-b", step))

    h.january(db.engines, worker, work / "outbox-b", log)
    return h.canonical_state(db.engines), log


def soak(db, data_dir: Path, work: Path, runs: int):
    """January again and again on a database that already ran it."""
    base = h.counts(h.canonical_state(db.engines))
    problems = []
    for n in range(runs):
        h.january(db.engines, lambda step: h.run_worker(db.name, data_dir, work / "logs-soak"),
                        work / "outbox-a")
        now = h.counts(h.canonical_state(db.engines))
        check = h.integrity(db.engines)
        if now != base:
            problems.append("run %d grew: %s" % (n + 1, {k: (base[k], now[k]) for k in now
                                                          if now[k] != base[k]}))
        if not (check["chain"] and check["replay_identical"] and check["tb_balanced"]):
            problems.append("run %d integrity: %s" % (n + 1, check))
    return base, problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--soak", type=int, default=20, help="extra January runs on A (0: none)")
    parser.add_argument("--keep-logs", default=None, help="keep worker logs and outbox files here")
    args = parser.parse_args(argv)

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="leasedesk-chaos-") as tmp:
        work = Path(args.keep_logs) if args.keep_logs else Path(tmp)
        data_dir = h.generate(Path(tmp) / "generated")
        ok = True
        with h.scratch_month("a", data_dir) as a, h.scratch_month("b", data_dir) as b:
            t = time.monotonic()
            state_a = run_a(a, data_dir, work)
            took_a = time.monotonic() - t
            t = time.monotonic()
            state_b, log = run_b(b, data_dir, work)
            took_b = time.monotonic() - t
            diffs = h.differences(state_a, state_b)
            checks = {"A": h.integrity(a.engines), "B": h.integrity(b.engines)}

            print("C3 chaos: kill the worker mid-run, it finishes with identical results")
            print()
            print("  A  uninterrupted January                       %5.1fs" % took_a)
            print("  B  January, worker SIGKILLed twice mid-job      %5.1fs" % took_b)
            for k in log.kills:
                print("       kill during %-11s job #%s (%s, attempt %s): worker pid %d, backend %d "
                      "blocked at %s; partial work written: %s; restart exit %d" % (
                          k.step, k.job.get("id"), k.job.get("kind"), k.job.get("attempts"),
                          k.worker_pid, k.backend_pid, k.key if len(k.key) < 42 else k.key[:42] + "...",
                          "yes" if k.partial else "NO", k.restart_exit))
                ok &= k.partial and k.job.get("kind") == k.step
            print()
            counts = h.counts(state_a)
            print("  rows compared: " + ", ".join("%s %d" % kv for kv in counts.items()))
            if diffs:
                ok = False
                print("  A == B: NO, %d difference(s):" % len(diffs))
                for d in diffs:
                    print("    " + d[:400])
            else:
                print("  A == B: identical (work items, versions, terms, runs, journal, outbox, "
                      "jobs, per-subject event sequences)")
            for name, c in checks.items():
                good = c["chain"] and c["replay_identical"] and c["tb_balanced"]
                ok &= good
                print("  %s: verify_chain %s, replay == live %s, trial balance %s / %s %s" % (
                    name, "ok" if c["chain"] else "BROKEN %s" % (c["chain_break"],),
                    "yes" if c["replay_identical"] else "NO %s" % c["replay_differences"],
                    c["tb_debits"], c["tb_credits"], "balanced" if c["tb_balanced"] else "UNBALANCED"))

            if args.soak:
                t = time.monotonic()
                base, problems = soak(a, data_dir, work, args.soak)
                print("  soak: January %d more times on A in %.1fs: %s" % (
                    args.soak, time.monotonic() - t,
                    "nothing grew; chain, replay and trial balance held every run"
                    if not problems else "%d problem(s)" % len(problems)))
                for p in problems[:10]:
                    print("    " + p[:400])
                ok &= not problems
        print()
        print("  %s in %.1fs" % ("PASS" if ok else "FAIL", time.monotonic() - started))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
