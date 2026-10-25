"""Regressions for checker identity and version-driven evidence refresh."""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import lease_world as lw
import pytest
from sqlalchemy import text

from app.jobs.lease_versions import ConfirmedRules, confirmed_rules
from app.jobs.monthly import check_period, run_month
from app.jobs.worker import drain
from app.records.seed import seed
from app.work import resolver
from app.work.roles import ensure_gateway_actor, load_actor
from app.work.transitions import create_item, transition

ROOT = Path(__file__).resolve().parents[3]
ENTITY = "ENT-CA"
LEASE = "LEASE-01"
MONTH = date(2026, 1, 1)


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("version-recheck-generated")
    subprocess.run(
        [sys.executable, "-m", "datagen.build", "--out", str(out)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return out


@pytest.fixture
def confirmed(clean, generated, monkeypatch):
    seed(Path(generated), clean["lease_agent"], clean["lease_gateway"])
    lw.use_documents(monkeypatch, generated)
    lw.draft_and_confirm(clean, generated)
    return clean


def _draft_modification(engines, version, effective, changed_terms):
    with engines["owner"].begin() as conn:
        foundation = conn.execute(text("""
            SELECT id FROM lease_version WHERE lease_id = :lease AND version = 1
        """), {"lease": LEASE}).scalar_one()
        version_id = conn.execute(text("""
            INSERT INTO lease_version (lease_id, version, effective_from)
            VALUES (:lease, :version, :effective) RETURNING id
        """), {
            "lease": LEASE,
            "version": version,
            "effective": effective,
        }).scalar_one()
        conn.execute(text("""
            INSERT INTO lease_term (
                lease_version_id, field, value, document_id, page, bbox,
                quote, confidence, extracted_by_run
            )
            SELECT :version, field, value, document_id, page, bbox,
                   quote, confidence, extracted_by_run
              FROM lease_term
             WHERE lease_version_id = :foundation
        """), {"version": version_id, "foundation": foundation})
        for field, value in changed_terms.items():
            conn.execute(text("""
                UPDATE lease_term SET value = CAST(:value AS jsonb)
                 WHERE lease_version_id = :version AND field = :field
            """), {
                "version": version_id,
                "field": field,
                "value": json.dumps(value),
            })

    modification_evidence = {
        "lease_id": LEASE,
        "lease_version_id": version_id,
        "changed_terms": dict(changed_terms),
    }
    with engines["lease_agent"].begin() as conn:
        actor = load_actor(conn, "agent:investigation")
        item = create_item(
            conn,
            actor,
            kind="LEASE_MODIFICATION",
            subject_type="lease_version",
            subject_id=version_id,
            title=f"{LEASE} v{version} test amendment",
            entity_id=ENTITY,
            region_id="REG-BAY",
            clinic_id="CLINIC-01",
            period=MONTH,
            evidence=modification_evidence,
        )
        item = transition(
            conn,
            actor,
            item["id"],
            "propose",
            reason="Regression fixture amendment.",
            patch={
                "proposal": "approve",
                "reason": "Regression fixture amendment.",
                "evidence": modification_evidence,
            },
        )
    return version_id, item["id"]


def _post_modification(engines, item_id):
    with engines["lease_api"].begin() as conn:
        transition(
            conn,
            load_actor(conn, "PER-CTRL"),
            item_id,
            "approve",
            reason="Regression fixture approved.",
        )
    with engines["lease_gateway"].begin() as conn:
        transition(
            conn,
            ensure_gateway_actor(conn),
            item_id,
            "post",
            reason="Regression fixture posted.",
        )


def _out_of_order_chain(engines, predecessor_effective, terminal_effective):
    with engines["lease_reader"].connect() as conn:
        foundation = conn.execute(text("""
            SELECT id FROM lease_version WHERE lease_id = :lease AND version = 1
        """), {"lease": LEASE}).scalar_one()
    predecessor, predecessor_item = _draft_modification(
        engines,
        2,
        predecessor_effective,
        {"base_rent_monthly": 17_400.00},
    )
    terminal, terminal_item = _draft_modification(
        engines,
        3,
        terminal_effective,
        {"expiration": "2031-12-31"},
    )
    _post_modification(engines, terminal_item)
    return foundation, predecessor, predecessor_item, terminal, terminal_item


def _rent_item(conn):
    return conn.execute(text("""
        SELECT w.id, w.state, w.proposal, w.reason, w.entity_id, w.region_id, w.evidence
          FROM work_item w
          JOIN landlord_charge c ON c.id = w.subject_id
         WHERE w.kind = 'CHARGE_CHECK'
           AND c.lease_id = :lease
           AND c.period = :period
           AND c.charge_type = 'base_rent'
           AND w.evidence->>'rule' = 'amount'
    """), {"lease": LEASE, "period": MONTH}).mappings().one()


def _source(source_id, kind, rank, value, *, suspect=False):
    return resolver.Source(
        source_id=source_id,
        kind=kind,
        rank=rank,
        label=source_id,
        value=value,
        claim=f"rent is ${value:,.2f}",
        citation={"doc_id": source_id, "kind": "email"},
        suspect=suspect,
        note="sender verification failed" if suspect else "",
    )


def _record_mixed_investigation(engines, modification):
    sources = [
        _source("investigation-amendment", "amendment", 1, 17_400.00),
        _source("investigation-agreeing", "authorized_rep", 3, 17_400.00),
        _source("investigation-conflict", "property_manager", 4, 10_400.00),
        _source("investigation-suspect", "property_manager", 4, 1_400.00, suspect=True),
    ]
    with engines["lease_agent"].begin() as conn:
        item = _rent_item(conn)
        evidence = dict(item["evidence"])
        evidence["investigation"] = {
            "root_cause": "amendment",
            "evidence": [{"doc_id": source.source_id} for source in sources],
        }
        evidence["modification"] = dict(modification)
        evidence.update(resolver.resolve(
            conn,
            evidence,
            kind="CHARGE_CHECK",
            region_id=item["region_id"],
            entity_id=item["entity_id"],
            extra_sources=sources,
            today=MONTH,
        ))
        transition(
            conn,
            load_actor(conn, "agent:investigation"),
            item["id"],
            "propose",
            reason=evidence["decision"]["explanation"],
            patch={
                "proposal": item["proposal"],
                "reason": evidence["decision"]["explanation"],
                "evidence": evidence,
            },
        )
    return sources


def test_confirmed_rules_fingerprint_names_complete_ordered_chains():
    rules = ConfirmedRules(
        {},
        {"LEASE-02": 23, "LEASE-01": 13},
        {},
        {"LEASE-02": (21, 23), "LEASE-01": (11, 13)},
    )

    assert rules.versions == {"LEASE-02": 23, "LEASE-01": 13}
    assert rules.version_chains == {"LEASE-02": (21, 23), "LEASE-01": (11, 13)}
    assert rules.fingerprint == '{"LEASE-01":[11,13],"LEASE-02":[21,23]}'
    assert rules.fingerprint != ConfirmedRules(
        {},
        rules.versions,
        {},
        {"LEASE-02": (21, 23), "LEASE-01": (13, 11)},
    ).fingerprint
    assert ConfirmedRules({}, {"LEASE-01": 13}, {}).fingerprint == '{"LEASE-01":[13]}'


@pytest.mark.parametrize(
    ("predecessor_effective", "terminal_effective"),
    [
        pytest.param(date(2025, 7, 1), date(2025, 7, 1), id="same-effective-date"),
        pytest.param(date(2025, 4, 1), date(2025, 7, 1), id="backdated-predecessor"),
    ],
)
def test_monthly_rechecks_when_a_nonterminal_version_becomes_standing(
        confirmed, predecessor_effective, terminal_effective,
):
    engines = confirmed
    foundation, predecessor, predecessor_item, terminal, _ = _out_of_order_chain(
        engines, predecessor_effective, terminal_effective
    )

    with engines["lease_reader"].connect() as conn:
        before_rules = confirmed_rules(conn, ENTITY, as_of=MONTH)
    assert before_rules.versions[LEASE] == terminal
    assert before_rules.version_chains[LEASE] == (foundation, terminal)

    with engines["lease_agent"].begin() as conn:
        run_month(conn, ENTITY, MONTH)
    initial_outcomes = drain(engines["lease_agent"], "version-chain-initial")
    assert [outcome.job.kind for outcome in initial_outcomes] == [
        "ingest", "abstraction", "checking",
    ]
    assert initial_outcomes[-1].result["confirmed"] == before_rules.fingerprint

    with engines["lease_reader"].connect() as conn:
        initial = _rent_item(conn)
        event_count = conn.execute(text("""
            SELECT count(*) FROM audit_event
             WHERE subject_type = 'work_item' AND subject_id = :item
        """), {"item": str(initial["id"])}).scalar_one()
    assert initial["evidence"]["lease_version_id"] == terminal
    assert initial["evidence"]["lease_version_ids"] == [foundation, terminal]

    _post_modification(engines, predecessor_item)
    with engines["lease_reader"].connect() as conn:
        after_rules = confirmed_rules(conn, ENTITY, as_of=MONTH)
    assert after_rules.versions[LEASE] == terminal
    assert after_rules.version_chains[LEASE] == (foundation, predecessor, terminal)
    assert after_rules.fingerprint != before_rules.fingerprint

    with engines["lease_agent"].begin() as conn:
        jobs = run_month(conn, ENTITY, MONTH)
    assert "recheck" in jobs
    [recheck] = drain(engines["lease_agent"], "version-chain-recheck")
    assert recheck.job.kind == "checking" and recheck.result["revised"] >= 1

    with engines["lease_reader"].connect() as conn:
        revised = _rent_item(conn)
        revised_event_count = conn.execute(text("""
            SELECT count(*) FROM audit_event
             WHERE subject_type = 'work_item' AND subject_id = :item
        """), {"item": str(revised["id"])}).scalar_one()
    assert revised["id"] == initial["id"]
    assert revised["evidence"]["lease_version_id"] == terminal
    assert revised["evidence"]["lease_version_ids"] == [foundation, predecessor, terminal]
    assert revised["evidence"]["supported"] == 17_400.00
    assert revised["evidence"]["supported"] != initial["evidence"]["supported"]
    assert revised_event_count == event_count + 1

    with engines["lease_agent"].begin() as conn:
        unchanged = run_month(conn, ENTITY, MONTH)
    assert "recheck" not in unchanged
    assert drain(engines["lease_agent"], "version-chain-unchanged") == []
    with engines["lease_reader"].connect() as conn:
        assert conn.execute(text("""
            SELECT count(*) FROM audit_event
             WHERE subject_type = 'work_item' AND subject_id = :item
        """), {"item": str(revised["id"])}).scalar_one() == revised_event_count


def test_version_recheck_preserves_every_investigation_source_once(confirmed):
    engines = confirmed
    foundation, predecessor, predecessor_item, terminal, terminal_item = _out_of_order_chain(
        engines, date(2025, 7, 1), date(2025, 7, 1)
    )
    with engines["lease_agent"].begin() as conn:
        check_period(conn, ENTITY, MONTH)

    investigation_sources = _record_mixed_investigation(
        engines,
        {"lease_version_id": terminal, "work_item_id": terminal_item},
    )
    _post_modification(engines, predecessor_item)
    with engines["lease_agent"].begin() as conn:
        result = check_period(conn, ENTITY, MONTH)
    assert result["revised"] >= 1

    with engines["lease_reader"].connect() as conn:
        refreshed = _rent_item(conn)
    evidence = refreshed["evidence"]
    source_ids = [source["source_id"] for source in evidence["sources"]]
    for source in investigation_sources:
        assert source_ids.count(source.source_id) == 1
    assert sum(source["kind"] == "lease" for source in evidence["sources"]) == 1
    assert sum(source["kind"] == "invoice" for source in evidence["sources"]) == 1

    decision = evidence["decision"]
    assert "investigation-agreeing" in decision["agreeing"]
    assert "investigation-conflict" in decision["contradicting"]
    assert "investigation-suspect" in decision["set_aside"]
    assert evidence["investigation"]["root_cause"] == "amendment"
    assert evidence["modification"] == {
        "lease_version_id": terminal,
        "work_item_id": terminal_item,
    }
    assert evidence["lease_version_id"] == terminal
    assert evidence["lease_version_ids"] == [foundation, predecessor, terminal]
