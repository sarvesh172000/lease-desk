"""POST /api/evidence-packs: a PDF an auditor can re-perform a number from.

    POST /api/evidence-packs  {"subject": "work_item:42"}
                              {"subject": "journal_entry:7"}
                              {"subject": "lease:LEASE-01:2026-01"}
                              {"subject": {"type": "lease_period", "lease_id": "LEASE-01",
                                           "period": "2026-01"}}
    -> 200 application/pdf, with X-Chain-Verified, X-Chain-Broken-Seq (when
       broken) and X-Last-Event-Seq headers repeating the stamp in the PDF

The auditor and the controller may ask (403 for other roles, 401 when not
signed in), for anything in their scope (a subject outside it is a 404). The
pack is gathered on a `lease_reader` connection in a READ ONLY transaction
(work/evidence_pack.py) and is not stored.
"""

from pathlib import Path
from typing import Any, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..auth.deps import SessionActor, require_role
from ..docs.storage import LocalStorage
from ..work.evidence_pack import PackError, PackNotFound, build_pack, parse_subject
from ..work.why import read_only
from .deps import get_data_dir, get_storage
from .items import in_scope
from .why import get_reader_engine

PACK_ROLES = ("auditor", "controller")

router = APIRouter(prefix="/api", tags=["evidence-packs"])


class PackRequest(BaseModel):
    subject: Union[str, dict]


@router.post("/evidence-packs", response_class=Response,
             responses={200: {"content": {"application/pdf": {}}}})
def evidence_pack(body: PackRequest,
                  actor: SessionActor = Depends(require_role(*PACK_ROLES)),
                  eng: Any = Depends(get_reader_engine),
                  data_dir: Path = Depends(get_data_dir),
                  storage: Optional[LocalStorage] = Depends(get_storage)) -> Response:
    try:
        subject = parse_subject(body.subject)
    except PackError as exc:
        raise HTTPException(422, str(exc)) from None
    try:
        with read_only(eng) as conn:
            pack = build_pack(conn, subject, storage=storage, data_dir=data_dir,
                              requested_by=actor.id, visible=lambda item: in_scope(actor, item))
    except PackNotFound as exc:
        raise HTTPException(404, str(exc)) from None
    stamp = pack.summary["stamp"]
    headers = {
        "Content-Disposition": 'attachment; filename="evidence-pack-%s.pdf"' % _slug(subject.label),
        "X-Chain-Verified": "true" if stamp["chain_verified"] else "false",
        "X-Last-Event-Seq": str(stamp["last_event_seq"] or ""),
    }
    if stamp["broken_seq"] is not None:
        headers["X-Chain-Broken-Seq"] = str(stamp["broken_seq"])
    return Response(content=pack.pdf, media_type="application/pdf", headers=headers)


def _slug(label: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in label).strip("-").lower()[:80] or "pack"
