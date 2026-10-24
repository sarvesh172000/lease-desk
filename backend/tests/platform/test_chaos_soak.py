"""Soak (PHASE_3 group 4, scaled to the data that is seeded: January only).

January runs start to finish (run, confirm, run again, approve, post,
release, send), then twenty times more. After every pass the chain verifies,
replay equals live state, the trial balance balances, and nothing has grown
since the first pass: not a job, item, entry, outbox row, file or event.
`make chaos` runs the same soak against a real worker process.
"""

import lease_world as lw
import pytest

from app.jobs.worker import drain
from ops.chaos import harness as h

RUNS = 20


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    return h.generate(tmp_path_factory.mktemp("generated"))


def test_january_twenty_more_times_changes_nothing_and_stays_consistent(clean, generated,
                                                                       monkeypatch, tmp_path):
    h.seed_db(clean, generated)
    lw.use_documents(monkeypatch, generated)
    out = tmp_path / "outbox"

    def worker(step):
        assert all(o.status == "done" for o in drain(clean["lease_agent"], "soak"))

    h.january(clean, worker, out)
    first = h.canonical_state(clean)
    base = h.integrity(clean)
    assert base["chain"] and base["replay_identical"] and base["tb_balanced"]
    assert h.counts(first)["journal_entry"] == 10 and h.counts(first)["audit_event"] == 64

    for n in range(RUNS):
        h.january(clean, worker, out)
        check = h.integrity(clean)
        assert check["chain"], (n, check["chain_break"])
        assert check["replay_identical"], (n, check["replay_differences"])
        assert (check["tb_debits"], check["tb_credits"]) == (base["tb_debits"], base["tb_credits"])
        assert h.counts(h.canonical_state(clean)) == h.counts(first), "pass %d grew" % (n + 1)
    assert h.differences(first, h.canonical_state(clean)) == []
    assert [f.name for f in out.iterdir()] == ["ap_batch_ENT-CA_2026-01.csv"]
