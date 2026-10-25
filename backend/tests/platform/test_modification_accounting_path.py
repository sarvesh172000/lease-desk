"""Regression coverage for modification accounting and recheck liveness."""

from datetime import date
from pathlib import Path

import lease_world as lw
import pytest
from sqlalchemy import text
from test_api_read import generated, insert_work_item, seeded  # noqa: F401

from app.agents.investigation_run import BOOKS_CLOSED_THROUGH, to_payload
from app.agents.modification import SETTLED, Investigation
from app.agents.trust import EXECUTED_AMENDMENT, Decision, Source
from app.api.items import perform
from app.api.leases import _amend, _versions_by_lease, active_version, build_schedule, register_terms
from app.auth.sessions import SessionActor
from app.engine.remeasurement import ProposedAmendment, propose
from app.jobs.lease_versions import confirmed_rules
from app.jobs.worker import drain
from app.work import modifications
from app.work.roles import load_actor
from app.work.transitions import transition
from leasedesk.models import from_dict
from leasedesk.remeasure import remeasure

ENTITY = "ENT-CA"
LEASE = "LEASE-01"
CONTROLLER = SessionActor(
    id="PER-CTRL",
    name="Priya Raghunathan",
    role="controller",
    region_id=None,
    entity_id=None,
)


@pytest.fixture
def standing_lease(seeded, generated, monkeypatch):
    """A confirmed v1 plus the same signed register the API composes."""
    lw.use_documents(monkeypatch, generated)
    lw.draft_and_confirm(seeded, generated)
    root = Path(generated)
    payload = register_terms(root, LEASE)
    assert payload is not None
    return seeded, root, payload


def _investigation(payload, amendment, source_id, *, period=date(2026, 7, 1)):
    source = Source(
        source_id=source_id,
        rank=EXECUTED_AMENDMENT,
        sender="legal@serramonteretail.example",
        sent=date(2026, 6, 18),
        claim=amendment.summary,
        quote=amendment.summary,
        reason="Executed by both parties.",
    )
    decision = Decision(
        settled=True,
        trusted=source,
        conflicting=[],
        reason="Relied on the executed amendment, uncontradicted.",
    )
    return Investigation(
        lease_id=LEASE,
        period=period,
        variance=0.0,
        outcome=SETTLED,
        sources=[source],
        decision=decision,
        amendment=amendment,
        # This deliberately mirrors the stale agent result. Persistence must
        # replace it with a proposal over the database's standing chain.
        proposal=propose(payload, amendment, BOOKS_CLOSED_THROUGH),
        confidence=1.0,
        reasons=[decision.reason],
        searched=1,
    )


def _record(engines, payload, amendment, source_id, subject_id):
    item_id = insert_work_item(
        engines["owner"],
        state="PROPOSED",
        subject_id=subject_id,
        clinic_id="STORE-01",
        period=amendment.effective.isoformat(),
        evidence={
            "lease_id": LEASE,
            "charge_type": "base_rent",
            "billed": amendment.new_base_rent,
            "supported": 19_626.65,
        },
    )
    with engines["owner"].begin() as conn:
        conn.execute(text("""
            UPDATE work_item SET entity_id = :entity, region_id = 'REG-BAY'
             WHERE id = :id
        """), {"entity": ENTITY, "id": item_id})
    result = _investigation(payload, amendment, source_id, period=amendment.effective)
    with engines["lease_agent"].begin() as conn:
        recorded = modifications.record_investigation(
            conn, item_id, result, to_payload(result))
    assert recorded.modification_item_id is not None
    return recorded, result


def _expected(conn, root, target_version, effective):
    base = register_terms(root, LEASE)
    assert base is not None
    versions = _versions_by_lease(conn, LEASE)[LEASE]
    chain = [
        version for version in versions
        if version.confirmed or version.number == target_version
    ]
    chain.sort(key=lambda version: (version.effective_from, version.number))
    composed = dict(base, amendments=[])
    for version in chain:
        composed = _amend(composed, version)
    return remeasure(
        from_dict(composed), effective=effective, through=BOOKS_CLOSED_THROUGH)


def _lines(measurement):
    return [
        {
            "account": line.account,
            "debit": round(float(line.debit), 2),
            "credit": round(float(line.credit), 2),
        }
        for line in measurement.entries
    ]


def test_extension_proposal_preserves_rent_and_posts_in_first_open_period(standing_lease):
    engines, root, payload = standing_lease
    with engines["owner"].begin() as conn:
        conn.execute(text("""
            UPDATE period SET status = 'closed'
             WHERE entity_id = :entity AND period <= :closed
        """), {"entity": ENTITY, "closed": BOOKS_CLOSED_THROUGH})

    amendment = ProposedAmendment(
        effective=date(2026, 7, 1),
        new_expiration=date(2031, 12, 31),
        summary="The executed extension preserves the existing rent terms.",
    )
    recorded, stale = _record(
        engines, payload, amendment, "executed-extension", "extension-charge")

    with engines["lease_reader"].connect() as conn:
        item = conn.execute(text("""
            SELECT period, evidence FROM work_item WHERE id = :id
        """), {"id": recorded.modification_item_id}).mappings().one()
        expected = _expected(conn, root, 2, amendment.effective)
        versions = _versions_by_lease(conn, LEASE)[LEASE]
        schedule, _ = build_schedule(payload, versions, 2, preview=True)

    assert schedule.period_for(date(2026, 7, 1)).payment == 19_626.65
    assert schedule.period_for(date(2027, 1, 1)).payment == 20_215.45
    assert recorded.payload["entries"] == _lines(expected)
    assert recorded.payload["liability_after"] != stale.proposal.liability_after
    assert item["evidence"]["entries"] == _lines(expected)
    assert item["period"] == date(2026, 10, 1)
    assert item["evidence"]["books_closed_through"] == "2026-09-01"
    assert item["evidence"]["adjustment_period"] == "2026-10-01"

    posted = perform(
        engines["lease_api"], engines["lease_gateway"], CONTROLLER,
        recorded.modification_item_id, "approve", reason="Extension reviewed.")
    assert posted.state == "POSTED"
    with engines["lease_reader"].connect() as conn:
        journal = conn.execute(text("""
            SELECT date, period FROM journal_entry WHERE work_item_id = :id
        """), {"id": recorded.modification_item_id}).one()
        recheck = conn.execute(text("""
            SELECT payload FROM job WHERE kind = 'modification_recheck'
        """)).scalar_one()
    assert tuple(journal) == (date(2026, 10, 1), date(2026, 10, 1))
    assert recheck["period"] == "2026-07-01"


def test_later_amendment_proposal_uses_posted_predecessor_chain(standing_lease):
    engines, root, payload = standing_lease
    first = ProposedAmendment(
        effective=date(2026, 7, 1),
        new_base_rent=17_400.00,
        new_expiration=date(2031, 12, 31),
        escalation_kind="fixed_percent",
        escalation_amount=0.025,
        summary="Rent is $17,400 with 2.5% annual escalation through 2031.",
    )
    v2, _ = _record(engines, payload, first, "executed-v2", "first-amendment-charge")
    assert perform(
        engines["lease_api"], engines["lease_gateway"], CONTROLLER,
        v2.modification_item_id, "approve", reason="First amendment reviewed.",
    ).state == "POSTED"

    second = ProposedAmendment(
        effective=date(2026, 8, 1),
        new_base_rent=18_000.00,
        summary="The later amendment sets monthly rent to $18,000.",
    )
    v3, stale = _record(
        engines, payload, second, "executed-v3", "second-amendment-charge")
    with engines["lease_reader"].connect() as conn:
        expected = _expected(conn, root, 3, second.effective)

    assert v3.payload["entries"] == _lines(expected)
    assert v3.payload["liability_before"] == expected.liability_before
    assert v3.payload["liability_before"] != stale.proposal.liability_before

    assert perform(
        engines["lease_api"], engines["lease_gateway"], CONTROLLER,
        v3.modification_item_id, "approve", reason="Later amendment reviewed.",
    ).state == "POSTED"
    with engines["lease_reader"].connect() as conn:
        versions = _versions_by_lease(conn, LEASE)[LEASE]
        active = active_version(versions, date(2027, 8, 1))
        schedule, _ = build_schedule(
            payload, versions, active, as_of=date(2027, 8, 1))
        rule = confirmed_rules(conn, ENTITY, as_of=date(2027, 8, 1)).rules[LEASE]
    assert active == 3
    assert schedule.period_for(date(2026, 8, 1)).payment == 18_000.00
    assert schedule.period_for(date(2027, 8, 1)).payment == 18_450.00
    assert rule.rent_for(date(2026, 8, 1)) == 18_000.00
    assert rule.rent_for(date(2027, 8, 1)) == 18_450.00


def test_rejected_modification_recheck_finishes_instead_of_holding(standing_lease):
    engines, _, payload = standing_lease
    amendment = ProposedAmendment(
        effective=date(2026, 7, 1),
        new_base_rent=17_400.00,
        summary="Rent changes to $17,400.",
    )
    recorded, _ = _record(
        engines, payload, amendment, "rejected-v2", "rejected-amendment-charge")

    with engines["lease_api"].begin() as conn:
        actor = load_actor(conn, CONTROLLER.id)
        transition(
            conn, actor, recorded.modification_item_id, "approve",
            reason="Approve pending gateway review.")
        modifications.schedule_recheck(conn, recorded.modification_item_id)
        transition(
            conn, actor, recorded.modification_item_id, "hold",
            reason="Gateway concern requires review.")
        transition(
            conn, actor, recorded.modification_item_id, "reject",
            reason="Do not post this modification.")

    outcomes = drain(engines["lease_agent"], "rejected-modification-recheck")
    rechecks = [outcome for outcome in outcomes
                if outcome.job.kind == "modification_recheck"]
    assert len(rechecks) == 1
    assert rechecks[0].status == "done"
    assert rechecks[0].result == {
        "status": "cancelled",
        "lease_version_id": recorded.lease_version_id,
        "modification_item_id": recorded.modification_item_id,
        "item_state": "REJECTED",
    }
    with engines["lease_reader"].connect() as conn:
        job = conn.execute(text("""
            SELECT status, attempts, payload FROM job
             WHERE kind = 'modification_recheck'
        """)).mappings().one()
    assert (job["status"], job["attempts"]) == ("done", 1)
    assert job["payload"]["result"]["item_state"] == "REJECTED"


@pytest.mark.parametrize("state", ["CLOSED", "REJECTED"])
def test_non_postable_terminal_recheck_returns_without_checker(monkeypatch, state):
    monkeypatch.setattr(
        modifications,
        "load_item",
        lambda conn, item_id: {
            "kind": modifications.MODIFICATION_KIND,
            "subject_id": "22",
            "state": state,
        },
    )
    assert modifications.run_recheck(
        object(), {"modification_item_id": 11, "lease_version_id": 22}) == {
            "status": "cancelled",
            "lease_version_id": 22,
            "modification_item_id": 11,
            "item_state": state,
        }


def test_only_one_lease_modification_can_await_a_decision(standing_lease):
    engines, _, payload = standing_lease
    first = ProposedAmendment(
        effective=date(2026, 7, 1),
        new_base_rent=17_400.00,
        summary="First pending amendment.",
    )
    _record(engines, payload, first, "pending-source-one", "pending-charge-one")
    second = ProposedAmendment(
        effective=date(2026, 8, 1),
        new_base_rent=18_000.00,
        summary="Second pending amendment.",
    )
    with pytest.raises(modifications.ModificationError, match="already has open modification"):
        _record(engines, payload, second, "pending-source-two", "pending-charge-two")

    with engines["lease_reader"].connect() as conn:
        assert conn.execute(text("""
            SELECT count(*) FROM work_item WHERE kind = 'LEASE_MODIFICATION'
        """)).scalar_one() == 1
        assert conn.execute(text("""
            SELECT count(*) FROM lease_version WHERE lease_id = :lease AND version > 1
        """), {"lease": LEASE}).scalar_one() == 1


def test_gateway_reselects_the_first_open_period_at_posting(standing_lease):
    engines, _, payload = standing_lease
    with engines["owner"].begin() as conn:
        conn.execute(text("""
            UPDATE period SET status = 'closed'
             WHERE entity_id = :entity AND period <= :closed
        """), {"entity": ENTITY, "closed": BOOKS_CLOSED_THROUGH})
    amendment = ProposedAmendment(
        effective=date(2026, 7, 1),
        new_base_rent=17_400.00,
        summary="Rent changes to $17,400.",
    )
    recorded, _ = _record(
        engines, payload, amendment, "reperiod-source", "reperiod-charge")

    with engines["owner"].begin() as conn:
        conn.execute(text("""
            UPDATE period SET status = 'closed'
             WHERE entity_id = :entity AND period = '2026-10-01'
        """), {"entity": ENTITY})
    posted = perform(
        engines["lease_api"], engines["lease_gateway"], CONTROLLER,
        recorded.modification_item_id, "approve", reason="Reperioded amendment reviewed.")
    assert posted.state == "POSTED"

    with engines["lease_reader"].connect() as conn:
        journal = conn.execute(text("""
            SELECT date, period FROM journal_entry WHERE work_item_id = :item
        """), {"item": recorded.modification_item_id}).one()
        event = conn.execute(text("""
            SELECT evidence FROM audit_event
             WHERE subject_type = 'work_item' AND subject_id = :item
               AND action = 'post' AND allowed
        """), {"item": str(recorded.modification_item_id)}).scalar_one()
    assert tuple(journal) == (date(2026, 11, 1), date(2026, 11, 1))
    assert event["proposed_adjustment_period"] == "2026-10-01"
    assert event["adjustment_period"] == "2026-11-01"
    assert event["reperioded"] is True
