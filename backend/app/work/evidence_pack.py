"""Evidence packs: everything an auditor needs to re-perform one number, as a PDF.

A pack is requested for a subject, any of

    work_item:42                one work item (a charge check, a lease confirmation)
    journal_entry:7             the work item behind a posted entry, and the entry
    lease:LEASE-01:2026-01      every charge check on one lease for one period

or the same as a mapping ({"type": "work_item", "id": 42}, {"type":
"lease_period", "lease_id": ..., "period": "2026-01"}). It contains, per
work item:

  - the lease clause cited: quote, section, page, and the page itself with the
    clause boxed (located with the teammate's pipeline, api/evidence.py; no
    box is drawn that the pipeline did not find)
  - the invoice line: invoice, description, amount, page, boxed the same way
  - the calculation: billed, supported, disputed, and what was payable
  - the sources weighed and their trust rank (work/why.py sources_for)
  - every approval and denial on record, with actor and time, including the
    confirmation of the lease version the checker read
  - the journal entries posted for it
  - the policy versions cited (or that none was)

and once, a chain verification stamp: `verify_chain()` over the whole stream,
the seq and hash of the last event the pack covers, the chain head, the
database role it was generated as, and when.

Generated read-only: `build_pack` runs on whatever connection it is given,
and the API hands it a `lease_reader` connection inside a READ ONLY
transaction (work/why.py `read_only`). Nothing is stored.
"""

import html
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .charges import payable
from .events import verify_chain
from .why import decisions_by_policy, sources_for, timeline_for

SUBJECT_KINDS = ("work_item", "journal_entry", "lease_period")
IMAGE_DPI = 110


class PackError(ValueError):
    """The subject is malformed."""


class PackNotFound(LookupError):
    """The subject names nothing on record, or nothing the requester may see."""


@dataclass(frozen=True)
class Subject:
    kind: str
    id: Optional[str] = None
    lease_id: Optional[str] = None
    period: Optional[date] = None

    @property
    def label(self) -> str:
        if self.kind == "lease_period":
            return "lease %s, %s" % (self.lease_id, self.period.strftime("%B %Y"))
        return "%s %s" % (self.kind.replace("_", " "), self.id)


@dataclass
class Pack:
    pdf: bytes
    summary: Dict[str, Any]


# ---------------------------------------------------------------- subject

_STRING = re.compile(r"^(work_item|item|journal_entry|entry|lease):(.+)$")


def parse_subject(value: Any) -> Subject:
    """A Subject from a string or a mapping; PackError when malformed."""
    if isinstance(value, str):
        m = _STRING.match(value.strip())
        if not m:
            raise PackError("subject must look like work_item:42, journal_entry:7 or "
                            "lease:LEASE-01:2026-01, got %r" % value)
        kind, rest = m.groups()
        if kind == "lease":
            lease_id, _, period = rest.rpartition(":")
            return _subject({"type": "lease_period", "lease_id": lease_id, "period": period})
        return _subject({"type": {"item": "work_item", "entry": "journal_entry"}.get(kind, kind),
                         "id": rest})
    if isinstance(value, Mapping):
        return _subject(value)
    raise PackError("subject must be a string or an object, got %s" % type(value).__name__)


def _subject(m: Mapping) -> Subject:
    kind = m.get("type") or m.get("kind")
    if kind not in SUBJECT_KINDS:
        raise PackError("subject type must be one of %s" % ", ".join(SUBJECT_KINDS))
    if kind == "lease_period":
        lease_id, period = m.get("lease_id"), m.get("period")
        if not isinstance(lease_id, str) or not lease_id.strip() or len(lease_id) > 200:
            raise PackError("a lease_period subject needs lease_id")
        return Subject(kind, lease_id=lease_id.strip(), period=_period(period))
    try:
        ident = int(str(m.get("id")))
    except (TypeError, ValueError):
        raise PackError("a %s subject needs a numeric id" % kind) from None
    if ident < 1 or ident > 2 ** 62:
        raise PackError("a %s id must be positive" % kind)
    return Subject(kind, id=str(ident))


def _period(value: Any) -> date:
    s = str(value or "")
    if re.fullmatch(r"\d{4}-\d{2}", s):
        s += "-01"
    try:
        d = date.fromisoformat(s)
    except ValueError:
        raise PackError("period must be YYYY-MM or YYYY-MM-01, got %r" % (value,)) from None
    if d.day != 1:
        raise PackError("period must be the first of a month, got %s" % d)
    return d


# ---------------------------------------------------------------- gather

def build_pack(conn: Connection, subject: Any, *, storage=None, data_dir: Optional[Path] = None,
               requested_by: Optional[str] = None, visible: Optional[Callable[[Mapping], bool]] = None,
               now: Optional[datetime] = None) -> Pack:
    """Gather the record for `subject` on `conn` (read-only) and render the PDF."""
    subject = subject if isinstance(subject, Subject) else parse_subject(subject)
    items, entries = _items_for(conn, subject)
    if visible is not None:
        if any(not visible(i) for i in items):
            raise PackNotFound("no %s" % subject.label)
    sections = [_item_section(conn, item, storage, data_dir) for item in items]
    covered = {e["seq"]: e for s in sections for e in s["events"]}
    seen_entries = {e["id"] for s in sections for e in s["entries"]}
    loose = [e for e in entries if e["id"] not in seen_entries]

    refs = sorted({e["policy_ref"] for e in covered.values() if e.get("policy_ref")})
    policies = [dict(p, ref=ref) for ref in refs
                for p in decisions_by_policy(conn, ref) if p.get("kind") == "policy"]
    for ref in refs:
        if not any(p["ref"] == ref for p in policies):
            policies.append({"ref": ref, "name": ref, "version": None, "status": "not on file"})

    broken = verify_chain(conn)
    head = conn.execute(text(
        "SELECT seq, hash FROM audit_event ORDER BY seq DESC LIMIT 1")).first()
    last = covered[max(covered)] if covered else None
    stamp = {
        "chain_verified": broken is None,
        "broken_seq": broken.seq if broken else None,
        "problem": broken.problem if broken else None,
        "last_event_seq": last["seq"] if last else None,
        "last_event_hash": last["hash"] if last else None,
        "head_seq": head.seq if head else None,
        "head_hash": (head.hash or "").strip() if head else None,
        "events_covered": len(covered),
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "generated_as": conn.execute(text("SELECT current_user")).scalar_one(),
        "requested_by": requested_by,
    }
    summary = {
        "subject": subject.label,
        "items": [{"id": s["item"]["id"], "state": s["item"]["state"], "title": s["item"]["title"],
                   "calc": s["calc"]} for s in sections],
        "policies": [{"ref": p["ref"], "name": p.get("name"), "version": p.get("version")}
                     for p in policies],
        "approvals": [_short(e) for s in sections for e in s["events"]
                      if e["allowed"] and e["action"] in ("approve", "reject", "post")],
        "denials": [_short(e) for s in sections for e in s["events"] if not e["allowed"]],
        "stamp": stamp,
    }
    pdf = _render(subject, sections, loose, policies, stamp)
    return Pack(pdf=pdf, summary=summary)


def _items_for(conn: Connection, subject: Subject):
    if subject.kind == "work_item":
        row = conn.execute(text("SELECT * FROM work_item WHERE id = :id"),
                           {"id": int(subject.id)}).mappings().first()
        if row is None:
            raise PackNotFound("no work item %s" % subject.id)
        return [dict(row)], []
    if subject.kind == "journal_entry":
        entry = conn.execute(text("SELECT id, work_item_id FROM journal_entry WHERE id = :id"),
                             {"id": int(subject.id)}).first()
        if entry is None:
            raise PackNotFound("no journal entry %s" % subject.id)
        entries = _entries(conn, "e.id = :id", {"id": entry.id})
        if entry.work_item_id is None:
            return [], entries
        row = conn.execute(text("SELECT * FROM work_item WHERE id = :id"),
                           {"id": entry.work_item_id}).mappings().one()
        return [dict(row)], entries
    if conn.execute(text("SELECT 1 FROM lease WHERE id = :l"), {"l": subject.lease_id}).first() is None:
        raise PackNotFound("no lease %s" % subject.lease_id)
    rows = conn.execute(text("""
        SELECT w.* FROM work_item w
         WHERE w.kind = 'CHARGE_CHECK' AND w.period = :p
           AND (w.evidence ->> 'lease_id' = :l
                OR (w.subject_type = 'landlord_charge' AND w.subject_id IN (
                        SELECT id FROM landlord_charge WHERE lease_id = :l)))
         ORDER BY w.id
    """), {"l": subject.lease_id, "p": subject.period}).mappings().all()
    return [dict(r) for r in rows], []


def _item_section(conn: Connection, item: Mapping, storage, data_dir) -> Dict[str, Any]:
    from ..api import evidence as ev  # lazy: app.api imports this module's router

    evidence = item.get("evidence") if isinstance(item.get("evidence"), Mapping) else {}
    events = timeline_for(conn, "work_item", item["id"])
    # The lease version the checker read, and who confirmed it.
    version_id = evidence.get("lease_version_id")
    if version_id is not None:
        for w in conn.execute(text("""
            SELECT id FROM work_item WHERE subject_type = 'lease_version' AND subject_id = :v
        """), {"v": str(version_id)}).scalars():
            events += timeline_for(conn, "work_item", w)
        events += timeline_for(conn, "lease_version", version_id)
    events.sort(key=lambda e: e["seq"])

    charge = None
    if item.get("kind") == "CHARGE_CHECK":
        charge = ev.document_for_charge(conn, evidence.get("charge_id") or item.get("subject_id"))
    lease_id = evidence.get("lease_id")
    proof = evidence.get("proof") if isinstance(evidence.get("proof"), Mapping) else None
    sha = ev.lease_sha(Path(data_dir), lease_id) if data_dir and lease_id else None
    citation = invoice = None
    try:
        citation = ev.lease_citation(storage, sha, lease_id, dict(proof)) if proof else None
        invoice = ev.invoice_line(storage, charge) if charge else None
    except Exception:  # noqa: BLE001 — a missing or unreadable PDF leaves the box out, never the pack
        citation = invoice = None
    sources = sources_for(conn, item)
    for src in sources:          # the page the pipeline found, where the record has none
        located = citation if src.get("source") == "lease_version" else (
            invoice if src.get("source") == "landlord_invoice" else None)
        if located and not src.get("page"):
            src["page"] = located.get("page")
    return {
        "item": dict(item),
        "evidence": evidence,
        "proof": proof,
        "charge": charge,
        "citation": citation,
        "citation_image": _boxed_image(storage, citation),
        "invoice": invoice,
        "invoice_image": _boxed_image(storage, invoice),
        "sources": sources,
        "calc": _calc(item, evidence, charge),
        "events": events,
        "entries": _entries(conn, "e.work_item_id = :w", {"w": item["id"]}),
    }


def _calc(item: Mapping, evidence: Mapping, charge: Optional[Mapping]) -> Dict[str, Optional[str]]:
    billed = _dec(evidence.get("billed"))
    if billed is None:
        billed = _dec(item.get("amount")) if item.get("amount") is not None else (
            _dec(charge.get("amount")) if charge else None)
    if billed is None:
        return {"billed": None, "supported": None, "disputed": None, "payable": None,
                "resolution": None, "basis": None}
    held = item.get("proposal") == "hold"
    supported = _dec(evidence.get("supported"))
    if supported is None:
        supported = billed if not held else Decimal("0.00")
    disputed = max(billed - supported, Decimal("0.00")) if held else Decimal("0.00")
    approved = item.get("state") in ("APPROVED", "POSTED", "CLOSED")
    pay = payable(item, billed) if approved and item.get("kind") == "CHARGE_CHECK" else None
    return {"billed": str(billed), "supported": str(supported), "disputed": str(disputed),
            "payable": str(pay.amount) if pay else None,
            "resolution": evidence.get("resolution"), "basis": pay.basis if pay else None}


def _entries(conn: Connection, where: str, params: Mapping) -> List[Dict[str, Any]]:
    rows = conn.execute(text("""
        SELECT e.id, e.date, e.period, e.memo, e.entry_type, e.work_item_id,
               a.code, a.name AS account, l.debit, l.credit, l.clinic_id
          FROM journal_entry e
          JOIN journal_line l ON l.journal_entry_id = e.id
          JOIN account a ON a.id = l.account_id
         WHERE %s ORDER BY e.id, l.id
    """ % where), dict(params)).mappings().all()
    out: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        e = out.setdefault(r["id"], {k: r[k] for k in ("id", "date", "period", "memo",
                                                       "entry_type", "work_item_id")} | {"lines": []})
        e["lines"].append({"code": r["code"], "account": r["account"], "debit": r["debit"],
                           "credit": r["credit"], "clinic_id": r["clinic_id"]})
    return list(out.values())


def _boxed_image(storage, located: Optional[Mapping]) -> Optional[bytes]:
    """The cited page as PNG, cropped around the box, with the box drawn."""
    if storage is None or not located or not located.get("doc_id") or not located.get("box"):
        return None
    try:
        import pymupdf

        with pymupdf.open(stream=storage.get(located["doc_id"]), filetype="pdf") as doc:
            page = doc[int(located["page"]) - 1]
            x0, y0, x1, y1 = (float(v) for v in located["box"])
            page.draw_rect(pymupdf.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2), color=(0.85, 0.1, 0.1),
                           width=1.6)
            r = page.rect
            clip = pymupdf.Rect(r.x0, max(r.y0, y0 - 110), r.x1, min(r.y1, y1 + 110))
            return page.get_pixmap(dpi=IMAGE_DPI, clip=clip).tobytes("png")
    except Exception:  # noqa: BLE001 — no image is better than a wrong one
        return None


# ----------------------------------------------------------------- render

def _render(subject: Subject, sections: List[Dict], loose: List[Dict], policies: List[Dict],
            stamp: Mapping) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=9.5)
    quote = ParagraphStyle("quote", parent=body, leftIndent=12, textColor=colors.HexColor("#333333"),
                           fontName="Helvetica-Oblique")
    h1, h2, h3 = styles["Title"], styles["Heading2"], styles["Heading3"]
    width = letter[0] - 1.5 * inch

    def p(s, style=body):
        return Paragraph(s, style)

    def grid(rows, widths, header=True):
        t = Table([[p(_esc(c), small) if not isinstance(c, Paragraph) else c for c in r]
                   for r in rows], colWidths=widths, repeatRows=1 if header else 0)
        style = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
                 ("VALIGN", (0, 0), (-1, -1), "TOP")]
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")))
        t.setStyle(TableStyle(style))
        return t

    def image(png):
        img = Image(io.BytesIO(png))
        scale = min(width / img.imageWidth, 3.2 * inch / img.imageHeight)
        img.drawWidth, img.drawHeight = img.imageWidth * scale, img.imageHeight * scale
        return img

    story = [p("Evidence pack", h1),
             p("<b>Subject:</b> %s" % _esc(subject.label)),
             p("<b>Generated:</b> %s as database role <b>%s</b>%s" % (
                 _esc(stamp["generated_at"]), _esc(stamp["generated_as"]),
                 " for %s" % _esc(stamp["requested_by"]) if stamp.get("requested_by") else "")),
             Spacer(1, 6), _stamp_table(stamp, p, colors, Table, TableStyle, width), Spacer(1, 10)]

    if not sections and not loose:
        story.append(p("No work items are on record for this subject."))

    for s in sections:
        item, calc = s["item"], s["calc"]
        story += [p("Work item %s: %s" % (item["id"], _esc(item["title"])), h2),
                  p("Kind %s, state <b>%s</b>, proposal %s, clinic %s, period %s." % (
                      _esc(item["kind"]), _esc(item["state"]), _esc(item.get("proposal") or "none"),
                      _esc(item.get("clinic_id") or "-"), _esc(item.get("period") or "-")))]
        if item.get("reason"):
            story.append(p("<b>Reason on record:</b> %s" % _esc(item["reason"])))

        story.append(p("Lease clause cited", h3))
        proof, cite = s["proof"], s["citation"]
        if proof and proof.get("quote"):
            page = (cite or {}).get("page") or proof.get("page")
            story += [p("Lease %s, section %s, page %s%s" % (
                          _esc(s["evidence"].get("lease_id")), _esc(proof.get("section") or "-"),
                          _esc(page or "-"),
                          ", box [%s] in PDF points" % ", ".join("%.1f" % v for v in cite["box"])
                          if cite and cite.get("box") else ", box not located")),
                      p("“%s”" % _esc(proof["quote"]), quote)]
            if s["citation_image"]:
                story.append(image(s["citation_image"]))
        else:
            story.append(p("No lease clause was cited for this item."))

        story.append(p("Invoice line", h3))
        charge = s["charge"]
        if charge:
            inv = s["invoice"]
            story.append(grid([["Invoice", "Description", "Amount", "Page", "Box"],
                               [s["evidence"].get("invoice_id") or charge.get("invoice_id"),
                                charge.get("description"), _money(charge.get("amount")),
                                (inv or {}).get("page") or charge.get("page") or "-",
                                ", ".join("%.1f" % v for v in inv["box"]) if inv else "not located"]],
                              [1.3 * inch, 2.3 * inch, 1.0 * inch, 0.5 * inch, width - 5.1 * inch]))
            if s["invoice_image"]:
                story += [Spacer(1, 4), image(s["invoice_image"])]
        else:
            story.append(p("This item is not about an invoice line."))

        story.append(p("Calculation", h3))
        story.append(grid([["Billed", "Supported by the lease", "Disputed", "Payable", "Resolution"],
                           [_money(calc["billed"]), _money(calc["supported"]),
                            _money(calc["disputed"]), _money(calc["payable"]),
                            "%s%s" % (calc["resolution"] or "-",
                                      " (%s)" % calc["basis"] if calc["basis"] else "")]],
                          [width / 5] * 5))
        if s["evidence"].get("rule"):
            story.append(p("Rule applied: %s" % _esc(s["evidence"]["rule"]), small))

        if s["sources"]:
            story.append(p("Sources weighed", h3))
            story.append(grid([["Rank", "Source", "Claims", "Citation"]] + [
                [src.get("rank") or src.get("trust_rank") or "-",
                 src.get("rank_name") or src.get("source"),
                 _money(src.get("claims")) if src.get("claims") is not None else
                 src.get("value") or src.get("claim") or "-",
                 _source_cite(src)] for src in s["sources"]],
                [0.5 * inch, 2.3 * inch, 1.0 * inch, width - 3.8 * inch]))

        story.append(p("Approvals and denials on record", h3))
        story.append(grid([["Seq", "When (UTC)", "Actor", "Action", "Allowed", "Reason"]] + [
            [e["seq"], str(e["at"])[:19].replace("T", " "),
             "%s%s" % (e["actor_id"], " (%s)" % e["actor_name"] if e.get("actor_name") else ""),
             "%s %s%s" % (e["subject_type"].replace("_", " "), e["subject_id"],
                          ": %s" % _action(e)),
             "yes" if e["allowed"] else "DENIED", e.get("reason") or ""] for e in s["events"]],
            [0.4 * inch, 1.1 * inch, 1.5 * inch, 1.5 * inch, 0.7 * inch, width - 5.2 * inch]))

        if s["entries"]:
            story.append(p("Journal entries posted", h3))
            story += [_entry_table(e, grid, width) for e in s["entries"]]

    for e in loose:
        story += [p("Journal entry %s" % e["id"], h2), _entry_table(e, grid, width)]

    story.append(p("Policy versions cited", h3))
    if policies:
        story.append(grid([["Ref", "Policy", "Version", "Status", "Effective"]] + [
            [pol["ref"], pol.get("name"), pol.get("version") or "-", pol.get("status"),
             "%s to %s" % (pol.get("effective_from") or "-", pol.get("effective_to") or "open")]
            for pol in policies], [1.4 * inch, 2.0 * inch, 0.7 * inch, 0.9 * inch,
                                   width - 5.0 * inch]))
    else:
        story.append(p("No policy was cited by any decision in this pack."))

    story += [Spacer(1, 10), KeepTogether([p("Chain verification", h3),
                                           _stamp_table(stamp, p, colors, Table, TableStyle, width)])]

    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            title="Evidence pack: %s" % subject.label, author="Lease Desk",
                            subject="Evidence pack", creator="Lease Desk evidence_pack")
    doc.build(story)
    return out.getvalue()


def _stamp_table(stamp, p, colors, Table, TableStyle, width):
    if stamp["chain_verified"]:
        verdict = "<b>CHAIN VERIFIED</b>: verify_chain() found no broken link (Chain verified)."
        shade = colors.HexColor("#e3f4e6")
    else:
        verdict = ("<b>CHAIN BROKEN at seq %s</b>: %s. Do not rely on events from seq %s on."
                   % (stamp["broken_seq"], _esc(stamp["problem"]), stamp["broken_seq"]))
        shade = colors.HexColor("#fbe3e3")
    rows = [[p(verdict)],
            [p("Last event covered: seq %s, hash %s" % (stamp["last_event_seq"] or "-",
                                                          stamp["last_event_hash"] or "-"))],
            [p("Chain head: seq %s, hash %s. %s events covered." % (
                stamp["head_seq"] or "-", stamp["head_hash"] or "-", stamp["events_covered"]))],
            [p("Generated at %s as %s." % (_esc(stamp["generated_at"]), _esc(stamp["generated_as"])))]]
    t = Table(rows, colWidths=[width])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), shade),
                           ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#888888"))]))
    return t


def _entry_table(e, grid, width):
    from reportlab.lib.units import inch

    rows = [["Entry %s, %s" % (e["id"], e["date"]), "Account", "Debit", "Credit"]]
    rows += [[e["memo"] if i == 0 else "", "%s %s" % (line["code"], line["account"]),
              _money(line["debit"]) if line["debit"] else "", _money(line["credit"])
              if line["credit"] else ""] for i, line in enumerate(e["lines"])]
    return grid(rows, [2.4 * inch, width - 4.4 * inch, 1.0 * inch, 1.0 * inch])


# ---------------------------------------------------------------- helpers

def _action(e: Mapping) -> str:
    ev = e.get("evidence") or {}
    a = e["action"]
    if a == "approve" and ev.get("resolution"):
        return "approve (%s)" % ev["resolution"]
    if a == "propose":
        return "propose %s" % (((e.get("diff") or {}).get("set") or {}).get("proposal") or "")
    return a


def _source_cite(s: Mapping) -> str:
    if s.get("source") == "lease_version":
        return "lease %s v%s, section %s, p.%s, confirmed by %s" % (
            s.get("lease_id"), s.get("version"), s.get("section") or "-", s.get("page") or "-",
            s.get("confirmed_by") or "nobody")
    if s.get("source") == "landlord_invoice":
        return "invoice %s, p.%s: %s" % (s.get("invoice_id"), s.get("page") or "-",
                                         s.get("description") or "")
    c = s.get("citation")
    return str(c) if c is not None else "-"


def _short(e: Mapping) -> Dict[str, Any]:
    return {"seq": e["seq"], "at": e["at"], "actor_id": e["actor_id"], "action": e["action"],
            "allowed": e["allowed"], "reason": e.get("reason"),
            "resolution": (e.get("evidence") or {}).get("resolution")}


def _dec(v: Any) -> Optional[Decimal]:
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
    return d.quantize(Decimal("0.01")) if d.is_finite() else None


def _money(v: Any) -> str:
    d = _dec(v)
    return "-" if d is None else ("-$%s" % "{:,.2f}".format(-d) if d < 0 else "${:,.2f}".format(d))


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=False)
