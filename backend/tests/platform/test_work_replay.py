"""work/replay.py: projections rebuilt from audit_event equal the live state,
byte for byte."""

import pytest
from sqlalchemy import text

from app.db.bootstrap import execute_raw
from app.work import replay as replay_module
from app.work.replay import rebuild, replay, snapshot
from app.work.transitions import Denied, create_item, transition
from work_world import ACTORS, bay_item, engine_for, world_fixture  # noqa: F401  (the `world` fixture)

A = ACTORS


def act(engines, actor, item_id, action, **kwargs):
    with engine_for(engines, A[actor]).begin() as conn:
        return transition(conn, A[actor], item_id, action, **kwargs)


def busy_history(engines):
    """A bit of everything: several items, questions, denials, a post, a
    close, patches, money and dates."""
    ids = []
    with engines["lease_agent"].begin() as conn:
        for n in range(4):
            ids.append(create_item(conn, A["agent:checker"], **bay_item(
                subject_id="chg-%d" % n, amount="%d.10" % (1000 + n)))["id"])
    a, b, c, d = ids
    act(engines, "agent:checker", a, "propose", reason="matches", patch={"proposal": "approve"})
    act(engines, "RM-BAY", a, "approve")
    act(engines, "system:gateway", a, "post", evidence={"journal_entry_id": 1})
    act(engines, "CTRL", a, "close")
    act(engines, "agent:checker", b, "ask", patch={"asked_to": "RM-BAY", "body": "Suite?"})
    act(engines, "RM-BAY", b, "answer", patch={"answer": "Same suite"})
    act(engines, "agent:checker", b, "propose", patch={"amount": "999.99",
                                                       "evidence": {"calc": [1, 2.5]}})
    act(engines, "agent:checker", c, "hold", reason="CAM above lease")
    act(engines, "RM-BAY", c, "reject")
    with pytest.raises(Denied):
        act(engines, "RM-DESERT", d, "hold")
    act(engines, "agent:checker", d, "hold")
    act(engines, "RM-BAY", d, "resume")
    return ids


def test_replay_reproduces_the_live_state_byte_for_byte(world):
    busy_history(world)
    with world["owner"].connect() as conn:
        live = snapshot(conn)
        conn.rollback()
        with conn.begin():
            report = replay(conn)
        rebuilt = snapshot(conn)
    assert report.identical, report.differences
    assert rebuilt == live
    assert report.rows == {"work_item": 4, "question": 1}
    assert report.events == 15     # 4 creates, 11 allowed transitions; the denial is skipped


def test_replay_keeps_ids_so_journal_entries_still_point_at_their_items(world):
    ids = busy_history(world)
    with world["owner"].begin() as conn:
        execute_raw(conn, """
            INSERT INTO period (entity_id, period) VALUES ('ENT-CA', '2026-01-01');
            INSERT INTO account (entity_id, code, name, type) VALUES
                ('ENT-CA', '6100', 'Lease cost', 'expense'),
                ('ENT-CA', '2000', 'Accounts payable', 'liability');
            INSERT INTO journal_entry (entity_id, date, period, memo, idempotency_key, work_item_id)
            VALUES ('ENT-CA', '2026-01-31', '2026-01-01', 'rent', 'k1', %d);
            INSERT INTO journal_line (journal_entry_id, account_id, debit, credit)
            SELECT currval(pg_get_serial_sequence('journal_entry', 'id')), id,
                   CASE WHEN code = '6100' THEN 1000.10 ELSE 0 END,
                   CASE WHEN code = '2000' THEN 1000.10 ELSE 0 END FROM account;
        """ % ids[0])
    with world["owner"].connect() as conn:
        with conn.begin():
            assert replay(conn).identical


def test_replay_repairs_and_reports_a_tampered_projection(world):
    ids = busy_history(world)
    with world["owner"].begin() as conn:
        conn.execute(text("UPDATE work_item SET state = 'APPROVED', amount = 1 WHERE id = :i"),
                     {"i": ids[2]})
        conn.execute(text("DELETE FROM question"))
    with world["owner"].connect() as conn:
        with conn.begin():
            report = replay(conn)
        repaired = conn.execute(text("SELECT state FROM work_item WHERE id = :i"),
                                {"i": ids[2]}).scalar_one()
    assert not report.identical
    assert any(d.startswith("work_item %d:" % ids[2]) for d in report.differences)
    assert any(d.startswith("question ") for d in report.differences)
    assert repaired == "REJECTED"


def test_replay_fails_loudly_on_a_history_that_does_not_fit(world):
    """A forged event whose 'from' state never happened breaks the rebuild
    rather than silently producing some state."""
    ids = busy_history(world)
    with world["lease_api"].begin() as conn:
        from app.work.events import append_event
        append_event(conn, actor_id="CTRL", action="approve", subject_type="work_item",
                     subject_id=ids[0], diff={"from": "PROPOSED", "to": "APPROVED", "set": {}})
    with world["owner"].connect() as conn:
        with pytest.raises(Exception, match="expected one row"):
            with conn.begin():
                rebuild(conn)


def test_replay_moves_a_lagging_identity_forward_never_back(world):
    ids = busy_history(world)
    with world["owner"].begin() as conn:
        conn.execute(text("SELECT setval(pg_get_serial_sequence('work_item', 'id'), 1)"))
    with world["owner"].connect() as conn:
        with conn.begin():
            replay(conn)
    with world["lease_agent"].begin() as conn:
        fresh = create_item(conn, A["agent:checker"], **bay_item(subject_id="chg-new"))
    assert fresh["id"] == max(ids) + 1


def test_make_replay_entry_point(world, monkeypatch, capsys):
    busy_history(world)
    monkeypatch.setattr("app.db.engine.engine", lambda role: world[role])
    assert replay_module.main([]) == 0
    assert "identical" in capsys.readouterr().out

    with world["owner"].begin() as conn:
        conn.execute(text("UPDATE work_item SET title = :t"), {"t": "edited behind its back"})
    assert replay_module.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "differs" in out and "rolled back" in out
    with world["owner"].connect() as conn:   # --check changed nothing
        titles = set(conn.execute(text("SELECT title FROM work_item")).scalars())
    assert titles == {"edited behind its back"}
