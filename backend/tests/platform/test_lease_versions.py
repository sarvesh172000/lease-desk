"""jobs/lease_versions.py: the abstraction step drafts lease_version 1, a
regional manager confirms it, and the checker reads only confirmed terms.

Every test runs offline. The platform conftest hides any API key and points
the LLM cache somewhere empty, so the job takes the generator path unless a
test hands in its own client (the LLM-path tests do, with the suite's fake).
"""

import subprocess
import sys
from datetime import date
from pathlib import Path

import lease_world as lw
import pytest
from fakes import FakeClient, FakeResponse
from sqlalchemy import text

from app.agents.abstraction import CITED_FIELDS, AbstractedLease
from app.docs.citations import locate
from app.engine.from_datagen import rules_from_terms
from app.jobs import lease_versions
from app.jobs.handlers import abstraction
from app.jobs.lease_versions import (
    PATH_GENERATOR,
    PATH_LLM,
    confirmed_rules,
    draft_versions,
    generator_quotes,
    generator_terms,
    load_lease_document,
)
from app.jobs.monthly import check_period, job_key, run_month
from app.jobs.worker import drain
from app.llm.cache import ResponseCache
from app.llm.client import LLM
from app.records.seed import seed
from app.work.events import events_for, verify_chain
from app.work.roles import load_actor
from app.work.transitions import Denied, transition

ROOT = Path(__file__).resolve().parents[3]
JAN = date(2026, 1, 1)
ENTITY = "ENT-CA"
LEASES = ["LEASE-01", "LEASE-02", "LEASE-03", "LEASE-04", "LEASE-05"]


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


def abstraction_items(eng):
    return rows(eng, """
        SELECT w.*, v.lease_id FROM work_item w JOIN lease_version v ON v.id::text = w.subject_id
         WHERE w.kind = 'LEASE_ABSTRACTION' ORDER BY v.lease_id""")


# --------------------------------------------------------------- drafting

def test_the_abstraction_job_drafts_version_1_of_every_lease_with_every_term_boxed(seeded):
    agent = seeded["lease_agent"]
    with agent.begin() as conn:
        result = abstraction(conn, {"entity_id": ENTITY, "period": "2026-01-01"})
    assert result["status"] == "drafted"
    assert result["drafted"] == LEASES and result["versions"] == 5
    assert set(result["paths"].values()) == {PATH_GENERATOR}
    assert result["flagged_fields"] == 0 and result["unreadable"] == []

    versions = rows(agent, "SELECT * FROM lease_version ORDER BY lease_id")
    assert [(v["lease_id"], v["version"]) for v in versions] == [(lid, 1) for lid in LEASES]
    assert all(v["confirmed_by"] is None and v["confirmed_at"] is None for v in versions)
    terms_by_lease = {lid: t for lid, t in generator_terms_all().items()}
    for v in versions:
        assert v["effective_from"] == terms_by_lease[v["lease_id"]].commencement

    terms = rows(agent, "SELECT * FROM lease_term ORDER BY lease_version_id, field")
    assert len(terms) == 5 * len(CITED_FIELDS)
    for t in terms:
        assert t["page"] >= 1 and len(t["bbox"]) == 4 and t["quote"]
        assert float(t["confidence"]) == 1.0, (t["field"], t["confidence"])
        assert t["document_id"] and t["extracted_by_run"]


def generator_terms_all():
    from datagen.company import build_company
    from datagen.leases import build_leases

    return {t.lease_id: t for t in build_leases(build_company())}


def test_every_box_really_holds_the_quoted_words(seeded, generated):
    lw.draft(seeded, generated)
    with seeded["lease_agent"].connect() as conn:
        _, doc = load_lease_document(conn, "LEASE-02", Path(generated))
    terms = rows(seeded["lease_reader"], """
        SELECT t.* FROM lease_term t JOIN lease_version v ON v.id = t.lease_version_id
         WHERE v.lease_id = 'LEASE-02'""")
    by_field = {t["field"]: t for t in terms}
    rent = by_field["base_rent_monthly"]
    assert rent["value"] == 9150.0 and "$9,150.00" in rent["quote"]
    x0, y0, x1, y1 = rent["bbox"]
    words = [w.text for w in doc.page(rent["page"]).words
             if x0 <= (w.x0 + w.x1) / 2 <= x1 and y0 <= (w.y0 + w.y1) / 2 <= y1]
    assert "$9,150.00" in words
    assert by_field["escalation_kind"]["value"] == "fixed_step"
    assert by_field["commencement"]["value"] == "2023-07-01"


def test_the_run_is_recorded_as_the_generator_and_claims_no_model(seeded, generated):
    lw.draft(seeded, generated)
    runs = rows(seeded["lease_reader"], "SELECT * FROM agent_run ORDER BY id")
    assert len(runs) == 5
    for r in runs:
        assert (r["agent"], r["prompt_id"], r["model"]) == (
            PATH_GENERATOR, "generator:datagen.leases", None)
        assert (r["input_tokens"], r["output_tokens"], float(r["cost_usd"])) == (0, 0, 0.0)
        assert r["status"] == "succeeded" and r["finished_at"] is not None


def test_one_item_per_version_proposed_by_the_abstraction_agent_in_the_clinics_region(seeded,
                                                                                      generated):
    lw.draft(seeded, generated)
    items = abstraction_items(seeded["lease_reader"])
    assert [i["lease_id"] for i in items] == LEASES
    clinics = {r["id"]: r for r in rows(seeded["lease_reader"], "SELECT * FROM clinic")}
    with seeded["lease_reader"].connect() as conn:
        for i in items:
            assert (i["state"], i["proposal"], i["proposed_by"]) == (
                "PROPOSED", "approve", "agent:abstraction")
            assert i["subject_type"] == "lease_version"
            assert i["region_id"] == clinics[i["clinic_id"]]["region_id"]
            assert i["entity_id"] == ENTITY
            ev = i["evidence"]
            assert ev["path"] == PATH_GENERATOR and ev["lease_id"] == i["lease_id"]
            assert len(ev["fields"]) == 13 and ev["low_confidence"] == []
            assert {f["field"] for f in ev["fields"]} == set(CITED_FIELDS)
            assert all(f["bbox"] and f["page"] for f in ev["fields"])
            events = events_for(conn, "work_item", i["id"])
            assert [(e.actor_id, e.action) for e in events] == [
                ("agent:abstraction", "create"), ("agent:abstraction", "propose")]
        assert verify_chain(conn) is None


def test_the_history_cross_check_shows_both_figures_and_picks_neither(seeded, generated):
    lw.draft(seeded, generated)
    flagged = [i for i in abstraction_items(seeded["lease_reader"])
               if i["evidence"]["history_disagreements"]]
    for i in flagged:
        for d in i["evidence"]["history_disagreements"]:
            assert d["period"] < "2026-01" and d["schedule_says"] != d["cash_says"]
            assert any(d["period"] in f for f in i["evidence"]["flags"])


def test_drafting_twice_adds_nothing(seeded, generated):
    lw.draft(seeded, generated)
    before = {t: q(seeded["lease_reader"], "SELECT count(*) FROM %s" % t)
              for t in ("lease_version", "lease_term", "agent_run", "work_item", "audit_event")}
    again = lw.draft(seeded, generated)
    assert again["drafted"] == []
    assert {t: q(seeded["lease_reader"], "SELECT count(*) FROM %s" % t) for t in before} == before


def test_a_quote_not_on_any_page_gets_no_box_low_confidence_and_a_flag(seeded, generated,
                                                                       monkeypatch):
    real = generator_quotes

    def broken(terms, company):
        out = real(terms, company)
        value, _ = out["security_deposit"]
        out["security_deposit"] = (value, "a sentence that no page of this lease contains at all")
        return out

    monkeypatch.setattr(lease_versions, "generator_quotes", broken)
    result = lw.draft(seeded, generated)
    assert result["flagged_fields"] == 5
    deposit = rows(seeded["lease_reader"],
                   "SELECT * FROM lease_term WHERE field = 'security_deposit'")
    assert len(deposit) == 5
    for t in deposit:
        assert t["page"] is None and t["bbox"] is None and t["document_id"] is None
        assert float(t["confidence"]) == 0.0
    for i in abstraction_items(seeded["lease_reader"]):
        assert i["evidence"]["low_confidence"] == ["security_deposit"]
        assert any("security_deposit" in f for f in i["evidence"]["flags"])
        assert "low confidence: security_deposit" in i["reason"]


def test_without_the_lease_document_nothing_is_boxed(seeded, tmp_path):
    with seeded["lease_agent"].begin() as conn:
        result = draft_versions(conn, ENTITY, root=tmp_path, history_until=JAN)
    assert result["flagged_fields"] == 5 * 13
    terms = rows(seeded["lease_reader"], "SELECT * FROM lease_term")
    assert terms and all(t["bbox"] is None and t["page"] is None for t in terms)
    assert all(float(t["confidence"]) == 0.0 for t in terms)
    ev = abstraction_items(seeded["lease_reader"])[0]["evidence"]
    assert any("not in the store" in f for f in ev["flags"])


def test_no_abstraction_agent_actor_writes_nothing(seeded, generated):
    with seeded["owner"].begin() as conn:
        conn.execute(text("UPDATE actor SET active = false WHERE id = 'agent:abstraction'"))
    with pytest.raises(Exception, match="agent:abstraction"):
        lw.draft(seeded, generated)
    assert q(seeded["lease_reader"], "SELECT count(*) FROM lease_version") == 0


# --------------------------------------------------------------- LLM path

def _model_answer(document, terms, company):
    """What a model reading LEASE-01 correctly would return."""
    raw = {}
    for name, (value, quote) in generator_quotes(terms, company).items():
        found = locate(document, quote)
        raw[name] = {"value": value, "page": found.page, "quote": quote}
    return AbstractedLease.model_validate(dict(raw, uncertain=[]))


def test_a_warm_cache_takes_the_llm_path_and_says_so(seeded, generated, tmp_path):
    with seeded["lease_agent"].connect() as conn:
        _, doc = load_lease_document(conn, "LEASE-01", Path(generated))
    terms, company = generator_terms("LEASE-01")
    answer = _model_answer(doc, terms, company)
    client = FakeClient(lambda kwargs: FakeResponse(answer))
    cache = ResponseCache(tmp_path / "llm")

    # The fake model answers LEASE-01 for every lease; only the path matters here.
    with seeded["lease_agent"].begin() as conn:
        result = draft_versions(conn, ENTITY, root=Path(generated), history_until=JAN,
                                llm_factory=lambda: LLM(cache=cache, client=client))
    assert set(result["paths"].values()) == {PATH_LLM}
    assert len(client.messages.calls) == 5
    runs = rows(seeded["lease_reader"], "SELECT * FROM agent_run")
    assert {(r["agent"], r["prompt_id"], r["model"]) for r in runs} == {
        (PATH_LLM, "lease_abstraction", "claude-opus-5-5")}
    assert all(r["input_tokens"] > 0 and not r["cache_hit"] for r in runs)
    ev = abstraction_items(seeded["lease_reader"])[0]["evidence"]
    assert ev["path"] == PATH_LLM and ev["path_note"] is None


def test_a_cold_cache_with_no_key_never_calls_out_and_falls_back_on_record(seeded, generated,
                                                                         tmp_path, monkeypatch):
    (tmp_path / "llm").mkdir()
    monkeypatch.setenv("LEASEDESK_LLM_CACHE", str(tmp_path / "llm"))
    result = lw.draft(seeded, generated)
    assert set(result["paths"].values()) == {PATH_GENERATOR}
    ev = abstraction_items(seeded["lease_reader"])[0]["evidence"]
    assert "cache cold" in ev["path_note"]
    assert {r["agent"] for r in rows(seeded["lease_reader"], "SELECT agent FROM agent_run")} == {
        PATH_GENERATOR}


# ----------------------------------------------------------- confirmation

def test_a_regional_manager_approving_the_item_confirms_the_version(seeded, generated):
    lw.draft(seeded, generated)
    item = abstraction_items(seeded["lease_reader"])[0]
    with seeded["lease_api"].begin() as conn:
        row = transition(conn, load_actor(conn, lw.RM_BAY), item["id"], "approve")
    assert row["state"] == "APPROVED"
    v = rows(seeded["lease_reader"], "SELECT * FROM lease_version WHERE id = :id",
             id=int(item["subject_id"]))[0]
    assert v["confirmed_by"] == lw.RM_BAY and v["confirmed_at"] is not None
    others = q(seeded["lease_reader"],
               "SELECT count(*) FROM lease_version WHERE confirmed_by IS NOT NULL")
    assert others == 1


def test_the_abstraction_agent_cannot_confirm_its_own_draft(seeded, generated):
    lw.draft(seeded, generated)
    item = abstraction_items(seeded["lease_reader"])[0]
    with pytest.raises(Denied):
        with seeded["lease_agent"].begin() as conn:
            transition(conn, load_actor(conn, "agent:abstraction"), item["id"], "approve")
    assert q(seeded["lease_reader"],
             "SELECT count(*) FROM lease_version WHERE confirmed_by IS NOT NULL") == 0


# ------------------------------------------------------- the checker side

def test_unconfirmed_leases_are_never_checked(seeded, generated):
    lw.draft(seeded, generated)
    with seeded["lease_agent"].begin() as conn:
        counts = check_period(conn, ENTITY, JAN)
    assert (counts["charges"], counts["checked"], counts["waiting"]) == (12, 0, 12)
    assert (counts["created"], counts["findings"]) == (0, 0)
    assert sorted(counts["waiting_leases"]) == LEASES
    assert all("not confirmed" in why for why in counts["waiting_leases"].values())
    assert counts["confirmed"] == "none"
    assert q(seeded["lease_reader"],
             "SELECT count(*) FROM work_item WHERE kind = 'CHARGE_CHECK'") == 0


def test_before_any_draft_the_reason_says_so(seeded):
    with seeded["lease_agent"].begin() as conn:
        counts = check_period(conn, ENTITY, JAN)
    assert counts["waiting"] == 12
    assert all("no lease_version yet" in w for w in counts["waiting_leases"].values())


def test_rules_from_confirmed_terms_match_the_lease_as_generated(seeded, generated):
    lw.draft_and_confirm(seeded, generated)
    with seeded["lease_agent"].connect() as conn:
        confirmed = confirmed_rules(conn, ENTITY)
    assert confirmed.waiting == {} and sorted(confirmed.rules) == LEASES
    from datagen.company import build_company
    from datagen.leases import build_leases

    company = build_company()
    expected = rules_from_terms(build_leases(company), company)
    for lid, rule in confirmed.rules.items():
        want = expected[lid]
        assert rule.steps == want.steps, lid
        assert (rule.suite, rule.commencement, rule.expiration) == (
            want.suite, want.commencement, want.expiration)
        assert rule.cam_estimate_monthly == want.cam_estimate_monthly
        for key in ("base_rent", "escalation", "cam_estimate", "premises", "payment_timing"):
            assert rule.proof[key].quote == want.proof[key].quote, (lid, key)
            assert rule.proof[key].section == want.proof[key].section


def test_a_partly_confirmed_entity_checks_only_the_confirmed_leases(seeded, generated):
    lw.draft(seeded, generated)
    items = abstraction_items(seeded["lease_reader"])
    with seeded["lease_api"].begin() as conn:
        rm = load_actor(conn, lw.RM_BAY)
        for i in items[:2]:
            transition(conn, rm, i["id"], "approve")
    with seeded["lease_agent"].begin() as conn:
        counts = check_period(conn, ENTITY, JAN)
    checked = rows(seeded["lease_reader"], """
        SELECT DISTINCT c.lease_id FROM work_item w JOIN landlord_charge c ON c.id = w.subject_id
         WHERE w.kind = 'CHARGE_CHECK'""")
    assert sorted(r["lease_id"] for r in checked) == ["LEASE-01", "LEASE-02"]
    assert counts["checked"] + counts["waiting"] == 12 and counts["waiting"] > 0
    assert sorted(counts["waiting_leases"]) == LEASES[2:]
    ev = rows(seeded["lease_reader"],
              "SELECT evidence FROM work_item WHERE kind = 'CHARGE_CHECK' LIMIT 1")[0]["evidence"]
    assert ev["lease_version_id"] in {int(i["subject_id"]) for i in items[:2]}


def test_a_confirmed_version_missing_a_term_waits_with_the_reason(seeded, generated):
    lw.draft_and_confirm(seeded, generated)
    with seeded["owner"].begin() as conn:
        conn.execute(text("""
            DELETE FROM lease_term WHERE field = 'base_rent_monthly' AND lease_version_id =
                (SELECT id FROM lease_version WHERE lease_id = 'LEASE-03')"""))
    with seeded["lease_agent"].connect() as conn:
        confirmed = confirmed_rules(conn, ENTITY)
    assert "LEASE-03" not in confirmed.rules
    assert "base_rent_monthly" in confirmed.waiting["LEASE-03"]


# --------------------------------------------------- the month, twice

def _month(agent):
    with agent.begin() as conn:
        ids = run_month(conn, ENTITY, "2026-01")
    return ids, drain(agent, "test")


def test_confirming_then_running_the_month_again_checks_the_waiting_charges(seeded):
    agent = seeded["lease_agent"]
    _, first = _month(agent)
    assert [(o.job.kind, o.status) for o in first] == [
        ("ingest", "done"), ("abstraction", "done"), ("checking", "done")]
    assert first[2].result["waiting"] == 12 and first[2].result["created"] == 0

    ids, nothing = _month(agent)
    assert nothing == [] and "recheck" not in ids, "nothing confirmed, nothing to redo"

    confirmed = lw.confirm(seeded)
    assert confirmed == LEASES
    ids, second = _month(agent)
    assert [(o.job.kind, o.status) for o in second] == [("checking", "done")]
    assert second[0].job.idempotency_key.startswith(job_key(ENTITY, JAN, "checking") + "@")
    assert (second[0].result["created"], second[0].result["holds"],
            second[0].result["waiting"]) == (12, 5, 0)

    jobs = q(agent, "SELECT count(*) FROM job")
    ids, third = _month(agent)
    assert third == [] and q(agent, "SELECT count(*) FROM job") == jobs == 4


def test_a_confirmation_pulled_back_by_hold_no_longer_counts(seeded, generated):
    lw.draft_and_confirm(seeded, generated)
    item = abstraction_items(seeded["lease_reader"])[0]
    with seeded["lease_api"].begin() as conn:
        transition(conn, load_actor(conn, lw.RM_BAY), item["id"], "hold",
                   reason="The rent on page 3 does not match the schedule.")
    with seeded["lease_agent"].connect() as conn:
        confirmed = confirmed_rules(conn, ENTITY)
    assert item["lease_id"] not in confirmed.rules
    assert "HELD" in confirmed.waiting[item["lease_id"]]


def test_the_demo_confirm_step_is_idempotent_and_refuses_outside_demo_mode(seeded, generated,
                                                                          monkeypatch):
    from app.settings import get_settings
    from app.work import confirm_leases

    lw.draft(seeded, generated)
    assert lw.confirm(seeded) == LEASES
    assert lw.confirm(seeded) == []
    monkeypatch.setenv("LEASEDESK_DEMO_MODE", "0")
    monkeypatch.setenv("LEASEDESK_SESSION_SECRET", "a-test-secret-that-is-not-the-dev-default")
    get_settings.cache_clear()
    try:
        assert confirm_leases.main(["--as", lw.RM_BAY]) == 1
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
