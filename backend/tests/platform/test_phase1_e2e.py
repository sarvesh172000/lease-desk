"""Phase 1's Definition of Done, end to end, on the session's throwaway database.

    datagen.build -> seed -> run_month + worker (drafts the five lease versions,
    checks nothing against unconfirmed terms) -> a regional manager confirms
    the leases -> run_month again checks the twelve charges -> the manager
    approves -> the gateway posts -> the AP clerk releases -> the outbox
    writes the CSV -> trial balance, Beancount, verify_chain() and replay agree

Every step runs as the database role its process really uses: the worker as
lease_agent, people through lease_api, the gateway as lease_gateway, the
auditor's checks as lease_reader, replay as the owner. Then January runs a
second time and nothing new appears anywhere.
"""

import csv
import io
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import lease_world as lw
import pytest
from beancount import loader
from beancount.core import data as bc
from sqlalchemy import text

from app.jobs.monthly import check_period, run_month
from app.jobs.worker import drain
from app.ledger.export_beancount import render
from app.ledger.trial_balance import trial_balance
from app.records.seed import seed
from app.work.events import events_for, verify_chain
from app.work.gateway import post_approved, release_batch, send_outbox
from app.work.replay import replay
from app.work.roles import load_actor
from app.work.transitions import Denied, transition

ROOT = Path(__file__).resolve().parents[3]
JAN = date(2026, 1, 1)
ENTITY = "ENT-CA"
RM_BAY = "PER-RM-BAY"
RM_DESERT = "PER-RM-DESERT"
AP = "PER-AP"


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("generated")
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    return out


@pytest.fixture
def seeded(clean, generated, monkeypatch):
    seed(Path(generated), clean["lease_agent"], clean["lease_gateway"])
    lw.use_documents(monkeypatch, generated)
    # A manager from another region, to be refused. Phase 1 seeds one region.
    with clean["owner"].begin() as conn:
        conn.execute(text("INSERT INTO region (id, name) VALUES ('REG-DESERT', 'Desert')"))
        conn.execute(text("""
            INSERT INTO actor (id, name, role, region_id, entity_id, active)
            VALUES (:id, 'Desert manager', 'regional_manager', 'REG-DESERT', NULL, true)
        """), {"id": RM_DESERT})
    return clean


def q(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def month(engines):
    with engines["lease_agent"].begin() as conn:
        run_month(conn, ENTITY, "2026-01")
    return drain(engines["lease_agent"], "e2e")


def act(engines, role, actor_id, item_id, action, **kwargs):
    with engines[role].begin() as conn:
        return transition(conn, load_actor(conn, actor_id), item_id, action, **kwargs)


def footprint(engines):
    """Everything a second January could add to."""
    return {t: q(engines["lease_reader"], "SELECT count(*) FROM %s" % t)
            for t in ("job", "work_item", "question", "journal_entry", "journal_line",
                      "outbox", "audit_event")}


def test_january_from_seed_to_posted_books_then_again_adds_nothing(seeded, tmp_path):
    eng = seeded
    reader = eng["lease_reader"]

    # 1. The month: three jobs. Abstraction drafts lease_version 1 of each of
    #    the five leases, every term boxed on its page, and proposes one
    #    LEASE_ABSTRACTION item each. Nothing is confirmed yet, so the checker
    #    proposes nothing: the twelve charges wait, and the job says why.
    outcomes = month(eng)
    assert [(o.job.kind, o.status) for o in outcomes] == [
        ("ingest", "done"), ("abstraction", "done"), ("checking", "done")]
    assert outcomes[1].result["versions"] == 5
    assert set(outcomes[1].result["paths"].values()) == {"abstraction:generator"}
    assert (outcomes[2].result["created"], outcomes[2].result["waiting"]) == (0, 12)
    assert q(reader, "SELECT count(*) FROM work_item WHERE kind = 'CHARGE_CHECK'") == 0
    with reader.connect() as conn:
        drafts = conn.execute(text("""
            SELECT w.id, w.state, w.proposed_by, v.id AS version_id, v.lease_id
              FROM work_item w JOIN lease_version v ON v.id::text = w.subject_id
             WHERE w.kind = 'LEASE_ABSTRACTION' ORDER BY v.lease_id
        """)).mappings().all()
        boxed = conn.execute(text(
            "SELECT count(*) FROM lease_term WHERE bbox IS NOT NULL AND page IS NOT NULL")).scalar()
    assert len(drafts) == 5 and {d["state"] for d in drafts} == {"PROPOSED"}
    assert {d["proposed_by"] for d in drafts} == {"agent:abstraction"}
    assert boxed == 5 * 13

    # 1b. A Desert manager may not confirm a Bay Area lease; the Bay Area
    #     manager confirms all five, each one a hash-chained approve.
    with pytest.raises(Denied, match="region"):
        act(eng, "lease_api", RM_DESERT, drafts[0]["id"], "approve")
    for d in drafts:
        assert act(eng, "lease_api", RM_BAY, d["id"], "approve")["state"] == "APPROVED"
    assert q(reader, "SELECT count(*) FROM lease_version WHERE confirmed_by = :rm",
             rm=RM_BAY) == 5

    # 1c. The month again: one more checking job, now against the confirmed
    #     terms. Every charge checked, every finding proposed.
    outcomes = month(eng)
    assert [(o.job.kind, o.status) for o in outcomes] == [("checking", "done")]
    assert (outcomes[0].result["created"], outcomes[0].result["holds"]) == (12, 5)
    with reader.connect() as conn:
        items = conn.execute(text("""
            SELECT w.id, w.state, w.proposal, w.subject_id, c.amount
              FROM work_item w JOIN landlord_charge c ON c.id = w.subject_id
             WHERE w.kind = 'CHARGE_CHECK' ORDER BY w.id
        """)).mappings().all()
    assert len(items) == 12 and {i["state"] for i in items} == {"PROPOSED"}
    good = [i for i in items if i["proposal"] == "approve"]
    held = [i for i in items if i["proposal"] == "hold"]
    assert (len(good), len(held)) == (7, 5)

    # 2. A Desert manager may not approve a Bay Area item: Denied, and on record.
    with pytest.raises(Denied, match="region"):
        act(eng, "lease_api", RM_DESERT, good[0]["id"], "approve")
    with reader.connect() as conn:
        refused = [e for e in events_for(conn, "work_item", good[0]["id"]) if not e.allowed]
        assert all(e["evidence"]["lease_version_id"] in {d["version_id"] for d in drafts}
                   for e in conn.execute(text(
                       "SELECT evidence FROM work_item WHERE kind = 'CHARGE_CHECK'")).mappings())
    assert [(e.actor_id, e.action) for e in refused] == [(RM_DESERT, "approve")]
    assert "REG-DESERT" in refused[0].reason

    # 3. Separation of duties: the manager answers a question on a held item,
    #    and may then not approve that item.
    disputed = held[0]["id"]
    act(eng, "lease_agent", "agent:checker", disputed, "ask",
        patch={"asked_to": RM_BAY, "body": "Did the clinic move suites?"})
    act(eng, "lease_api", RM_BAY, disputed, "answer", patch={"answer": "No, same suite."})
    with pytest.raises(Denied, match="separation of duties"):
        act(eng, "lease_api", RM_BAY, disputed, "approve")
    with reader.connect() as conn:
        last = events_for(conn, "work_item", disputed)[-1]
    assert (last.actor_id, last.action, last.allowed) == (RM_BAY, "approve", False)

    # 4. The Bay Area manager approves the seven good items.
    for i in good:
        assert act(eng, "lease_api", RM_BAY, i["id"], "approve")["state"] == "APPROVED"

    # 5. The gateway posts them; nothing held reaches the ledger.
    with eng["lease_gateway"].begin() as conn:
        posted = post_approved(conn, ENTITY, JAN)
    assert sorted(p.work_item_id for p in posted) == sorted(i["id"] for i in good)
    approved_total = sum((i["amount"] for i in good), Decimal("0"))
    assert q(reader, "SELECT sum(debit) FROM journal_line") == approved_total
    assert q(reader, "SELECT sum(credit) FROM journal_line") == approved_total
    assert q(reader, "SELECT count(*) FROM journal_entry WHERE work_item_id = ANY(:ids)",
             ids=[i["id"] for i in held]) == 0
    assert q(reader, "SELECT count(*) FROM work_item WHERE state = 'POSTED'") == 7
    with reader.connect() as conn:
        for p in posted:
            post_event = events_for(conn, "work_item", p.work_item_id)[-1]
            assert (post_event.actor_id, post_event.action) == ("system:gateway", "post")
            assert post_event.evidence == {"journal_entry_id": p.journal_entry_id}

    # 6. The AP clerk releases the batch; the outbox writes the CSV once.
    with eng["lease_gateway"].begin() as conn:
        batch = release_batch(conn, JAN, AP, entity_id=ENTITY)
    assert batch.created and batch.item_count == 7 and batch.total == approved_total
    with eng["lease_gateway"].connect() as conn:
        assert send_outbox(conn, tmp_path) == [batch.outbox_id]
    files = list(tmp_path.glob("*.csv"))
    assert [f.name for f in files] == ["ap_batch_ENT-CA_2026-01.csv"]
    lines = list(csv.DictReader(io.StringIO(files[0].read_text())))
    assert sorted(l["charge_id"] for l in lines) == sorted(i["subject_id"] for i in good)
    assert sum(Decimal(l["amount"]) for l in lines) == approved_total

    # 7. The books: balanced, loadable by Beancount, and the chain intact.
    with reader.connect() as conn:
        tb = trial_balance(conn, ENTITY, JAN)
        assert tb.total_debits == tb.total_credits == approved_total
        assert tb.row("Accounts payable").credit == approved_total
        entries, errors, _ = loader.load_string(render(conn))
        assert verify_chain(conn) is None
    assert errors == []
    assert len([e for e in entries if isinstance(e, bc.Transaction)]) == 7

    # 8. Replay rebuilds exactly the live state.
    with eng["owner"].connect() as conn:
        with conn.begin() as tx:
            report = replay(conn)
            tx.rollback()
    assert report.identical, report.differences[:5]
    assert report.rows["work_item"] == 17 and report.rows["question"] == 1

    # 9. January again: no new jobs, items, entries, outbox rows or events.
    before = footprint(eng)
    assert month(eng) == []
    with eng["lease_agent"].begin() as conn:                 # even forcing the checker
        assert check_period(conn, ENTITY, JAN)["created"] == 0
    with eng["lease_gateway"].begin() as conn:
        assert post_approved(conn, ENTITY, JAN) == []
        assert not release_batch(conn, JAN, AP, entity_id=ENTITY).created
    with eng["lease_gateway"].connect() as conn:
        assert send_outbox(conn, tmp_path) == []
    assert footprint(eng) == before
    with reader.connect() as conn:
        assert verify_chain(conn) is None
