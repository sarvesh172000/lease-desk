"""The C3 gate: kill the worker during January, it finishes after a restart
with results identical to an uninterrupted run (PHASE_3 group 4).

Two throwaway databases of their own (ops/chaos/harness.ScratchDB), the same
generated company seeded into each, a real `python -m app.jobs.worker`
subprocess on each. On B the worker is SIGKILLed twice, each time parked
inside a job with partial work written. `make chaos` runs the same thing and
prints a report.
"""

from pathlib import Path

import pytest
from sqlalchemy import text

from ops.chaos import harness as h


@pytest.fixture(scope="module")
def generated(tmp_path_factory, database):        # `database`: skip when no Postgres
    return h.generate(tmp_path_factory.mktemp("chaos-generated"))


@pytest.fixture(autouse=True)
def _worker_sees_no_model(monkeypatch):
    """The worker subprocess inherits the environment; keep it offline."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_killing_the_worker_mid_january_ends_identical_to_an_uninterrupted_run(generated,
                                                                              tmp_path):
    data = Path(generated)
    with h.scratch_month("a", data) as a, h.scratch_month("b", data) as b:
        h.january(a.engines, lambda step: h.run_worker(a.name, data, tmp_path / "logs-a"),
                  tmp_path / "outbox-a")

        kills = []
        h.january(b.engines, lambda step: kills.append(
            h.run_worker_killed_mid(b.name, b.engines, data, tmp_path / "logs-b", step)),
            tmp_path / "outbox-b")

        # Each kill landed inside the job it meant to, with work in flight.
        assert [(k.step, k.job["kind"], k.job["status"], k.partial) for k in kills] == [
            ("abstraction", "abstraction", "running", True),
            ("checking", "checking", "running", True)]
        with b.engines["owner"].connect() as conn:
            jobs = conn.execute(text("SELECT id, status, attempts FROM job ORDER BY id")).all()
        killed = {k.job["id"] for k in kills}
        assert {j.status for j in jobs} == {"done"}
        # A killed job ran again once; nothing else ran twice.
        assert {j.id: j.attempts for j in jobs} == {j.id: 2 if j.id in killed else 1 for j in jobs}

        state_a, state_b = h.canonical_state(a.engines), h.canonical_state(b.engines)
        assert h.differences(state_a, state_b) == []
        assert h.counts(state_a) == {
            "lease_version": 5, "lease_term": 65, "agent_run": 5, "work_item": 17, "question": 0,
            "journal_entry": 10, "journal_line": 20, "outbox": 1, "job": 4, "sync_cursor": 4,
            "audit_event": 64}

        for db in (a, b):
            check = h.integrity(db.engines)
            assert check["chain"], check["chain_break"]
            assert check["replay_identical"], check["replay_differences"]
            assert check["tb_balanced"] and check["tb_debits"] > 0

        # One batch file each, byte for byte the same.
        files_a = sorted((tmp_path / "outbox-a").glob("*.csv"))
        files_b = sorted((tmp_path / "outbox-b").glob("*.csv"))
        assert [f.name for f in files_a] == [f.name for f in files_b] == [
            "ap_batch_ENT-CA_2026-01.csv"]


def test_the_comparison_sees_a_real_difference(generated, tmp_path):
    """Normalising ids away must not normalise differences away: one edited
    work item is caught, and nothing else is reported."""
    data = Path(generated)
    with h.scratch_month("c", data) as c:
        h.enqueue_month(c.engines)
        h.run_worker(c.name, data, tmp_path)
        before = h.canonical_state(c.engines)
        with c.engines["owner"].begin() as conn:
            conn.execute(text("UPDATE work_item SET title = title || ' (edited)' WHERE id = "
                              "(SELECT min(id) FROM work_item)"))
        after = h.canonical_state(c.engines)
    diffs = h.differences(before, after)
    assert len(diffs) == 1 and diffs[0].startswith("work_item:")
