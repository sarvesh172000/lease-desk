"""GET /api/exceptions, GET /api/exceptions/{id}, and the actions on one.

    GET  /api/exceptions                     the open holds (§16 #2)
    GET  /api/exceptions/{id}                the money screen (§16 #3)
    POST /api/exceptions/{id}/approve        sign-off (§16 #4)
    POST /api/exceptions/{id}/hold           park it (the queue's hold, same path)
    POST /api/exceptions/{id}/pay-as-billed  {"reason"}: the controller's override
    POST /api/exceptions/{id}/investigate    SSE: the investigation's stages (§16 #5)

Approve on a hold upholds it (work/charges.py): only the undisputed
`supported` amount posts, and a charge nothing supports posts nothing. The
only way a disputed amount is paid is pay-as-billed, controller-only, with a
reason. The detail shows the outcome as `resolution`, `payable` (what
approving posts) and `disputed` (what stays out of the ledger).

An exception is a CHARGE_CHECK work item whose proposal is `hold`: the checker
compared a landlord charge with what the lease supports and they disagreed.
`exc_<work_item.id>` names it. The list is only the holds; the detail and the
actions take any charge check by the same id, so a charge the checker found
correct opens on the same screen (variance 0, proposal `approve`) and a person
can sign it off there.

Its numbers come from `work_item.evidence`, which the checker writes:

    {"lease_id": "LEASE-01", "charge_id": "<landlord_charge.id>",
     "charge_ids": [...], "charge_type": "cam_estimate",
     "billed": 6458.33, "supported": 5941.67, "confidence": 0.94,
     "rule": "operating_expense", "proof": {"quote": ..., "section": "4.1", ...},
     "investigation": {"root_cause": ..., "confidence": ..., "evidence": [...],
                       "liability_before": ..., "entries": [...], ...}}

Anything evidence does not carry falls back to the landlord charge the item is
about (`subject_type = 'landlord_charge'`, or `evidence.charge_id`), and
otherwise is null. Nothing is computed here that the checker or the engine did
not already decide; `delta` is billed minus supported, as in the fixture.

Work state -> the four statuses the UI knows (DESIGN.md §16):

    NEW         exception        variance found, nobody has proposed anything yet
    PROPOSED    pending_review   the agent proposed the hold; a person signs off
    NEEDS_INFO  escalated        a question is out to a person
    HELD        escalated        parked on someone outside the system
    APPROVED    balanced         a person signed off; only posting is left
    POSTED, CLOSED, REJECTED     balanced, and no longer listed as open
"""

import json
import logging
import math
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ..agents import investigation_run
from ..auth.deps import SessionActor, current_actor
from ..docs.storage import LocalStorage
from ..records.ingest import stable_id
from ..work import charges
from . import evidence as where
from .deps import get_data_dir, get_engine, get_gateway_engine, get_storage
from .items import perform
from .schemas import (
    ApproveResult,
    Entry,
    Evidence,
    ExceptionDetail,
    ExceptionSummary,
    Investigation,
    InvoiceLine,
    LeaseCitation,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["exceptions"], dependencies=[Depends(current_actor)])

STATUS_BY_STATE = {
    "NEW": "exception",
    "PROPOSED": "pending_review",
    "NEEDS_INFO": "escalated",
    "HELD": "escalated",
    "APPROVED": "balanced",
    "POSTED": "balanced",
    "CLOSED": "balanced",
    "REJECTED": "balanced",
}
CLOSED_STATES = ("POSTED", "CLOSED", "REJECTED")

_ID = re.compile(r"^exc_([1-9][0-9]{0,17})$")

_SELECT = """
    SELECT w.id, w.state, w.clinic_id, w.period, w.amount, w.evidence, w.proposal, w.reason,
           c.id          AS charge_id,
           c.lease_id    AS charge_lease_id,
           c.clinic_id   AS charge_clinic_id,
           c.charge_type AS charge_type,
           c.amount      AS charge_amount,
           c.period      AS charge_period
      FROM work_item w
      LEFT JOIN landlord_charge c
        ON c.id = COALESCE(CASE WHEN w.subject_type = 'landlord_charge' THEN w.subject_id END,
                           w.evidence ->> 'charge_id')
     WHERE w.kind = 'CHARGE_CHECK'
"""
_HOLDS = " AND w.proposal = 'hold'"


def exception_id(work_item_id: int) -> str:
    return "exc_%d" % work_item_id


def open_exceptions(conn: Connection) -> List[Dict[str, Any]]:
    """Every open exception, flattened to what the list and the portfolio need."""
    rows = conn.execute(text(_SELECT + _HOLDS + """
           AND w.state <> ALL(:closed)
         ORDER BY w.period NULLS LAST, w.id
    """), {"closed": list(CLOSED_STATES)}).mappings().all()
    return [_flatten(r) for r in rows]


@router.get("/exceptions", response_model=List[ExceptionSummary])
def list_exceptions(eng: Engine = Depends(get_engine)) -> List[ExceptionSummary]:
    with eng.connect() as conn:
        return [ExceptionSummary(**{k: e[k] for k in ExceptionSummary.model_fields})
                for e in open_exceptions(conn)]


@router.get("/exceptions/{exc_id}", response_model=ExceptionDetail)
def get_exception(exc_id: str, eng: Engine = Depends(get_engine),
                  data_dir: Path = Depends(get_data_dir),
                  storage: Optional[LocalStorage] = Depends(get_storage)) -> ExceptionDetail:
    """§16's shape, plus where on the page: `invoice_line` (the billed line,
    boxed on the invoice) and `lease_citation` (the clause the checker cited,
    boxed on the lease). Either is null when it cannot be located; a box is
    never invented (api/evidence.py)."""
    with eng.connect() as conn:
        row = _row(conn, exc_id)
        flat = _flatten(row)
        ev = flat["evidence"]
        charge = where.document_for_charge(conn, _str(ev.get("charge_id")) or row["charge_id"])
        lease_sha = _lease_sha(conn, data_dir, flat["lease_id"])
    billed = row["charge_amount"] if row["charge_amount"] is not None else row["amount"]
    pay = None if billed is None else charges.payable(
        {"kind": "CHARGE_CHECK", "proposal": row["proposal"], "evidence": ev}, billed)
    line = where.invoice_line(storage, charge)
    cited = where.lease_citation(storage, lease_sha, flat["lease_id"], ev.get("proof"))
    return ExceptionDetail(
        **{k: flat[k] for k in ("exception_id", "lease_id", "period", "expected",
                                "actual", "delta", "status")},
        investigation=_investigation(ev.get("investigation")),
        item_id=row["id"], state=row["state"], clinic_id=flat["clinic_id"],
        charge_type=flat["charge_type"], confidence=flat["confidence"],
        proposal=row["proposal"], reason=row["reason"], rule=_str(ev.get("rule")),
        resolution=_str(ev.get("resolution")), resolved_by=_str(ev.get("resolved_by")),
        override_reason=_str(ev.get("override_reason")),
        payable=float(pay.amount) if pay else None,
        disputed=float(pay.disputed) if pay else None,
        invoice_line=InvoiceLine(**line) if line else None,
        lease_citation=LeaseCitation(**cited) if cited else None,
    )


class ApproveBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=4000)


class OverrideBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=4000)


@router.post("/exceptions/{exc_id}/approve", response_model=ApproveResult)
def approve_exception(exc_id: str, body: Optional[ApproveBody] = None,
                      actor: SessionActor = Depends(current_actor),
                      eng: Engine = Depends(get_engine),
                      gateway_engine: Engine = Depends(get_gateway_engine)) -> ApproveResult:
    """§16 #4, sign-off: the same approve as POST /api/items/{id}/actions/approve
    (transition() as the session actor, then the gateway post), answered in
    the four statuses the exception screen knows, plus the work state and
    whether the gateway posted. 403 refused (and on record), 409 not awaiting
    review, 404 not a charge check."""
    return _act(exc_id, "approve", body, actor, eng, gateway_engine)


@router.post("/exceptions/{exc_id}/hold", response_model=ApproveResult)
def hold_exception(exc_id: str, body: Optional[ApproveBody] = None,
                   actor: SessionActor = Depends(current_actor),
                   eng: Engine = Depends(get_engine),
                   gateway_engine: Engine = Depends(get_gateway_engine)) -> ApproveResult:
    """Hold: the same transition as POST /api/items/{id}/actions/hold. The item
    goes to HELD (status `escalated`) and nothing is posted. Same errors."""
    return _act(exc_id, "hold", body, actor, eng, gateway_engine)


@router.post("/exceptions/{exc_id}/pay-as-billed", response_model=ApproveResult)
def pay_as_billed(exc_id: str, body: OverrideBody,
                  actor: SessionActor = Depends(current_actor),
                  eng: Engine = Depends(get_engine),
                  gateway_engine: Engine = Depends(get_gateway_engine)) -> ApproveResult:
    """The override: approve a held charge and pay the billed amount anyway.
    The same as POST /api/items/{id}/actions/approve with
    patch {"resolution": "pay_as_billed"}. Controller only: anyone else is
    403 and the refusal is on record. The reason is required (422 without
    one, blank included) and goes on the approve event."""
    return _act(exc_id, "approve", body, actor, eng, gateway_engine,
                patch={"resolution": charges.PAY_AS_BILLED})


def _act(exc_id: str, action: str, body, actor: SessionActor,
         eng: Engine, gateway_engine: Engine, patch: Optional[dict] = None) -> ApproveResult:
    with eng.connect() as conn:
        item_id = _row(conn, exc_id)["id"]
    result = perform(eng, gateway_engine, actor, item_id, action,
                     reason=body.reason if body is not None else None, patch=patch)
    return ApproveResult(status=STATUS_BY_STATE[result.state], exception_id=exception_id(item_id),
                         state=result.state, posting=result.posting)


def sse_delay() -> float:
    """Seconds between investigation frames, so the timeline visibly unfolds.
    Tests override it to 0."""
    return 0.45


def investigation_runner() -> Callable[..., Any]:
    """The modification agent's caller (agents/investigation_run.run). A
    dependency so a test can put a fake in its place without patching."""
    return investigation_run.run


@router.post("/exceptions/{exc_id}/investigate", response_class=StreamingResponse,
             responses={200: {"content": {"text/event-stream": {}}}})
def investigate(exc_id: str, eng: Engine = Depends(get_engine),
                data_dir: Path = Depends(get_data_dir),
                storage: Optional[LocalStorage] = Depends(get_storage),
                delay: float = Depends(sse_delay),
                run: Callable[..., Any] = Depends(investigation_runner)) -> StreamingResponse:
    """§16 #5: what explains this variance, as `data: {...}` frames.

    - An item whose evidence already holds an investigation replays it:
      searching, found (one frame per ranked source) or not_found, remeasured
      (only when the engine recorded balances before and after), complete.
    - Otherwise the modification agent searches the mailbox
      (agents/investigation_run.py): the model nominates documents, trust.py
      ranks them, the engine remeasures. The frames are read off its result,
      which is then recorded on the work item, merged into the checker's own
      evidence, so a reload replays it and the approval that follows is
      against the same figures. Unexplained is a valid outcome (not_found).
    - When the agent cannot run (no model and nothing cached, or it failed),
      the frames are the checker's own evidence, honestly: the clause it
      cited (located on the lease page) or not_found, then an `error` frame
      saying why the mailbox was not searched. No remeasurement is invented.

    Nothing is posted here: an investigation proposes, a person approves.
    """
    with eng.connect() as conn:
        row = _row(conn, exc_id)
        flat = _flatten(row)
        lease_sha = _lease_sha(conn, data_dir, flat["lease_id"])
    frames = _investigation_stream(eng, row["id"], flat, storage, lease_sha, run)

    def stream() -> Iterator[str]:
        for i, frame in enumerate(frames):
            if i and delay:
                time.sleep(delay)
            yield _sse(frame)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _sse(event: dict) -> str:
    return "data: %s\n\n" % json.dumps(event)


def _investigation_stream(eng: Engine, item_id: int, flat: Dict[str, Any],
                          storage: Optional[LocalStorage], lease_sha: Optional[str],
                          run: Callable[..., Any]) -> Iterator[Dict[str, Any]]:
    """The frames, lazily: the agent runs once the response has started."""
    raw = flat["evidence"].get("investigation")
    if isinstance(raw, dict) and raw:
        yield from _replay(flat, raw)
        return
    if not flat["lease_id"]:
        yield from _checker_frames(flat, storage, lease_sha)
        yield {"stage": "complete", "entries": 0, "balanced": None,
               "message": _str(flat.get("reason")) or "Nothing more on record."}
        return

    try:
        result, searched = run(lease_id=flat["lease_id"], period=flat["period"],
                               expected=flat["expected"], actual=flat["actual"],
                               delta=flat["delta"])
    except investigation_run.NoModel as exc:
        yield from _checker_frames(flat, storage, lease_sha)
        yield {"stage": "error", "message": "%s The mailbox was not searched; what is shown is "
                                            "the checker's own evidence." % exc}
        return
    except Exception as exc:  # noqa: BLE001 - the stream owns the error
        log.exception("investigation failed for work item %s", item_id)
        yield from _checker_frames(flat, storage, lease_sha)
        yield {"stage": "error", "message": "The investigation failed: %s" % exc}
        return

    payload = investigation_run.to_payload(result)
    yield from _replay(flat, payload, searched=searched)
    try:
        _record(eng, item_id, payload)
    except Exception:  # noqa: BLE001 - the finding stands even if recording fails
        log.exception("could not record the investigation on work item %s", item_id)
        yield {"stage": "error",
               "message": "Found, but could not be recorded; it will not survive a reload."}


def _record(eng: Engine, item_id: int, payload: dict) -> None:
    """Merge the investigation into the item's evidence, leaving the checker's
    own findings untouched."""
    with eng.connect() as conn:
        with conn.begin():
            conn.execute(text("""
                UPDATE work_item
                   SET evidence = COALESCE(evidence, '{}'::jsonb)
                                  || jsonb_build_object('investigation', CAST(:inv AS jsonb))
                 WHERE id = :id
            """), {"id": item_id, "inv": json.dumps(payload)})


def _checker_frames(flat: Dict[str, Any], storage: Optional[LocalStorage],
                    lease_sha: Optional[str]) -> List[Dict[str, Any]]:
    """searching, then found (the clause the checker cited) or not_found."""
    ev = flat["evidence"]
    lease_id = flat["lease_id"]
    proof = ev.get("proof") if isinstance(ev.get("proof"), dict) else {}
    section = proof.get("section")
    frames: List[Dict[str, Any]] = [{
        "stage": "searching",
        "message": "Checking %s against %s%s" % (
            _str(ev.get("charge_ref")) or _str(ev.get("invoice_id")) or "the billed charge",
            lease_id or "the lease", " §%s" % section if section else ""),
    }]
    quote = _str(proof.get("quote"))
    if quote:
        cited = where.lease_citation(storage, lease_sha, lease_id, proof)
        frames.append({"stage": "found", "doc_id": cited["doc_id"] if cited else None,
                       "quote": quote, "confidence": flat["confidence"],
                       "source": cited["label"] if cited else None,
                       "page": cited["page"] if cited else None,
                       "box": cited["box"] if cited else None})
    else:
        frames.append({"stage": "not_found",
                       "message": "No clause is cited for this charge."})
    return frames


def _replay(flat: Dict[str, Any], raw: dict, searched: Optional[int] = None) -> List[Dict[str, Any]]:
    """An investigation, stage by stage, read off what it recorded."""
    inv = _investigation(raw) or Investigation()
    if searched is not None:
        message = "Searching %s documents…" % "{:,}".format(searched)
    else:
        message = "Searching for what explains the %s variance on %s" % (
            "${:,.2f}".format(flat["delta"]) if flat["delta"] is not None else "billed",
            flat["lease_id"] or "this lease")
    frames: List[Dict[str, Any]] = [{"stage": "searching", "message": message}]
    # A source the investigation ranked but which does not explain the
    # variance is not a finding.
    if inv.explains_variance is not False and inv.evidence:
        for e in inv.evidence:
            frames.append({"stage": "found", "doc_id": e.doc_id, "quote": e.quote,
                           "confidence": inv.confidence, "trust_rank": e.trust_rank,
                           "source": e.source, "page": e.page, "box": e.box})
    else:
        frames.append({"stage": "not_found",
                       "message": "The investigation found no explaining document."})
    if inv.liability_before is not None and inv.liability_after is not None:
        liability = _money(raw.get("liability_delta"))
        rou = _money(raw.get("rou_delta"))
        # Not a new figure: the change between the engine's own two balances.
        if liability is None:
            liability = round(inv.liability_after - inv.liability_before, 2)
        if rou is None and inv.rou_before is not None and inv.rou_after is not None:
            rou = round(inv.rou_after - inv.rou_before, 2)
        frames.append({"stage": "remeasured", "liability_delta": liability, "rou_delta": rou})
    frames.append({"stage": "complete", "entries": len(inv.entries),
                   "balanced": inv.balanced if inv.entries else None})
    return frames


def _row(conn: Connection, exc_id: str):
    """The charge check `exc_id` names, or 404."""
    match = _ID.match(exc_id)
    if match is None:
        raise HTTPException(404, "no exception %r" % exc_id)
    row = conn.execute(text(_SELECT + " AND w.id = :id"),
                       {"id": int(match.group(1))}).mappings().first()
    if row is None:
        raise HTTPException(404, "no exception %r" % exc_id)
    return row


# --- the documents behind the two panes ------------------------------------------

def _lease_sha(conn: Connection, data_dir: Path, lease_id: Optional[str]) -> Optional[str]:
    """The stored lease PDF for `lease_id`: the generator's manifest, else the
    ingested document. Ingest names a lease document
    `stable_id("datagen.leases", lease_id)` (records/ingest.py), so that link
    needs no column of its own. A lease never ingested simply has none."""
    if not lease_id:
        return None
    sha = where.lease_sha(data_dir, lease_id)
    if sha:
        return sha
    row = conn.execute(text("SELECT sha256 FROM source_document WHERE id = :id AND kind = 'lease'"),
                       {"id": stable_id("datagen.leases", lease_id)}).first()
    return row[0] if row else None


# --- shaping ---------------------------------------------------------------------

def _flatten(row) -> Dict[str, Any]:
    ev = row["evidence"] if isinstance(row["evidence"], dict) else {}
    actual = _money(ev.get("billed"))
    if actual is None:
        actual = _money(row["charge_amount"]) if row["charge_amount"] is not None \
            else _money(row["amount"])
    expected = _money(ev.get("supported"))
    inv = ev.get("investigation") if isinstance(ev.get("investigation"), dict) else {}
    confidence = _number(ev.get("confidence"))
    if confidence is None:
        confidence = _number(inv.get("confidence"))
    return {
        "exception_id": exception_id(row["id"]),
        "lease_id": _str(ev.get("lease_id")) or row["charge_lease_id"],
        "clinic_id": row["clinic_id"] or row["charge_clinic_id"],
        "period": row["period"] or row["charge_period"],
        "charge_type": _str(ev.get("charge_type")) or row["charge_type"],
        "expected": expected,
        "actual": actual,
        "delta": round(actual - expected, 2) if actual is not None and expected is not None else None,
        "status": STATUS_BY_STATE[row["state"]],
        "confidence": confidence,
        "evidence": ev,
        "reason": row["reason"],
    }


def _investigation(raw: Optional[dict]) -> Optional[Investigation]:
    """The investigation exactly as recorded, or None if there was none.

    The distinction matters on screen: an empty Investigation renders as an
    investigation that ran and explained nothing, rather than as one that was
    never run.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    evidence = [_lenient(Evidence, e) for e in _list(raw.get("evidence")) if isinstance(e, dict)]
    entries = [Entry(account=str(e.get("account") or ""), debit=_money(e.get("debit")) or 0.0,
                     credit=_money(e.get("credit")) or 0.0)
               for e in _list(raw.get("entries")) if isinstance(e, dict)]
    balanced = _bool(raw.get("balanced"))
    if balanced is None and entries:
        # Not a new number: the same debits-equal-credits test the engine asserts.
        balanced = abs(sum(e.debit for e in entries) - sum(e.credit for e in entries)) < 0.005
    return Investigation(
        root_cause=_str(raw.get("root_cause")),
        confidence=_number(raw.get("confidence")),
        explains_variance=_bool(raw.get("explains_variance")),
        evidence=evidence,
        liability_before=_money(raw.get("liability_before")),
        liability_after=_money(raw.get("liability_after")),
        rou_before=_money(raw.get("rou_before")),
        rou_after=_money(raw.get("rou_after")),
        entries=entries,
        balanced=balanced,
    )


def _number(value) -> Optional[float]:
    """A finite float from whatever evidence holds, else None. Evidence is
    written by agents, so a string or a NaN there must not become a 500."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _money(value) -> Optional[float]:
    number = _number(value)
    return None if number is None else round(number, 2)


def _str(value) -> Optional[str]:
    return value if isinstance(value, str) else None


def _bool(value) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _lenient(model, data: dict):
    """Build `model` from agent-written JSON, nulling any field that does not
    fit rather than failing the whole screen over one bad value."""
    values = {k: data.get(k) for k in model.model_fields}
    try:
        return model(**values)
    except ValidationError as exc:
        for error in exc.errors():
            values[error["loc"][0]] = None
        return model(**values)
