"""release_batch() and send_outbox(): an AP clerk releases one payment batch
file per entity and period, and the outbox delivers it exactly once.

The system never pays. What leaves is a CSV for AP to act on.
"""

import csv
import io
import threading
import time
from datetime import date
from decimal import Decimal

import ledger_world as w
import pytest
from sqlalchemy import text

from app.work import gateway
from app.work.events import events_for, verify_chain
from app.work.gateway import GatewayError, NotAllowed, release_batch, send_outbox

JAN = date(2026, 1, 1)
KEY = "ap_batch:ENT-CA:2026-01"


@pytest.fixture
def world(books):
    w.build(books["owner"])
    return books


def release(eng, actor="PER-AP", period=JAN, **kw):
    with eng["lease_gateway"].begin() as conn:
        return release_batch(conn, period, actor, **kw)


def outbox(eng):
    return w.rows(eng["lease_reader"], "SELECT * FROM outbox ORDER BY id")


# ----------------------------------------------------------- release_batch

def test_an_ap_clerk_releases_one_batch_of_approved_and_posted_items(world):
    rent = w.item(world["owner"], w.RENT, state="POSTED")
    cam = w.item(world["owner"], w.CAM, state="APPROVED")
    w.item(world["owner"], w.LATE_FEE, state="HELD")                      # not approved
    w.item(world["owner"], w.RENT_DEC, state="APPROVED", period="2025-12-01")  # other period

    batch = release(world)

    assert batch.created and batch.item_count == 2 and batch.total == Decimal("21726.65")
    (row,) = outbox(world)
    assert (row["kind"], row["idempotency_key"], row["status"]) == ("ap_batch", KEY, "pending")
    payload = row["payload"]
    assert payload["total"] == "21726.65" and payload["by_landlord"] == {"LL-01": "21726.65"}
    lines = list(csv.DictReader(io.StringIO(payload["csv"])))
    assert sorted(int(l["work_item_id"]) for l in lines) == sorted([rent, cam])
    assert {l["charge_id"] for l in lines} == {w.RENT, w.CAM}
    assert lines[0]["landlord_name"] == 'Harbor Point "Retail" LLC'      # CSV-quoted, intact


def test_releasing_twice_yields_one_batch(world):
    w.item(world["owner"], w.RENT)
    first = release(world)
    w.item(world["owner"], w.CAM)                    # approved after the release
    again = release(world)
    assert not again.created and again.outbox_id == first.outbox_id
    assert again.total == first.total
    assert len(outbox(world)) == 1


def test_a_release_is_audited(world):
    item = w.item(world["owner"], w.RENT)
    batch = release(world)
    with world["lease_reader"].connect() as conn:
        (event,) = events_for(conn, "ap_batch", KEY)
        assert verify_chain(conn) is None
    assert (event.actor_id, event.action, event.allowed) == ("PER-AP", "release_batch", True)
    assert event.evidence["outbox_id"] == batch.outbox_id
    assert event.evidence["work_item_ids"] == [item]


@pytest.mark.parametrize("actor,message", [
    ("PER-RM-BAY", "only an AP clerk"),
    ("PER-CTRL", "only an AP clerk"),
    ("PER-AP-GONE", "inactive"),
    ("PER-NOBODY", "unknown actor"),
    ("PER-AP-NV", "releases for entity ENT-NV, not ENT-CA"),
])
def test_anyone_but_an_ap_clerk_is_refused_and_the_refusal_is_recorded(world, actor, message):
    w.item(world["owner"], w.RENT)
    with pytest.raises(NotAllowed, match=message):
        release(world, actor=actor, entity_id="ENT-CA")
    assert outbox(world) == []
    with world["lease_reader"].connect() as conn:
        (event,) = events_for(conn, "ap_batch", KEY)
    assert (event.actor_id, event.allowed) == (actor, False)
    assert message.split()[0] in event.reason


def test_a_clerk_for_every_entity_must_name_one(world):
    w.item(world["owner"], w.RENT)
    with pytest.raises(NotAllowed, match="name the entity"):
        release(world, actor="PER-AP-ALL")
    assert release(world, actor="PER-AP-ALL", entity_id="ENT-CA").created


@pytest.mark.parametrize("period", [date(2026, 1, 15), "2026-01-01", None])
def test_a_bad_period_is_refused(world, period):
    with pytest.raises(GatewayError, match="first of a month"):
        release(world, period=period)


def test_an_empty_period_releases_nothing(world):
    w.item(world["owner"], w.RENT, state="PROPOSED")
    with pytest.raises(GatewayError, match="nothing to release"):
        release(world)
    assert outbox(world) == []


def test_the_agent_role_cannot_release(world):
    w.item(world["owner"], w.RENT)
    with pytest.raises(Exception, match="permission denied"):
        with world["lease_agent"].begin() as conn:
            release_batch(conn, JAN, "PER-AP")
    assert outbox(world) == []


# ------------------------------------------------------------- send_outbox

def test_send_writes_the_batch_file_and_marks_it_sent(world, tmp_path):
    w.item(world["owner"], w.RENT)
    batch = release(world)
    with world["lease_gateway"].connect() as conn:
        assert send_outbox(conn, tmp_path) == [batch.outbox_id]
    target = tmp_path / "ap_batch_ENT-CA_2026-01.csv"
    assert target.read_text().startswith("work_item_id,charge_id")
    (row,) = outbox(world)
    assert row["status"] == "sent" and row["sent_at"] is not None and row["attempts"] == 1
    with world["lease_gateway"].connect() as conn:
        assert send_outbox(conn, tmp_path) == []        # nothing left to send


def test_concurrent_senders_never_send_twice(world, tmp_path, monkeypatch):
    with world["owner"].begin() as conn:
        for i in range(6):
            conn.execute(text("INSERT INTO outbox (kind, payload, idempotency_key) VALUES "
                              "('ap_batch', CAST(:p AS jsonb), :k)"),
                         {"p": '{"csv": "row %d\\n"}' % i, "k": "ap_batch:T:%d" % i})
    deliveries = []
    real = gateway.DELIVERERS["ap_batch"]

    def slow(row, out_dir):
        deliveries.append(row["id"])
        time.sleep(0.05)                                 # hold the row lock a while
        real(row, out_dir)

    monkeypatch.setitem(gateway.DELIVERERS, "ap_batch", slow)
    sent = {}

    def sender(name):
        with world["lease_gateway"].connect() as conn:
            sent[name] = send_outbox(conn, tmp_path)

    threads = [threading.Thread(target=sender, args=(n,)) for n in ("a", "b")]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert sorted(deliveries) == sorted(set(deliveries)) and len(deliveries) == 6
    assert not set(sent["a"]) & set(sent["b"])
    assert len(sent["a"]) + len(sent["b"]) == 6
    assert sent["a"] and sent["b"]                       # both did real work
    assert {r["status"] for r in outbox(world)} == {"sent"}


def test_a_failing_delivery_retries_then_is_marked_failed(world, tmp_path):
    with world["owner"].begin() as conn:
        conn.execute(text("INSERT INTO outbox (kind, payload, idempotency_key) VALUES "
                          "('carrier_pigeon', '{}', 'pigeon:1'), "
                          "('ap_batch', '{}', 'ap_batch:no-csv')"))
    for expected_attempts, expected_status in ((1, "pending"), (2, "pending"), (3, "failed")):
        with world["lease_gateway"].connect() as conn:
            assert send_outbox(conn, tmp_path) == []
        assert [(r["attempts"], r["status"]) for r in outbox(world)] == \
            [(expected_attempts, expected_status)] * 2
    with world["lease_gateway"].connect() as conn:       # failed rows are left alone
        send_outbox(conn, tmp_path)
    assert [r["attempts"] for r in outbox(world)] == [3, 3]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bad", [0, -1, "3", True])
def test_max_attempts_must_be_a_positive_integer(world, tmp_path, bad):
    with world["lease_gateway"].connect() as conn:
        with pytest.raises(ValueError):
            send_outbox(conn, tmp_path, max_attempts=bad)


@pytest.mark.parametrize("key,name", [
    ("ap_batch:ENT-CA:2026-01", "ap_batch_ENT-CA_2026-01"),
    ("../../etc/passwd", "etc_passwd"),
    ("...", "outbox"),
])
def test_outbox_keys_become_safe_file_names(key, name):
    assert gateway.safe_filename(key) == name
