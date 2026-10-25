"""Persist an investigation and turn a settled amendment into reviewable work.

The agent may find and rank a document, but it cannot confirm a lease version
or post accounting. This module records the finding through the event-sourced
work layer, creates an unconfirmed full-snapshot lease version, recomputes its
accounting proposal from the standing version chain, and proposes a controller-
only ``LEASE_MODIFICATION`` item. The gateway remains the only poster.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from . import resolver
from .roles import load_actor
from .transitions import create_item, load_item, transition

INVESTIGATION_ACTOR = "agent:investigation"
MODIFICATION_KIND = "LEASE_MODIFICATION"
RECHECK_KIND = "modification_recheck"
VERSION_SUBJECT = "lease_version"
CHARGE_KIND = "CHARGE_CHECK"

_NON_POSTABLE_TERMINAL_STATES = frozenset({"CLOSED", "REJECTED"})
_CURRENCY = re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")


class ModificationError(ValueError):
    """An investigation result cannot safely become a lease modification."""


@dataclass(frozen=True)
class RecordedInvestigation:
    item: Mapping[str, Any]
    lease_version_id: Optional[int] = None
    modification_item_id: Optional[int] = None
    payload: Mapping[str, Any] = field(default_factory=dict)


def record_investigation(conn: Connection, item_id: int, result: Any,
                         payload: Mapping[str, Any], *,
                         expected_event_seq: Optional[int] = None) -> RecordedInvestigation:
    """Record one completed investigation and, when settled, propose v2.

    The existing charge item is locked first. A concurrent or repeated call
    that finds an investigation already recorded returns it without appending
    events or creating another version. The evidence patch is a complete
    replacement because that is what ``transition()`` replays.
    """
    item = load_item(conn, item_id, lock=True)
    evidence = dict(item.get("evidence") or {})
    if isinstance(evidence.get("investigation"), Mapping) and evidence["investigation"]:
        link = evidence.get("modification") if isinstance(
            evidence.get("modification"), Mapping) else {}
        return RecordedInvestigation(
            item=item,
            lease_version_id=_optional_int(link.get("lease_version_id")),
            modification_item_id=_optional_int(link.get("work_item_id")),
            payload=dict(evidence["investigation"]),
        )
    if expected_event_seq is not None and item.get("last_event_seq") != expected_event_seq:
        raise ModificationError(
            "work item %s changed while the investigation was running; retry against its "
            "current evidence" % item_id)
    if item["kind"] != CHARGE_KIND or item["subject_type"] != "landlord_charge":
        raise ModificationError("work item %s is not a landlord charge check" % item_id)
    if item["state"] != "PROPOSED":
        raise ModificationError(
            "work item %s is %s; only a PROPOSED charge can record an investigation"
            % (item_id, item["state"]))

    actor = load_actor(conn, INVESTIGATION_ACTOR)
    investigation_sources = _investigation_sources(result)
    trusted = getattr(getattr(result, "decision", None), "trusted", None)
    amendment_source = next(
        (source for source in investigation_sources
         if trusted is not None and source.source_id == trusted.source_id),
        None,
    )
    modification = _create_modification(conn, actor, item, result, payload, amendment_source)

    recorded_payload = dict(modification.payload) if modification and modification.payload \
        else dict(payload)
    searched = getattr(result, "searched", None)
    if searched is not None:
        recorded_payload.setdefault("searched", searched)
    evidence["investigation"] = recorded_payload
    if modification is not None:
        evidence["modification"] = {
            "lease_version_id": modification.lease_version_id,
            "work_item_id": modification.modification_item_id,
            "kind": MODIFICATION_KIND,
        }

    resolved = resolver.resolve(
        conn, evidence, kind=item["kind"], region_id=item.get("region_id"),
        entity_id=item.get("entity_id"), extra_sources=investigation_sources)
    evidence.update(resolved)
    if "question" not in resolved:
        evidence.pop("question", None)
    reason = resolved["decision"]["explanation"]
    event_evidence = {
        "investigation": recorded_payload.get("outcome"),
        "trusted_source": resolved["decision"].get("trusted"),
        "lease_version_id": modification.lease_version_id if modification else None,
        "modification_item_id": modification.modification_item_id if modification else None,
    }
    question = resolved.get("question")
    if resolved["decision"]["action"] == resolver.ASK and isinstance(question, Mapping):
        due_on = date.fromisoformat(question["due_on"])
        recorded_item = transition(
            conn, actor, item_id, "ask", reason=question["body"],
            patch={"asked_to": question["asked_to"], "body": question["body"],
                   "due_at": resolver.due_at(due_on), "evidence": evidence},
            evidence=dict(event_evidence, asked_on=question["asked_on"],
                          due_on=question["due_on"]),
        )
    else:
        recorded_item = transition(
            conn, actor, item_id, "propose", reason=reason,
            patch={"proposal": item.get("proposal"), "reason": reason, "evidence": evidence},
            evidence=event_evidence,
        )
    return RecordedInvestigation(
        item=recorded_item,
        lease_version_id=modification.lease_version_id if modification else None,
        modification_item_id=modification.modification_item_id if modification else None,
        payload=recorded_payload,
    )


def recheck_key(lease_version_id: int) -> str:
    return "lease_modification:%d:recheck" % lease_version_id


def schedule_recheck(conn: Connection, modification_item_id: int) -> int:
    """Persist the effective-month recheck intent with the approval event.

    ``lease_api`` may insert jobs but cannot update them. Scheduling inside
    the approval transaction means confirmation cannot commit without a
    durable intent. The worker holds this job until the gateway has posted.
    """
    from ..jobs.queue import enqueue

    item = load_item(conn, modification_item_id)
    if item["kind"] != MODIFICATION_KIND or item["subject_type"] != VERSION_SUBJECT:
        raise ModificationError("work item %s is not a lease modification" % modification_item_id)
    version_id = _optional_int(item["subject_id"])
    version = conn.execute(text("""
        SELECT lease_id, effective_from FROM lease_version WHERE id = :id
    """), {"id": version_id}).mappings().first()
    if version is None:
        raise ModificationError("lease version %s does not exist" % item["subject_id"])
    entity_id = item.get("entity_id")
    if not entity_id:
        raise ModificationError("lease modification %s has no entity" % modification_item_id)
    month = version["effective_from"].replace(day=1)
    return enqueue(
        conn, RECHECK_KIND,
        {"modification_item_id": modification_item_id, "lease_version_id": version_id,
         "entity_id": entity_id, "period": month.isoformat()},
        idempotency_key=recheck_key(version_id))


def run_recheck(conn: Connection, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Check a posted modification, or finish a terminal non-postable one."""
    from ..jobs.recovery import JobHeld

    item_id = _optional_int(payload.get("modification_item_id"))
    version_id = _optional_int(payload.get("lease_version_id"))
    if item_id is None or version_id is None:
        raise ModificationError("modification recheck payload needs item and version ids")
    item = load_item(conn, item_id)
    if item["kind"] != MODIFICATION_KIND or _optional_int(item["subject_id"]) != version_id:
        raise ModificationError("modification recheck does not match work item %s" % item_id)
    state = item["state"]
    if state in _NON_POSTABLE_TERMINAL_STATES:
        return {
            "status": "cancelled",
            "lease_version_id": version_id,
            "modification_item_id": item_id,
            "item_state": state,
        }
    if state != "POSTED":
        raise JobHeld("lease modification %s is %s, waiting for gateway posting"
                      % (item_id, state), timedelta(seconds=5))

    from ..jobs.monthly import check_period

    result = check_period(conn, payload.get("entity_id"), payload.get("period"))
    return dict(status="checked", lease_version_id=version_id, **result)


def _create_modification(conn: Connection, actor, charge_item: Mapping[str, Any], result: Any,
                         payload: Mapping[str, Any], source: Optional[resolver.Source]
                         ) -> Optional[RecordedInvestigation]:
    amendment = getattr(result, "amendment", None)
    proposal = getattr(result, "proposal", None)
    decision = getattr(result, "decision", None)
    if (getattr(result, "outcome", None) != "settled" or amendment is None
            or proposal is None or source is None or decision is None):
        return None

    lease_id = str(getattr(result, "lease_id", "") or "")
    if not lease_id:
        raise ModificationError("the investigation did not name a lease")
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                 {"key": "lease_modification|%s" % lease_id})
    existing = _existing_modification(conn, lease_id, source.source_id)
    if existing is not None:
        return existing
    open_item = _open_modification(conn, lease_id)
    if open_item is not None:
        raise ModificationError(
            "lease %s already has open modification work item %s; decide it before "
            "proposing another amendment" % (lease_id, open_item))

    base = _confirmed_base(conn, lease_id, amendment.effective)
    if base is None:
        # Lightweight API tests can investigate a synthetic charge without
        # creating lease versions. The finding remains fully auditable, but
        # there is no confirmed contract snapshot from which to create v2.
        return None
    scope = conn.execute(text("""
        SELECT l.clinic_id, c.entity_id, c.region_id
          FROM lease l JOIN clinic c ON c.id = l.clinic_id WHERE l.id = :lease
    """), {"lease": lease_id}).mappings().one()
    closed_through = _closed_through(proposal)
    adjustment_period = first_open_period(
        conn, scope["entity_id"], after=closed_through)

    version = conn.execute(text(
        "SELECT coalesce(max(version), 0) + 1 FROM lease_version WHERE lease_id = :lease"),
        {"lease": lease_id}).scalar_one()
    version_id = conn.execute(text("""
        INSERT INTO lease_version (lease_id, version, effective_from)
        VALUES (:lease, :version, :effective) RETURNING id
    """), {"lease": lease_id, "version": version,
             "effective": amendment.effective}).scalar_one()
    changed: Dict[str, Any] = {}
    if amendment.new_base_rent is not None:
        changed["base_rent_monthly"] = amendment.new_base_rent
    if amendment.new_expiration is not None:
        changed["expiration"] = amendment.new_expiration.isoformat()
    # ProposedAmendment uses 0.0 when the source states no escalation change.
    # Do not turn that default into a contractual term; a non-zero amount is
    # the evidence that both escalation fields were actually amended.
    if amendment.escalation_amount:
        changed["escalation_kind"] = amendment.escalation_kind
        changed["escalation_amount"] = amendment.escalation_amount
    conn.execute(text("""
        INSERT INTO lease_term (lease_version_id, field, value, document_id, page, bbox,
                                quote, confidence, extracted_by_run)
        SELECT :new, field, value, document_id, page, bbox, quote, confidence, extracted_by_run
          FROM lease_term
         WHERE lease_version_id = :base
           AND NOT (field = ANY (CAST(:changed AS text[])))
    """), {"new": version_id, "base": base["id"], "changed": list(changed)})

    trusted = getattr(decision, "trusted", None)
    quote = getattr(trusted, "quote", None)
    confidence = round(float(getattr(result, "confidence", 0.0)), 3)
    for term_field, value in changed.items():
        conn.execute(text("""
            INSERT INTO lease_term (lease_version_id, field, value, quote, confidence)
            VALUES (:version, :field, CAST(:value AS jsonb), :quote, :confidence)
        """), {"version": version_id, "field": term_field,
                 "value": json.dumps(value), "quote": quote, "confidence": confidence})

    measurement, standing_chain = _standing_remeasurement(
        conn, lease_id=lease_id, version_id=version_id, version=version,
        effective=amendment.effective, changed_terms=frozenset(changed),
        closed_through=closed_through,
    )
    canonical_payload = _canonical_investigation(payload, measurement)
    lines = list(canonical_payload["entries"])
    if canonical_payload["balanced"] is not True or not _balanced(lines):
        raise ModificationError("a settled amendment needs balanced proposed entries")

    total = sum((_decimal(line.get("debit")) for line in lines), Decimal("0"))
    modification_evidence = {
        "lease_id": lease_id,
        "lease_version_id": version_id,
        "version": version,
        "effective_from": amendment.effective.isoformat(),
        "books_closed_through": closed_through.isoformat(),
        "adjustment_period": adjustment_period.isoformat(),
        "standing_version_chain": list(standing_chain),
        "source_charge_item_id": charge_item["id"],
        "amendment_source": source.to_dict(),
        "amendment": {
            "new_base_rent": amendment.new_base_rent,
            "new_expiration": amendment.new_expiration.isoformat()
            if amendment.new_expiration else None,
            "escalation_kind": amendment.escalation_kind,
            "escalation_amount": amendment.escalation_amount,
            "summary": amendment.summary,
        },
        "changed_terms": changed,
        "entries": lines,
        "balanced": True,
        "investigation": canonical_payload,
    }
    item = create_item(
        conn, actor, kind=MODIFICATION_KIND, subject_type=VERSION_SUBJECT,
        subject_id=version_id, title="%s v%d amendment effective %s" % (
            lease_id, version, amendment.effective.isoformat()),
        entity_id=scope["entity_id"], region_id=scope["region_id"],
        clinic_id=scope["clinic_id"], period=adjustment_period,
        amount=total, evidence=modification_evidence)
    if item["state"] == "NEW":
        reason = "%s. Controller approval confirms v%d and posts the balanced remeasurement." % (
            getattr(result, "describe", lambda: "Amendment found")().rstrip("."), version)
        item = transition(
            conn, actor, item["id"], "propose", reason=reason,
            patch={"proposal": "approve", "reason": reason,
                   "evidence": modification_evidence})
    return RecordedInvestigation(
        item=item, lease_version_id=version_id,
        modification_item_id=item["id"], payload=canonical_payload)


def _closed_through(original_proposal: Any) -> date:
    value = getattr(original_proposal, "books_closed_through", None)
    if value is None:
        from ..agents.investigation_run import BOOKS_CLOSED_THROUGH

        value = BOOKS_CLOSED_THROUGH
    if not isinstance(value, date):
        raise ModificationError("the remeasurement proposal has no valid closed-through date")
    return value


def first_open_period(conn: Connection, entity_id: str, *, after: date) -> date:
    period = conn.execute(text("""
        SELECT min(period) FROM period
         WHERE entity_id = :entity AND status = 'open' AND period > :after
    """), {"entity": entity_id, "after": after}).scalar_one()
    if period is None:
        raise ModificationError(
            "entity %s has no open accounting period after %s"
            % (entity_id, after.isoformat()))
    return period


def _standing_remeasurement(
    conn: Connection,
    *,
    lease_id: str,
    version_id: int,
    version: int,
    effective: date,
    changed_terms: frozenset[str],
    closed_through: date,
):
    """Remeasure the candidate over the gateway-standing valid-time chain.

    The API's composer is intentionally reused here. In particular, its
    expiration-only path preserves existing rent boundaries and escalation
    anniversaries instead of inventing a flat tail.
    """
    from leasedesk.models import from_dict
    from leasedesk.remeasure import remeasure

    from ..api.leases import (
        TermsError,
        Version,
        _amend,
        _versions_by_lease,
        register_terms,
    )
    from ..jobs.lease_versions import data_dir, generator_terms

    base_payload = register_terms(data_dir(), lease_id)
    if base_payload is None:
        # Some narrowly scoped tests draft from an explicit temporary root
        # without changing the process-wide API setting. This is the same
        # deterministic signed-register fallback used by lease abstraction;
        # every later term still comes from the standing database chain.
        terms, company = generator_terms(lease_id)
        base_payload = terms.to_engine_json(company) if terms is not None else None
    if base_payload is None:
        raise ModificationError("lease %s has no signed terms for remeasurement" % lease_id)

    versions = _versions_by_lease(conn, lease_id).get(lease_id, [])
    stored = next((candidate for candidate in versions
                   if candidate.number == version), None)
    if stored is None:
        raise ModificationError("lease %s v%d has no stored term snapshot" % (lease_id, version))
    candidate = Version(
        number=version,
        effective_from=effective,
        confirmed=False,
        terms=dict(stored.terms),
        changed_terms=changed_terms,
    )
    standing = [
        existing for existing in versions
        if existing.number != version and existing.confirmed
        and existing.effective_from <= closed_through
    ]
    chain = standing + [candidate]
    chain.sort(key=lambda existing: (existing.effective_from, existing.number))

    composed = dict(base_payload, amendments=[])
    try:
        for existing in chain:
            composed = _amend(composed, existing)
        lease = from_dict(composed)
        measurement = remeasure(lease, effective=effective, through=closed_through)
        chain = standing_version_chain(
            conn, lease_id, exclude_version_id=version_id, through=closed_through)
        return measurement, chain
    except (KeyError, TermsError, TypeError, ValueError) as exc:
        raise ModificationError(
            "lease %s v%d cannot be remeasured from its standing versions: %s"
            % (lease_id, version, exc)) from None


def _canonical_investigation(payload: Mapping[str, Any], measurement: Any) -> Dict[str, Any]:
    lines = [
        {
            "account": line.account,
            "debit": round(float(line.debit), 2),
            "credit": round(float(line.credit), 2),
        }
        for line in measurement.entries
    ]
    canonical = dict(payload)
    canonical.update({
        "liability_before": round(float(measurement.liability_before), 2),
        "liability_after": round(float(measurement.liability_after), 2),
        "rou_before": round(float(measurement.rou_before), 2),
        "rou_after": round(float(measurement.rou_after), 2),
        "liability_delta": round(float(measurement.liability_delta), 2),
        "rou_delta": round(float(measurement.rou_delta), 2),
        "entries": lines,
        "balanced": _balanced(lines),
    })
    return canonical


def standing_version_chain(conn: Connection, lease_id: str, *,
                           exclude_version_id: Optional[int], through: date) -> tuple[int, ...]:
    """Stable version numbers underlying an immutable accounting proposal."""
    return tuple(conn.execute(text("""
        SELECT v.version
          FROM lease_version v
          LEFT JOIN LATERAL (
              SELECT w.kind, w.state FROM work_item w
               WHERE w.subject_type = 'lease_version' AND w.subject_id = v.id::text
               ORDER BY w.id DESC LIMIT 1
          ) item ON true
         WHERE v.lease_id = :lease AND v.effective_from <= :through
           AND (:excluded IS NULL OR v.id <> :excluded)
           AND v.confirmed_by IS NOT NULL
           AND coalesce(CASE
               WHEN item.kind = :modification THEN item.state = 'POSTED'
               ELSE item.state IN ('APPROVED', 'POSTED', 'CLOSED')
           END, true)
         ORDER BY v.effective_from, v.version
    """), {"lease": lease_id, "through": through, "excluded": exclude_version_id,
             "modification": MODIFICATION_KIND}).scalars())


def _open_modification(conn: Connection, lease_id: str) -> Optional[int]:
    return conn.execute(text("""
        SELECT w.id FROM work_item w JOIN lease_version v ON v.id::text = w.subject_id
         WHERE w.kind = :kind AND w.subject_type = :subject
           AND v.lease_id = :lease
           AND w.state NOT IN ('POSTED', 'REJECTED', 'CLOSED')
         ORDER BY w.id LIMIT 1
    """), {"kind": MODIFICATION_KIND, "subject": VERSION_SUBJECT,
             "lease": lease_id}).scalar()


def _existing_modification(conn: Connection, lease_id: str,
                           source_id: str) -> Optional[RecordedInvestigation]:
    row = conn.execute(text("""
        SELECT v.id AS lease_version_id, w.id AS work_item_id
          FROM lease_version v JOIN work_item w
            ON w.kind = :kind AND w.subject_type = :subject AND w.subject_id = v.id::text
         WHERE v.lease_id = :lease
           AND w.evidence->'amendment_source'->>'source_id' = :source
         ORDER BY v.version DESC LIMIT 1
    """), {"kind": MODIFICATION_KIND, "subject": VERSION_SUBJECT,
             "lease": lease_id, "source": source_id}).mappings().first()
    if row is None:
        return None
    item = load_item(conn, row["work_item_id"])
    evidence = item.get("evidence") if isinstance(item.get("evidence"), Mapping) else {}
    recorded = evidence.get("investigation")
    payload = dict(recorded) if isinstance(recorded, Mapping) else {}
    return RecordedInvestigation(
        item=item, lease_version_id=row["lease_version_id"],
        modification_item_id=row["work_item_id"], payload=payload)


def _confirmed_base(conn: Connection, lease_id: str, effective: date) -> Optional[Mapping]:
    return conn.execute(text("""
        SELECT v.id, v.version
          FROM lease_version v
         WHERE v.lease_id = :lease AND v.effective_from <= :effective
           AND v.confirmed_by IS NOT NULL
           AND coalesce((
               SELECT CASE
                        WHEN w.kind = :modification
                        THEN w.state = 'POSTED'
                        ELSE w.state IN ('APPROVED', 'POSTED', 'CLOSED')
                      END
                 FROM work_item w
                WHERE w.subject_type = 'lease_version' AND w.subject_id = v.id::text
                ORDER BY w.id DESC LIMIT 1
           ), true)
         ORDER BY v.effective_from DESC, v.version DESC LIMIT 1
    """), {"lease": lease_id, "effective": effective,
             "modification": MODIFICATION_KIND}).mappings().first()


def _investigation_sources(result: Any) -> list[resolver.Source]:
    """Every ranked source the investigation found, with safe money claims.

    The structured amendment amount belongs only to the trusted winner. Other
    sources get a numeric value only when their own claim or quote contains
    one explicit dollar amount. A non-rent winner remains value-less and can
    never gain monetary authority from the invoice under investigation.
    """
    amendment = getattr(result, "amendment", None)
    decision = getattr(result, "decision", None)
    trusted = getattr(decision, "trusted", None)
    out = []
    for source in list(getattr(result, "sources", None) or []):
        if trusted is not None and source.source_id == trusted.source_id and amendment is not None:
            value = amendment.new_base_rent
        else:
            value = _claimed_money(source)
        out.append(resolver.from_trust(
            source, value=value,
            citation={"doc_id": source.source_id, "kind": "email"},
        ))
    return out


def _claimed_money(source: Any) -> Optional[float]:
    matches = _CURRENCY.findall("%s\n%s" % (
        getattr(source, "claim", "") or "", getattr(source, "quote", "") or ""))
    values = {Decimal(value.replace(",", "")) for value in matches}
    if len(values) != 1:
        return None
    return float(next(iter(values)))


def _balanced(lines: list) -> bool:
    try:
        debits = sum((_decimal(line.get("debit")) for line in lines), Decimal("0"))
        credits = sum((_decimal(line.get("credit")) for line in lines), Decimal("0"))
    except (AttributeError, InvalidOperation, TypeError, ValueError):
        return False
    return bool(lines) and debits == credits


def _decimal(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("money must be a number")
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("money must be finite")
    return amount.quantize(Decimal("0.01"))


def _optional_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
