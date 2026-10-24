"""Chaos on the model provider: the circuit breaker (work/breaker.py) and
what the abstraction job does when the model cannot be read
(jobs/lease_versions.py).

  - an outage holds the job (requeued, attempt not spent, nothing written),
    and the job finishes on the LLM path once the provider is back
  - a single failed call falls back on record, in front of a person
  - a cached answer is served while the breaker is open
  - a lease nobody can read becomes a HELD item for a person, never a silent pass

The provider is ops/chaos/faults.ProviderDown, a client whose calls raise the
SDK's own connection error.
"""

import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import lease_world as lw
import pytest
from fakes import FakeResponse
from sqlalchemy import text

from app.agents.abstraction import AbstractedLease
from app.docs.citations import locate
from app.jobs import lease_versions
from app.jobs.handlers import HANDLERS
from app.jobs.lease_versions import (
    PATH_GENERATOR,
    PATH_LLM,
    UNREADABLE_KIND,
    draft_versions,
    generator_quotes,
    generator_terms,
    load_lease_document,
)
from app.jobs.monthly import check_period, parse_period
from app.jobs.worker import drain
from app.llm.cache import ResponseCache
from app.llm.client import LLM
from app.records.seed import seed
from app.work import breaker as brk
from app.work.breaker import CLOSED, HALF_OPEN, OPEN, CircuitBreaker, CircuitOpen, guard_client
from app.work.events import verify_chain
from ops.chaos.faults import ProviderDown, provider_error

ROOT = Path(__file__).resolve().parents[3]
ENTITY = "ENT-CA"
JAN = parse_period("2026-01")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def _fresh_global_breakers():
    brk._REGISTRY.clear()
    brk._published.clear()
    yield
    brk._REGISTRY.clear()
    brk._published.clear()


# --------------------------------------------------------------- breaker

def test_the_breaker_opens_after_n_outage_failures_and_then_makes_no_calls():
    clock = Clock()
    b = CircuitBreaker("t", failure_threshold=3, reset_after=60, clock=clock)
    client = ProviderDown()
    guarded = guard_client(client, b)
    for _ in range(2):
        with pytest.raises(Exception) as err:
            guarded.messages.parse(model="m")
        assert not isinstance(err.value, CircuitOpen)
    assert b.state == CLOSED
    with pytest.raises(CircuitOpen):                       # the third opens it
        guarded.messages.parse(model="m")
    assert b.state == OPEN and client.calls == 3
    for _ in range(5):
        with pytest.raises(CircuitOpen):
            guarded.messages.parse(model="m")
    assert client.calls == 3, "an open breaker sends nothing"
    snap = b.snapshot()
    assert (snap["state"], snap["rejected"], snap["opens"], snap["retry_in"]) == (OPEN, 5, 1, 60)
    assert "APIConnectionError" in snap["last_error"]


def test_half_open_lets_one_probe_through_and_its_result_decides():
    clock = Clock()
    b = CircuitBreaker("t", failure_threshold=1, reset_after=30, clock=clock)
    client = ProviderDown(answer=lambda kw: "answer")
    guarded = guard_client(client, b)
    with pytest.raises(CircuitOpen):
        guarded.messages.parse()
    clock.now += 30
    assert b.state == HALF_OPEN and b.retry_in() == 0

    with pytest.raises(CircuitOpen):                       # the probe fails: open again
        guarded.messages.parse()
    assert b.state == OPEN and b.opens == 2
    clock.now += 29
    with pytest.raises(CircuitOpen):
        guarded.messages.parse()
    assert client.calls == 2

    clock.now += 1
    b.before_call()                                        # a probe is out ...
    with pytest.raises(CircuitOpen):                       # ... so a second caller waits
        b.before_call()
    b.record_success()
    assert b.state == CLOSED
    client.down = False
    assert guarded.messages.parse() == "answer"
    assert b.snapshot()["consecutive_failures"] == 0


def test_a_bad_request_is_not_an_outage():
    b = CircuitBreaker("t", failure_threshold=1)

    def bad(**_):
        raise ValueError("400: invalid request")

    for _ in range(3):
        with pytest.raises(ValueError):
            b.call(bad)
    assert b.state == CLOSED and b.failures_total == 0


def test_state_is_visible_in_process_and_to_the_ops_page(clean):
    b = brk.breaker("llm", failure_threshold=1)
    with pytest.raises(CircuitOpen):
        b.call(lambda: (_ for _ in ()).throw(provider_error()))
    assert brk.states()["llm"]["state"] == OPEN
    assert brk.publish_if_changed(clean["lease_agent"]) == 1      # the worker's role may
    assert brk.publish_if_changed(clean["lease_agent"]) == 0      # nothing moved since
    with clean["lease_api"].connect() as conn:                    # the API may read it
        published = brk.read_published(conn)
    assert published["llm"]["state"] == OPEN and published["llm"]["published_at"]


def test_with_a_key_the_real_client_sits_behind_the_llm_breaker(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used")
    monkeypatch.setenv("LEASEDESK_LLM_CACHE", str(tmp_path / "cache"))
    llm = lease_versions.default_llm()
    assert isinstance(llm._client, brk.GuardedClient)
    assert llm._client.breaker is brk.breaker("llm")


# ---------------------------------------------------- the abstraction job

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
    return clean


def q(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def rows(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).mappings().all()


def answer_for(seeded, generated):
    with seeded["lease_agent"].connect() as conn:
        _, doc = load_lease_document(conn, "LEASE-01", Path(generated))
    terms, company = generator_terms("LEASE-01")
    raw = {}
    for name, (value, quote) in generator_quotes(terms, company).items():
        raw[name] = {"value": value, "page": locate(doc, quote).page, "quote": quote}
    parsed = AbstractedLease.model_validate(dict(raw, uncertain=[]))
    return lambda kwargs: FakeResponse(parsed)


def registry_with(llm_factory):
    def abstraction(conn, payload):
        return dict(status="drafted", **draft_versions(
            conn, payload["entity_id"], history_until=parse_period(payload["period"]),
            llm_factory=llm_factory))
    return dict(HANDLERS, abstraction=abstraction)


def enqueue_abstraction(eng):
    from app.jobs.queue import enqueue

    with eng.begin() as conn:
        return enqueue(conn, "abstraction", {"entity_id": ENTITY, "period": JAN.isoformat()})


def test_a_provider_outage_holds_the_job_and_it_finishes_on_the_llm_path_when_back(
        seeded, generated, tmp_path):
    clock = Clock()
    guard = CircuitBreaker("llm-test", failure_threshold=2, reset_after=120, clock=clock)
    provider = ProviderDown(answer=answer_for(seeded, generated))
    cache = ResponseCache(tmp_path / "cache")
    registry = registry_with(lambda: LLM(cache=cache, client=guard_client(provider, guard)))
    agent = seeded["lease_agent"]
    job_id = enqueue_abstraction(agent)

    [outcome] = drain(agent, "w", registry)
    assert outcome.status == "held"
    job = rows(agent, "SELECT * FROM job WHERE id = :i", i=job_id)[0]
    assert (job["status"], job["attempts"]) == ("queued", 0)
    assert job["last_error"].startswith("held: model provider unavailable")
    assert guard.state == OPEN and provider.calls == 2
    # Nothing was finished some other way: the generator fallback LEASE-01 got
    # before the breaker opened rolled back with the held job.
    for table in ("lease_version", "lease_term", "agent_run", "work_item", "audit_event"):
        assert q(agent, "SELECT count(*) FROM %s" % table) == 0, table
    assert q(agent, "SELECT run_after > now() + interval '100 seconds' FROM job") is True

    # Held as long as it lasts: another try while open calls nobody.
    with agent.begin() as conn:
        conn.execute(text("UPDATE job SET run_after = now()"))
    assert drain(agent, "w", registry)[0].status == "held"
    assert provider.calls == 2

    # The provider comes back; the breaker's probe goes through and closes it.
    provider.down = False
    clock.now += 120
    with agent.begin() as conn:
        conn.execute(text("UPDATE job SET run_after = now()"))
    [outcome] = drain(agent, "w", registry)
    assert outcome.status == "done"
    assert set(outcome.result["paths"].values()) == {PATH_LLM}
    assert guard.state == CLOSED and provider.calls == 2 + 5
    assert q(agent, "SELECT attempts FROM job") == 1
    assert {r["path"] for r in rows(agent, "SELECT evidence->>'path' AS path FROM work_item")} == {
        PATH_LLM}
    with seeded["lease_reader"].connect() as conn:
        assert verify_chain(conn) is None


def test_one_failed_call_falls_back_on_record_in_front_of_a_person(seeded, generated, tmp_path):
    guard = CircuitBreaker("llm-test", failure_threshold=5)
    answer = answer_for(seeded, generated)
    provider = ProviderDown(down=False)
    calls = []

    def flaky(kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise provider_error()
        return answer(kwargs)
    provider.answer = flaky
    cache = ResponseCache(tmp_path / "cache")
    with seeded["lease_agent"].begin() as conn:
        result = draft_versions(conn, ENTITY, history_until=JAN,
                                llm_factory=lambda: LLM(cache=cache,
                                                        client=guard_client(provider, guard)))
    assert result["paths"]["LEASE-01"] == PATH_GENERATOR
    assert {result["paths"][k] for k in result["paths"] if k != "LEASE-01"} == {PATH_LLM}
    item = rows(seeded["lease_reader"], """
        SELECT w.state, w.evidence FROM work_item w JOIN lease_version v ON v.id::text = w.subject_id
         WHERE v.lease_id = 'LEASE-01'""")[0]
    assert item["state"] == "PROPOSED"                      # a person still confirms it
    assert "LLM path failed" in item["evidence"]["path_note"]
    assert guard.state == CLOSED


def _warm_then_read_while_down(seeded, generated, cache_dir):
    warm = ProviderDown(answer=answer_for(seeded, generated), down=False)
    with seeded["lease_agent"].connect() as conn:            # warm the cache, keep nothing
        with conn.begin() as tx:
            draft_versions(conn, ENTITY, history_until=JAN,
                           llm_factory=lambda: LLM(cache=ResponseCache(cache_dir), client=warm))
            tx.rollback()
    guard = CircuitBreaker("llm-test", failure_threshold=1, reset_after=3600)
    with pytest.raises(CircuitOpen):
        guard.call(lambda: (_ for _ in ()).throw(provider_error()))
    down = ProviderDown()
    with seeded["lease_agent"].begin() as conn:
        result = draft_versions(conn, ENTITY, history_until=JAN, llm_factory=lambda: LLM(
            cache=ResponseCache(cache_dir), client=guard_client(down, guard)))
    return result, down, guard


def test_a_cached_answer_is_served_while_the_provider_is_down(seeded, generated, tmp_path,
                                                              monkeypatch):
    """The breaker guards the client, behind the cache: an answer already
    cached never meets it. (A fixed nonce keeps this test about the breaker;
    the test below shows a call with documents hits the cache with the real,
    random nonce too.)"""
    from app.llm import client as llm_client
    from app.llm import untrusted

    monkeypatch.setattr(llm_client, "fence_all", lambda docs: untrusted.fence_all(docs, nonce="c3"))
    result, down, guard = _warm_then_read_while_down(seeded, generated, tmp_path / "cache")
    assert set(result["paths"].values()) == {PATH_LLM}
    assert down.calls == 0 and guard.state == OPEN
    assert {r["cache_hit"] for r in rows(seeded["lease_reader"], "SELECT cache_hit FROM agent_run")} \
        == {True}


def test_the_response_cache_hits_for_a_call_with_documents_as_is(seeded, generated, tmp_path):
    result, down, guard = _warm_then_read_while_down(seeded, generated, tmp_path / "cache")
    assert down.calls == 0


def test_a_lease_nobody_can_read_goes_to_a_person_held_never_past_them(seeded, generated,
                                                                      tmp_path, monkeypatch):
    monkeypatch.setattr(lease_versions, "generator_terms", lambda lease_id: (None, None))
    guard = CircuitBreaker("llm-test", failure_threshold=100)
    provider = ProviderDown()                               # every call fails, breaker stays closed
    factory = lambda: LLM(cache=ResponseCache(tmp_path / "c"),  # noqa: E731
                          client=guard_client(provider, guard))
    agent = seeded["lease_agent"]
    with agent.begin() as conn:
        result = draft_versions(conn, ENTITY, history_until=JAN, llm_factory=factory)
    assert result["versions"] == 0 and len(result["unreadable"]) == 5
    items = rows(agent, "SELECT * FROM work_item ORDER BY subject_id")
    assert [(i["kind"], i["subject_type"], i["state"], i["proposal"]) for i in items] == [
        (UNREADABLE_KIND, "lease", "HELD", "hold")] * 5
    assert {i["proposed_by"] for i in items} == {None}
    assert all("could not be read" in i["reason"] and "LLM path failed" in i["evidence"]["path_note"]
               for i in items)
    events = q(agent, "SELECT count(*) FROM audit_event")

    with agent.begin() as conn:                             # again: nothing new
        draft_versions(conn, ENTITY, history_until=JAN, llm_factory=factory)
        waiting = check_period(conn, ENTITY, JAN)
    assert q(agent, "SELECT count(*) FROM work_item") == 5
    assert q(agent, "SELECT count(*) FROM audit_event") == events
    assert waiting["created"] == 0 and waiting["waiting"] == 12        # and nothing is checked


def test_the_hold_delay_follows_the_breaker(seeded, generated, tmp_path):
    clock = Clock()
    guard = CircuitBreaker("llm-test", failure_threshold=1, reset_after=900, clock=clock)
    registry = registry_with(lambda: LLM(cache=ResponseCache(tmp_path / "c"),
                                         client=guard_client(ProviderDown(), guard)))
    enqueue_abstraction(seeded["lease_agent"])
    [outcome] = drain(seeded["lease_agent"], "w", registry)
    assert outcome.status == "held"
    wait = q(seeded["lease_agent"], "SELECT extract(epoch FROM run_after - now()) FROM job")
    assert timedelta(seconds=float(wait)) > timedelta(seconds=880)
