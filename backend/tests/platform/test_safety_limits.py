"""The demo's "Limits" beat (PHASE_3.md group 2, step 6) as one test.

The agent tries to approve, a manager tries to approve their own answer, and
a raw SQL insert as the agent role: all three fail, all three are in the
audit timeline, and the chain verifies. `make prove-limits` runs the same
function, app.work.limits.prove_limits(), against the dev database.
"""

import ledger_world as w
import pytest
from sqlalchemy import text

from app.db.bootstrap import execute_raw
from app.work import limits
from app.work.events import events_for
from app.work.replay import replay
from app.work.roles import ensure_gateway_actor


@pytest.fixture
def world(books):
    w.build(books["owner"])
    with books["owner"].begin() as conn:
        execute_raw(conn, "INSERT INTO actor (id, name, role, active) "
                          "VALUES ('agent:checker', 'Charge checker', 'agent', true)")
        ensure_gateway_actor(conn)
    return books


def test_the_three_limits_fail_and_show_in_the_audit_timeline(world):
    before = _footprint(world)
    result = limits.prove_limits(world)

    assert result.ok, limits.report(result)
    a, b, c = result.refusals
    assert (a.label, a.actor_id, a.action, a.layer) == ("(a)", "agent:checker", "approve", "can()")
    assert "role agent may not approve" in a.reason
    assert (b.label, b.actor_id, b.action) == ("(b)", "PER-RM-BAY", "approve")
    assert "separation of duties" in b.reason and "answered" in b.reason
    assert (c.label, c.actor_id, c.layer) == ("(c)", "agent:checker", "Postgres")
    assert "permission denied for table journal_entry" in c.reason

    # All three are allowed = false events in the demo item's own timeline,
    # alongside the moves that set them up, and the item ends closed.
    with world["lease_reader"].connect() as conn:
        timeline = events_for(conn, "work_item", result.item_id)
    assert [(e.action, e.allowed) for e in timeline] == [
        ("create", True), ("propose", True), ("approve", False), ("ask", True),
        ("answer", True), ("approve", False), ("post", False), ("reject", True),
        ("close", True)]
    assert {e.seq for e in timeline if not e.allowed} == {r.seq for r in result.refusals}
    assert result.chain_ok and result.final_state == "CLOSED"

    # Nothing outside the work layer changed: not the books, not AP, not
    # the records. The work layer gained exactly the demo item and its question.
    after = _footprint(world)
    changed = {t for t in before if before[t] != after[t]}
    assert changed == {"work_item", "question", "audit_event"}
    assert after["work_item"][0] == before["work_item"][0] + 1
    assert after["question"][0] == before["question"][0] + 1

    # The history still rebuilds the work layer exactly.
    with world["owner"].connect() as conn:
        tx = conn.begin()
        try:
            report = replay(conn)
        finally:
            tx.rollback()
    assert report.identical, report.differences


def test_it_can_run_again_and_adds_only_a_new_demo_item(world):
    first = limits.prove_limits(world)
    second = limits.prove_limits(world)
    assert first.ok and second.ok and second.item_id != first.item_id
    assert {r.seq for r in first.refusals}.isdisjoint(r.seq for r in second.refusals)


def test_the_report_prints_the_three_refusals_and_the_chain(world):
    printed = limits.report(limits.prove_limits(world))
    assert printed.count("refused by") == 3
    assert "verify_chain(): OK" in printed
    assert "Every forbidden action was refused and is on record." in printed


def test_the_command_runs_against_the_configured_database(world, monkeypatch, capsys):
    real = limits.prove_limits
    monkeypatch.setattr(limits, "prove_limits", lambda: real(world))
    assert limits.main([]) == 0
    assert "verify_chain(): OK" in capsys.readouterr().out


def test_without_a_manager_it_says_what_is_missing(world, monkeypatch, capsys):
    with world["owner"].begin() as conn:
        conn.execute(text("UPDATE actor SET active = false WHERE role = 'regional_manager'"))
    real = limits.prove_limits
    monkeypatch.setattr(limits, "prove_limits", lambda: real(world))
    assert limits.main([]) == 2
    assert "no active regional_manager" in capsys.readouterr().err


def _footprint(engines):
    with engines["owner"].connect() as conn:
        return limits.table_footprint(conn)
