"""The answer key: what a perfect run would produce.

Written by the generator, read only by `eval/`. Nothing in `backend/app` may
import this module or the file it writes — a benchmark the system under test
can read is not a benchmark, and a test enforces it.

It carries three things the eval scores against:

  - **The true lease terms**, field by field, for extraction accuracy.
  - **Every planted error**, with what was billed, what the lease supports,
    which clause proves it, and where it should have been routed.
  - **The amendment**, with the remeasurement it should produce.
"""

import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Union

from .company import Company, build_company
from .errors import JANUARY_2026, real_errors
from .history import PAST_MISTAKES, build_history
from .leases import SECOND_AMENDMENT, LeaseTerms, build_leases

PERIOD = date(2026, 1, 1)


def build_answer_key(
    company: Optional[Company] = None,
    leases: Optional[List[LeaseTerms]] = None,
    document_shas: Optional[Dict[str, str]] = None,
) -> dict:
    company = company or build_company()
    leases = leases if leases is not None else build_leases(company)
    shas = document_shas or {}

    return {
        "generated_by": "datagen.answer_key",
        "seed": company.seed,
        "company": company.entity.name,
        "period": PERIOD.isoformat(),
        "leases": {t.lease_id: _lease_entry(t, company, shas) for t in leases},
        "errors": [_error_entry(e) for e in JANUARY_2026],
        "history_mistakes": [_error_entry(e) for e in PAST_MISTAKES],
        "amendment": _amendment_entry(),
        "totals": {
            "leases": len(leases),
            "planted_errors": len(JANUARY_2026),
            "to_hold": len(real_errors()),
            "to_approve": len(JANUARY_2026) - len(real_errors()),
            "overbilled": round(sum(e.variance for e in real_errors()), 2),
        },
    }


def write(path: Union[str, Path], key: Optional[dict] = None, **kwargs) -> Path:
    key = key if key is not None else build_answer_key(**kwargs)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(key, indent=2, sort_keys=True) + "\n")
    return out


def load(path: Union[str, Path]) -> dict:
    return json.loads(Path(path).read_text())


def _lease_entry(terms: LeaseTerms, company: Company, shas: Dict[str, str]) -> dict:
    clinic = company.clinic(terms.clinic_id)
    landlord = company.landlord(terms.landlord_id)
    return {
        "clinic_id": terms.clinic_id,
        "suite": clinic.suite,
        "document_sha256": shas.get(terms.lease_id),
        # Field by field, exactly as the abstraction agent must return them.
        "fields": {
            "commencement": terms.commencement.isoformat(),
            "expiration": terms.expiration.isoformat(),
            "rentable_sf": terms.rsf,
            "proportionate_share_pct": round(company.pro_rata_for(terms.clinic_id) * 100, 2),
            "base_rent_monthly": terms.base_rent_monthly,
            "escalation_kind": terms.escalation.kind,
            "escalation_amount": terms.escalation.amount,
            "cam_estimate_psf_annual": terms.cam_estimate_psf_annual,
            "security_deposit": terms.security_deposit,
            "renewal_count": terms.renewal.count,
            "renewal_years": terms.renewal.years,
            "renewal_notice_days": terms.renewal.notice_days,
            "authorized_representative": landlord.authorized_rep,
        },
        "expected_rent": {
            PERIOD.isoformat(): terms.rent_for(PERIOD),
        },
        "cam_estimate_monthly": terms.cam_estimate_monthly,
    }


def _error_entry(error) -> dict:
    return {
        "error_id": error.error_id,
        "kind": error.kind,
        "clinic_id": error.clinic_id,
        "period": error.period.isoformat(),
        "charge_type": error.charge_type,
        "billed": error.billed,
        "correct": error.correct,
        "variance": error.variance,
        "is_error": error.is_error,
        "lease_section": error.lease_section,
        "proof_quote": error.proof_quote,
        "expected_route": error.expected_route,
        "expected_outcome": error.expected_outcome,
        "description": error.description,
    }


def _amendment_entry() -> dict:
    a = SECOND_AMENDMENT
    return {
        "amendment_id": a.amendment_id,
        "lease_id": a.lease_id,
        "effective": a.effective.isoformat(),
        "source_id": "eml-20260618-amend",
        "expected_trust_rank": 1,
        "proof_quote": a.proof_quote,
        "new_base_rent": a.new_base_rent,
        "new_expiration": a.new_expiration.isoformat() if a.new_expiration else None,
        "new_escalation": a.new_escalation.amount if a.new_escalation else None,
        # What the remeasurement must produce, to the cent.
        "expected_liability_delta": 443255.70,
        "expected_rou_delta": 443255.70,
        "expected_entries": 4,
        "expected_balanced": True,
        # Sources that must NOT settle it.
        "must_not_settle": [
            "eml-20260622-pm-claim",
            "eml-20260701-forged",
            "eml-20260705-injection",
        ],
    }
