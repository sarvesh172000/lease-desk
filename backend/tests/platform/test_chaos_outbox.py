"""Chaos on the outbox: the delivery target (mail server, AP's drop folder)
is down, then comes back; the database drops the sender between delivering
and recording it. The outbox retries until the target returns, then sends
exactly once (work/gateway.send_outbox).

Mailpit is not in Compose yet, so "the mail server is down" is the deliverer
raising ConnectionRefusedError (ops/chaos/faults.outbox_target_down) or the
outbox directory replaced by a file (faults.blocked_directory), which fails
every write even as root.
"""

import threading

import lease_world as lw
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.jobs.worker import drain
from app.work import gateway
from app.work.events import verify_chain
from app.work.gateway import MAX_SEND_ATTEMPTS, send_outbox
from ops.chaos import harness as h
from ops.chaos.faults import blocked_directory, outbox_target_down, terminate


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    return h.generate(tmp_path_factory.mktemp("generated"))


@pytest.fixture
def released(clean, generated, monkeypatch, tmp_path):
    """January up to a released AP batch that nobody has sent yet."""
    h.seed_db(clean, generated)
    lw.use_documents(monkeypatch, generated)
    h.january(clean, lambda step: drain(clean["lease_agent"], "w"), tmp_path / "unused", send=False)
    assert outbox(clean) == [("pending", 0)]
    return clean


def outbox(eng):
    with eng["lease_reader"].connect() as conn:
        return [tuple(r) for r in conn.execute(text(
            "SELECT status, attempts FROM outbox ORDER BY id"))]


def send(eng, out_dir):
    with eng["lease_gateway"].connect() as conn:
        return send_outbox(conn, out_dir)


def events(eng):
    with eng["lease_reader"].connect() as conn:
        return conn.execute(text("SELECT count(*) FROM audit_event")).scalar()


def test_the_outbox_retries_while_the_target_is_down_then_sends_once(released, tmp_path):
    out = tmp_path / "ap"
    before = events(released)
    with outbox_target_down() as refused:
        for n in range(1, MAX_SEND_ATTEMPTS + 3):            # longer than the retry cap
            assert send(released, out) == []
            assert outbox(released) == [("pending", n)], "a target outage never gives up"
    assert len(refused) == MAX_SEND_ATTEMPTS + 2
    assert not list(out.glob("*.csv"))

    [sent] = send(released, out)                             # the target is back
    assert outbox(released) == [("sent", MAX_SEND_ATTEMPTS + 3)]
    assert [f.name for f in out.glob("*.csv")] == ["ap_batch_ENT-CA_2026-01.csv"]
    assert send(released, out) == [] and send(released, out) == []
    assert outbox(released) == [("sent", MAX_SEND_ATTEMPTS + 3)]
    assert events(released) == before
    with released["lease_reader"].connect() as conn:
        assert verify_chain(conn) is None


def test_an_unwritable_outbox_directory_is_retried_until_it_is_back(released, tmp_path):
    out = tmp_path / "ap"
    with blocked_directory(out):
        for n in (1, 2, 3, 4):
            assert send(released, out) == []
            assert outbox(released) == [("pending", n)]
    assert len(send(released, out)) == 1
    assert outbox(released) == [("sent", 5)]
    assert len(list(out.glob("*.csv"))) == 1


def test_losing_the_database_between_delivery_and_record_delivers_the_same_file_once(
        released, tmp_path):
    out = tmp_path / "ap"
    real = gateway.DELIVERERS["ap_batch"]
    delivered = []

    with released["lease_gateway"].connect() as conn:
        pid = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
        conn.commit()

        def deliver_then_lose_the_db(row, out_dir):
            real(row, out_dir)
            delivered.append(row["id"])
            with released["lease_gateway"].connect() as other:   # the sender's backend dies
                assert terminate(other, pid)

        gateway.DELIVERERS["ap_batch"] = deliver_then_lose_the_db
        try:
            with pytest.raises(DBAPIError):
                send_outbox(conn, out)
        finally:
            gateway.DELIVERERS["ap_batch"] = real
    assert outbox(released) == [("pending", 0)], "the send was never recorded"
    first = (out / "ap_batch_ENT-CA_2026-01.csv").read_text()

    assert len(send(released, out)) == 1                     # delivered again, recorded once
    assert outbox(released) == [("sent", 1)]
    assert [f.name for f in out.iterdir()] == ["ap_batch_ENT-CA_2026-01.csv"]
    assert (out / "ap_batch_ENT-CA_2026-01.csv").read_text() == first
    assert delivered and len(delivered) == 1


def test_two_senders_racing_after_an_outage_deliver_once(released, tmp_path):
    out = tmp_path / "ap"
    with outbox_target_down():
        send(released, out)
    real = gateway.DELIVERERS["ap_batch"]
    deliveries = []
    gateway.DELIVERERS["ap_batch"] = lambda row, d: (deliveries.append(row["id"]), real(row, d))
    try:
        results = {}
        threads = [threading.Thread(target=lambda n=n: results.__setitem__(n, send(released, out)))
                   for n in ("a", "b")]
        [t.start() for t in threads]
        [t.join() for t in threads]
    finally:
        gateway.DELIVERERS["ap_batch"] = real
    assert len(deliveries) == 1
    assert sorted(len(v) for v in results.values()) == [0, 1]
    assert outbox(released) == [("sent", 2)]
