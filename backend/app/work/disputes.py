"""Disputes and landlord correspondence (PHASE_2.md group 11).

The arc, and who moves each step:

  1. draft     A hold a person upheld (work/charges.py, resolution `upheld`)
               with a disputed amount becomes a dispute. agent:disputes, as
               lease_agent, builds the letter from structured facts only (the
               checker's finding, the lease clause with its section, page and
               quote, the math, the invoices), addressed to the landlord's
               notice address and authorized representative (lease Article
               12), writes the dispute row and opens a DISPUTE work item
               (subject_type 'dispute') proposing `send_letter`. No model is
               involved: every sentence is a template over facts on record.
  2. approve   The clinic's regional manager approves the letter: an ordinary
               transition, region-scoped by can(); a controller may too.
  3. send      The gateway (gateway.send_dispute_letter) puts the letter in
               the outbox as an `email` row under the key
               dispute_letter:<id>:<round>, so sending twice sends once, and
               marks the dispute `sent`. send_outbox() writes the .eml.
  4. recognise Once the letter is out, agent:disputes proposes a
               DISPUTE_RECEIVABLE item. Only a controller may approve it
               (approve_receivable; the gateway checks the approval on
               record again before posting).
  5. reply     The landlord's answer is recorded (record_reply, on lease_api):
               acknowledged, credited, partially credited or refused. An AP
               clerk records acknowledgements and full credit memos; a
               partial credit or a refusal changes what we expect to recover,
               so only a controller records those, and doing so reopens the
               DISPUTE item to the regional manager: APPROVED -> HELD with the
               landlord's reason as the item's reason.
  6. settle    The gateway clears the receivable by each credit memo and
               closes the items when fully credited. On a reopened item the
               regional manager either resumes it (pursue: approving it again
               sends a follow-up letter, round 2) or rejects it (concede); a
               conceded dispute is written off only when a controller closes
               it.

The accounting (and why it is conservative)
-------------------------------------------
An upheld hold never reached the books: the gateway posted only the
supported amount, so the disputed dollars are in neither expense nor AP.
Recognising the receivable is therefore a gross-up, never income:

  recognise (controller-approved)   Dr Landlord receivable / Cr Accounts payable
                                    for the disputed amount. AP now agrees with
                                    the landlord's statement (they say we owe
                                    it) and the receivable is our claim against
                                    it. No P&L effect: no gain contingency is
                                    recognised (ASC 450-30), and operating lease
                                    cost stays what the lease supports (ASC 842
                                    single lease cost is unaffected by a billing
                                    error). Not offset while the right of setoff
                                    is unestablished.
  credit memo                       Dr Accounts payable / Cr Landlord receivable
                                    for the amount credited: the landlord drops
                                    that much of the claim.
  concede (controller closes)       the uncredited remainder becomes cost:
                                    Dr Lease cost (or CAM expense) /
                                    Cr Landlord receivable when the receivable
                                    was recognised, else Cr Accounts payable.

A receivable is recognised only while the dispute is `sent` or
`acknowledged`; once the landlord has refused (all or part), recovery is no
longer probable and recognition is refused.

Statuses: drafted -> sent -> acknowledged -> credited | partially_credited |
refused; a reopened dispute that is pursued goes back to sent. Every change
is an audit_event with subject_type 'dispute' (the status history).
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .events import append_event, events_for
from .roles import Actor, load_actor
from .transitions import Denied, load_item, record_denial, transition

DRAFTER = "agent:disputes"
DISPUTE = "DISPUTE"
RECEIVABLE = "DISPUTE_RECEIVABLE"
SUBJECT = "dispute"

DRAFTED, SENT, ACKNOWLEDGED = "drafted", "sent", "acknowledged"
CREDITED, PARTIAL, REFUSED = "credited", "partially_credited", "refused"
STATUSES = (DRAFTED, SENT, ACKNOWLEDGED, CREDITED, PARTIAL, REFUSED)

# Landlord reply outcomes. The datagen/replies.py names are accepted as-is.
OUT_ACK, OUT_QUERIED = "acknowledged", "queried"
OUT_FULL, OUT_PARTIAL, OUT_REFUSED = "full_credit", "partial_credit", "refused"
OUTCOMES = (OUT_ACK, OUT_QUERIED, OUT_FULL, OUT_PARTIAL, OUT_REFUSED)
STATUS_FOR = {OUT_ACK: ACKNOWLEDGED, OUT_QUERIED: ACKNOWLEDGED, OUT_FULL: CREDITED,
              OUT_PARTIAL: PARTIAL, OUT_REFUSED: REFUSED}
# Who may record which reply. Anyone else is refused, on record.
RECORDERS = {"ap_clerk": {OUT_ACK, OUT_QUERIED, OUT_FULL},
             "controller": set(OUTCOMES)}
REPLY_FROM = (SENT, ACKNOWLEDGED)
RECOGNISABLE = (SENT, ACKNOWLEDGED)
REOPENS = (OUT_PARTIAL, OUT_REFUSED)
RECOGNISER = "controller"
LETTER_APPROVERS = ("regional_manager", "controller")

LANDLORD_RECEIVABLE = "Landlord receivable"
ACCOUNTS_PAYABLE = "Accounts payable"
EXPENSE_FOR = {"base_rent": "Lease cost", "cam_estimate": "CAM expense"}
DEFAULT_EXPENSE = "Lease cost"

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
REPLY_DAYS = 30

# What each checker rule is called in a letter.
RULE_TITLES = {
    "duplicate": "a duplicate billing",
    "premises": "rent for premises the Lease does not demise",
    "amount": "base rent above the Lease's rent schedule",
    "operating_expense": "an operating expense estimate above the Lease's estimate",
}


class DisputeError(ValueError):
    """The request does not fit the dispute as it stands. Nothing was written."""


class DisputeStateError(DisputeError):
    """The dispute is not in a status that allows this. Nothing was written."""


class UnknownDispute(LookupError):
    """No dispute has this id."""


class ReplyRefused(Denied):
    """This actor may not record this reply. The refusal is on record."""


class RecognitionRefused(Denied):
    """Only a controller recognises a landlord receivable. On record."""


def dispute_id_for(charge_item_id: int) -> str:
    return "DSP-%06d" % int(charge_item_id)


def expense_account(charge_type: Optional[str]) -> str:
    return EXPENSE_FOR.get(charge_type or "", DEFAULT_EXPENSE)


# ------------------------------------------------------------------ drafting

def upheld_holds(conn: Connection, entity_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Charge checks whose hold a person upheld with something disputed, and
    no dispute yet. An override (pay_as_billed) disputes nothing."""
    rows = conn.execute(text("""
        SELECT w.* FROM work_item w
         WHERE w.kind = 'CHARGE_CHECK' AND w.subject_type = 'landlord_charge'
           AND w.proposal = 'hold' AND w.state IN ('APPROVED', 'POSTED', 'CLOSED')
           AND w.evidence->>'resolution' = 'upheld'
           AND (CAST(:e AS text) IS NULL OR w.entity_id = :e)
           AND NOT EXISTS (SELECT 1 FROM dispute d WHERE d.charge_item_id = w.id)
         ORDER BY w.id
    """), {"e": entity_id}).mappings().all()
    return [dict(r) for r in rows if _disputed(r) > 0]


def draft_disputes(conn: Connection, entity_id: Optional[str] = None,
                   on: Optional[date] = None) -> Dict[str, Any]:
    """The disputes agent's sweep (the `disputes` job, as lease_agent):
    draft a letter for every upheld hold without one, and propose
    recognising the receivable for every dispute whose letter is out.
    Idempotent: a second run drafts and proposes nothing."""
    drafted = [draft_dispute(conn, row["id"], on=on)["id"] for row in upheld_holds(conn, entity_id)]
    proposed = propose_receivables(conn, entity_id)
    return {"drafted": drafted, "receivables_proposed": proposed}


def draft_dispute(conn: Connection, charge_item_id: int, *,
                  on: Optional[date] = None) -> Dict[str, Any]:
    """Draft the dispute for one upheld hold and return the dispute row.
    Returns the existing row if it was drafted already."""
    existing = conn.execute(text("SELECT * FROM dispute WHERE charge_item_id = :i"),
                            {"i": charge_item_id}).mappings().first()
    if existing is not None:
        return dict(existing)
    charge_item = load_item(conn, charge_item_id)
    evidence = charge_item.get("evidence") or {}
    if (charge_item["kind"] != "CHARGE_CHECK" or charge_item.get("proposal") != "hold"
            or evidence.get("resolution") != "upheld"):
        raise DisputeError("work item %s is not an upheld hold on a landlord charge"
                           % charge_item_id)
    if charge_item["state"] not in ("APPROVED", "POSTED", "CLOSED"):
        raise DisputeError("work item %s is %s; only an approved hold is disputed"
                           % (charge_item_id, charge_item["state"]))
    disputed = _disputed(charge_item)
    if disputed <= 0:
        raise DisputeError("work item %s disputes nothing" % charge_item_id)

    drafter = load_actor(conn, DRAFTER)
    facts = gather_facts(conn, charge_item, on=on)
    letter = render_letter(facts)
    dispute_id = facts["dispute_id"]
    m = facts["math"]
    item = _create_and_propose(
        conn, drafter, kind=DISPUTE, dispute_id=dispute_id, charge_item=charge_item,
        title="Dispute letter to %s: %s, $%s" % (facts["landlord"]["name"],
                                               facts["charge"]["invoice_id"], _fmt(disputed)),
        amount=disputed, proposal="send_letter",
        reason="Draft letter disputing $%s of invoice %s (%s), for the regional manager to "
               "approve" % (_fmt(disputed), facts["charge"]["invoice_id"], facts["rule_title"]),
        evidence={"dispute_id": dispute_id, "charge_item_id": charge_item["id"],
                  "letter": letter, "notice_to": facts["landlord"], "math": m,
                  "lease": facts["lease"], "documents": facts["documents"]})
    conn.execute(text("""
        INSERT INTO dispute (id, work_item_id, charge_item_id, charge_id, landlord_id, lease_id,
                             clinic_id, entity_id, region_id, period, charge_type, billed,
                             supported, amount, status, notice_to, letter, facts)
        VALUES (:id, :item, :charge_item, :charge, :landlord, :lease, :clinic, :entity, :region,
                :period, :ctype, :billed, :supported, :amount, 'drafted',
                CAST(:notice AS jsonb), :letter, CAST(:facts AS jsonb))
    """), {"id": dispute_id, "item": item["id"], "charge_item": charge_item["id"],
           "charge": facts["charge"]["charge_id"], "landlord": facts["landlord"]["landlord_id"],
           "lease": facts["lease"]["lease_id"], "clinic": facts["charge"]["clinic_id"],
           "entity": charge_item["entity_id"] or facts["entity_id"],
           "region": charge_item["region_id"], "period": facts["charge"]["period"],
           "ctype": facts["charge"]["charge_type"], "billed": m["billed"],
           "supported": m["supported"], "amount": m["disputed"],
           "notice": _json(facts["landlord"]), "letter": letter, "facts": _json(facts)})
    append_event(conn, actor_id=drafter.id, action="draft", subject_type=SUBJECT,
                 subject_id=dispute_id, diff={"from": None, "to": DRAFTED},
                 evidence={"work_item_id": item["id"], "charge_item_id": charge_item["id"],
                           "amount": m["disputed"]})
    return load_dispute(conn, dispute_id)


def propose_receivables(conn: Connection, entity_id: Optional[str] = None) -> List[str]:
    """Open a DISPUTE_RECEIVABLE item, proposed `recognize`, for each dispute
    whose letter is out (sent or acknowledged) and has none yet."""
    rows = conn.execute(text("""
        SELECT d.* FROM dispute d
         WHERE d.status IN ('sent', 'acknowledged')
           AND (CAST(:e AS text) IS NULL OR d.entity_id = :e)
           AND NOT EXISTS (SELECT 1 FROM work_item w WHERE w.kind = :kind
                            AND w.subject_type = :st AND w.subject_id = d.id)
         ORDER BY d.id
    """), {"e": entity_id, "kind": RECEIVABLE, "st": SUBJECT}).mappings().all()
    if not rows:
        return []
    drafter = load_actor(conn, DRAFTER)
    out = []
    for d in rows:
        charge_item = load_item(conn, d["charge_item_id"])
        _create_and_propose(
            conn, drafter, kind=RECEIVABLE, dispute_id=d["id"], charge_item=charge_item,
            title="Recognise landlord receivable: %s, $%s" % (d["id"], _fmt(d["amount"])),
            amount=d["amount"], proposal="recognize",
            reason="The dispute letter is out. Recognising the claim grosses up AP to the "
                   "landlord's statement and books our claim against it; no P&L effect.",
            evidence={"dispute_id": d["id"], "amount": str(d["amount"]),
                      "entry": [{"account": LANDLORD_RECEIVABLE, "debit": str(d["amount"])},
                                {"account": ACCOUNTS_PAYABLE, "credit": str(d["amount"])}],
                      "basis": "ASC 450-30: no gain recognised; ASC 842 lease cost unchanged"})
        out.append(d["id"])
    return out


def _create_and_propose(conn: Connection, drafter: Actor, *, kind: str, dispute_id: str,
                        charge_item: Mapping, title: str, amount: Any, proposal: str,
                        reason: str, evidence: Mapping) -> Dict[str, Any]:
    from .transitions import create_item

    item = create_item(conn, drafter, kind=kind, subject_type=SUBJECT, subject_id=dispute_id,
                       title=title, entity_id=charge_item["entity_id"],
                       region_id=charge_item["region_id"], clinic_id=charge_item["clinic_id"],
                       period=charge_item["period"], amount=amount,
                       evidence={"dispute_id": dispute_id})
    if item["state"] == "NEW":
        item = transition(conn, drafter, item["id"], "propose", reason=reason,
                          patch={"proposal": proposal, "evidence": dict(evidence)})
    return item


# --------------------------------------------------------------------- facts

def gather_facts(conn: Connection, charge_item: Mapping, *, on: Optional[date] = None) -> Dict:
    """Everything the letter says, as structured data from rows on record:
    the charge, the landlord's notice block, the tenant, the lease clause
    (section, page, quote), the math and the evidence documents."""
    from ..jobs import clock

    evidence = charge_item.get("evidence") or {}
    charge = conn.execute(text("""
        SELECT c.id, c.invoice_id, c.lease_id, c.clinic_id, c.period, c.charge_type,
               c.description, c.suite, c.amount, c.document_id,
               k.name AS clinic_name, k.suite AS clinic_suite, k.entity_id,
               n.address AS center_address, l.landlord_id
          FROM landlord_charge c
          JOIN clinic k ON k.id = c.clinic_id
          JOIN center n ON n.id = k.center_id
          JOIN lease l ON l.id = c.lease_id
         WHERE c.id = :id
    """), {"id": charge_item["subject_id"]}).mappings().first()
    if charge is None:
        raise DisputeError("work item %s has no landlord charge %s"
                           % (charge_item["id"], charge_item["subject_id"]))
    landlord = conn.execute(text("""
        SELECT id, name, notice_address, authorized_rep, authorized_rep_email
          FROM landlord WHERE id = :id
    """), {"id": charge["landlord_id"]}).mappings().one()
    entity = conn.execute(text("SELECT id, name FROM entity WHERE id = :id"),
                          {"id": charge["entity_id"]}).mappings().one()
    signer = conn.execute(text("""
        SELECT id, name, email FROM actor
         WHERE role = 'controller' AND active AND (entity_id IS NULL OR entity_id = :e)
         ORDER BY entity_id NULLS LAST, id LIMIT 1
    """), {"e": charge["entity_id"]}).mappings().first()
    if not landlord["notice_address"] or not landlord["authorized_rep_email"]:
        raise DisputeError("landlord %s has no notice address or authorized representative "
                           "email on record; the lease's notices clause is required"
                           % landlord["id"])

    billed = _money(evidence.get("billed", charge["amount"])) or _money(charge["amount"])
    disputed = _disputed(charge_item)
    supported = billed - disputed
    dispute_id = dispute_id_for(charge_item["id"])
    letter_date = on or clock.today(conn)

    documents = [{"kind": "invoice", "role": "the disputed charge",
                  "invoice_id": charge["invoice_id"], "charge_id": charge["id"],
                  "document_id": charge["document_id"], "amount": str(_money(charge["amount"]))}]
    related_ids = [r for r in evidence.get("related") or [] if r != charge["id"]]
    if related_ids:
        for r in conn.execute(text("""
            SELECT id, invoice_id, document_id, amount, charge_type, period FROM landlord_charge
             WHERE id = ANY(:ids) ORDER BY invoice_id, id
        """), {"ids": related_ids}).mappings():
            documents.append({"kind": "invoice", "role": "the charge already billed for the "
                              "same period", "invoice_id": r["invoice_id"], "charge_id": r["id"],
                              "document_id": r["document_id"], "amount": str(_money(r["amount"]))})
    lease = _lease_citation(conn, charge["lease_id"], evidence)
    documents.append({"kind": "lease", "role": "the Lease", "lease_id": charge["lease_id"],
                      "document_id": lease.get("document_id"), "section": lease.get("section"),
                      "page": lease.get("page")})

    rule = evidence.get("rule") or ""
    return {
        "dispute_id": dispute_id,
        "charge_item_id": charge_item["id"],
        "entity_id": charge["entity_id"],
        "rule": rule,
        "rule_title": RULE_TITLES.get(rule, "a charge the Lease does not support"),
        "finding": charge_item.get("reason") or "",
        "letter_date": letter_date.isoformat(),
        "reply_days": REPLY_DAYS,
        "charge": {"charge_id": charge["id"], "invoice_id": charge["invoice_id"],
                   "charge_ref": evidence.get("charge_ref"), "charge_type": charge["charge_type"],
                   "description": charge["description"], "suite": charge["suite"],
                   "period": charge["period"].isoformat(), "clinic_id": charge["clinic_id"]},
        "landlord": {"landlord_id": landlord["id"], "name": landlord["name"],
                     "attn": landlord["authorized_rep"],
                     "address": landlord["notice_address"],
                     "email": landlord["authorized_rep_email"]},
        "tenant": {"entity": entity["name"], "clinic": charge["clinic_name"],
                   "suite": charge["clinic_suite"], "address": charge["center_address"],
                   "signer": signer["name"] if signer else "Controller",
                   "signer_title": "Controller", "email": signer["email"] if signer else None},
        "lease": lease,
        "math": {"billed": str(billed), "supported": str(supported), "disputed": str(disputed)},
        "documents": documents,
    }


def _lease_citation(conn: Connection, lease_id: str, evidence: Mapping) -> Dict[str, Any]:
    """The clause the finding rests on: section and quote from the checker's
    proof; page and document from the confirmed lease_term that carries the
    same quote, else located in the lease PDF, else left unknown (never
    guessed)."""
    proof = evidence.get("proof") if isinstance(evidence.get("proof"), Mapping) else {}
    out = {"lease_id": lease_id, "lease_version_id": evidence.get("lease_version_id"),
           "section": proof.get("section"), "quote": proof.get("quote"),
           "page": proof.get("page"), "box": proof.get("box"), "document_id": None}
    term = None
    if out["quote"]:
        term = conn.execute(text("""
            SELECT t.page, t.bbox, t.document_id FROM lease_term t
              JOIN lease_version v ON v.id = t.lease_version_id
             WHERE v.lease_id = :lease AND t.quote = :quote AND t.page IS NOT NULL
             ORDER BY v.version DESC LIMIT 1
        """), {"lease": lease_id, "quote": out["quote"]}).mappings().first()
    if term is not None:
        out["page"] = out["page"] or term["page"]
        out["box"] = out["box"] or (list(term["bbox"]) if term["bbox"] else None)
        out["document_id"] = term["document_id"]
    if out["document_id"] is None:
        out["document_id"] = conn.execute(text("""
            SELECT t.document_id FROM lease_term t JOIN lease_version v ON v.id = t.lease_version_id
             WHERE v.lease_id = :lease AND t.document_id IS NOT NULL
             ORDER BY v.version DESC LIMIT 1
        """), {"lease": lease_id}).scalar()
    if out["page"] is None and out["quote"]:
        found = locate_in_lease(conn, lease_id, out["quote"])
        if found is not None:
            out["page"], out["box"] = found.page, list(found.box)
            out["document_id"] = out["document_id"] or found_document_id(lease_id)
    return out


def locate_in_lease(conn: Connection, lease_id: str, quote: str):
    """The quote's Citation in the stored lease PDF, or None when the PDF is
    not available or the quote is not on any page."""
    try:
        from ..docs.citations import locate
        from ..jobs.lease_versions import load_lease_document

        _doc_id, document = load_lease_document(conn, lease_id)
        return locate(document, quote) if document is not None else None
    except Exception:  # noqa: BLE001 - no store, unreadable PDF: the page stays unknown
        return None


def found_document_id(lease_id: str) -> str:
    from ..jobs.lease_versions import LEASE_SOURCE
    from ..records.ingest import stable_id

    return stable_id(LEASE_SOURCE, lease_id)


# -------------------------------------------------------------------- letter

def render_letter(facts: Mapping, *, round: int = 1, refusal: Optional[str] = None,
                  remaining: Optional[Any] = None, on: Optional[str] = None) -> str:
    """The letter, from facts alone. Round 2 and later is the follow-up sent
    after the landlord refused (all or part) and the regional manager chose
    to pursue it."""
    t, ll, c, m, lease = (facts["tenant"], facts["landlord"], facts["charge"], facts["math"],
                          facts["lease"])
    period = date.fromisoformat(c["period"])
    disputed = _money(remaining) if remaining is not None else _money(m["disputed"])
    where = "Section %s" % lease["section"] if lease.get("section") else "the Lease"
    page = (", page %d" % lease["page"]) if lease.get("page") else ""
    lines = [
        t["entity"],
        "%s, %s" % (t["clinic"], t["suite"]),
        t["address"] or "",
        "",
        _long(date.fromisoformat(on or facts["letter_date"])),
        "",
        "VIA EMAIL",
        ll["name"],
        "Attn: %s, Authorized Representative" % ll["attn"],
        ll["address"],
        ll["email"],
        "",
        "Re: %s - invoice %s, %s, %s" % (
            "Disputed charge" if round == 1 else "Disputed charge, follow-up %d" % (round - 1),
            c["invoice_id"], t["suite"], period.strftime("%B %Y")),
        "    Lease %s; our reference %s" % (lease["lease_id"], facts["dispute_id"]),
        "",
        "Dear %s:" % ll["attn"],
        "",
    ]
    if round > 1:
        lines += _wrap(
            "Thank you for your reply. We have considered it%s, and we maintain our dispute of "
            "$%s for the reasons below." % (
                " (\"%s\")" % _clip(refusal) if refusal else "", _fmt(disputed)))
        lines.append("")
    lines += _wrap(
        "In accordance with the notices provisions of the Lease, we dispute $%s of invoice %s "
        "(%s, %s), which we have identified as %s." % (
            _fmt(disputed), c["invoice_id"], c["charge_type"].replace("_", " "),
            period.strftime("%B %Y"), facts["rule_title"]))
    lines += ["", "What the Lease provides"]
    lines += _wrap('%s%s: "%s"' % (where, page, lease.get("quote") or "(see the Lease)"),
                   indent="    ")
    lines += ["", "What was billed"]
    lines += _wrap(facts["finding"], indent="    ")
    lines += ["", "The amounts",
              "    Billed                     $%s" % _fmt_col(m["billed"]),
              "    Supported by the Lease     $%s" % _fmt_col(m["supported"]),
              "    Disputed                   $%s" % _fmt_col(m["disputed"])]
    if remaining is not None and _money(remaining) != _money(m["disputed"]):
        lines.append("    Still in dispute           $%s" % _fmt_col(remaining))
    lines.append("")
    if _money(m["supported"]) > 0:
        lines += _wrap("We have approved the undisputed $%s for payment. The disputed amount is "
                       "held." % _fmt(m["supported"]))
    else:
        lines += _wrap("No part of this charge is supported by the Lease, and none of it will "
                       "be paid.")
    lines += ["", "Enclosed"]
    for n, d in enumerate(facts["documents"], 1):
        if d["kind"] == "invoice":
            lines.append("    %d. Invoice %s, $%s (%s)" % (n, d["invoice_id"], _fmt(d["amount"]),
                                                          d["role"]))
        else:
            lines.append("    %d. The Lease, %s%s" % (n, where, page))
    lines.append("")
    lines += _wrap("Please issue a credit memo for $%s against invoice %s, or reply in writing "
                   "with the basis for the charge, within %d days of this letter." % (
                       _fmt(disputed), c["invoice_id"], facts["reply_days"]))
    lines += ["", "Sincerely,", "", t["signer"], "%s, %s" % (t["signer_title"], t["entity"])]
    if t.get("email"):
        lines.append(t["email"])
    return "\n".join(lines) + "\n"


def letter_subject(facts: Mapping, round: int = 1) -> str:
    c, t = facts["charge"], facts["tenant"]
    period = date.fromisoformat(c["period"]).strftime("%B %Y")
    head = "Disputed charge" if round == 1 else "Disputed charge (follow-up)"
    return "%s - %s, %s, invoice %s (%s)" % (head, t["suite"], period, c["invoice_id"],
                                            facts["dispute_id"])


# ------------------------------------------------------------- recognition

def approve_receivable(conn: Connection, actor: Actor, dispute_id: str, *,
                       reason: Optional[str] = None) -> Dict[str, Any]:
    """The controller approves recognising the receivable (lease_api). Anyone
    else is refused on record; recognition after the landlord has refused
    any of it is a DisputeError."""
    d = load_dispute(conn, dispute_id)
    item = receivable_item(conn, dispute_id)
    if item is None:
        raise DisputeStateError("dispute %s has no receivable to recognise yet; the letter must be "
                           "sent first" % dispute_id)
    if actor.role != RECOGNISER:
        why = "only a controller may recognise a landlord receivable; %s is %s" % (
            actor.id, actor.role)
        event = record_denial(conn, actor, "approve", load_item(conn, item["id"]), why,
                              evidence={"dispute_id": dispute_id})
        raise RecognitionRefused(why, event)
    if d["status"] not in RECOGNISABLE:
        raise DisputeStateError("dispute %s is %s; a receivable is recognised only while the "
                           "landlord has not refused it (sent or acknowledged)"
                           % (dispute_id, d["status"]))
    return transition(conn, actor, item["id"], "approve", reason=reason,
                      evidence={"dispute_id": dispute_id, "recognize": str(d["amount"])})


# --------------------------------------------------------------- replies

def reply_from_datagen(reply: Any) -> Dict[str, Any]:
    """A datagen/replies.Reply as the payload record_reply takes."""
    return {"outcome": reply.outcome, "granted": reply.granted,
            "credit_memo_ref": "CM-%s" % reply.message_id if reply.granted else None,
            "reason": reply.body if reply.outcome in REOPENS else None,
            "received_on": reply.sent, "sender": reply.sender, "message_id": reply.message_id,
            "body": reply.body}


def record_reply(conn: Connection, actor: Actor, dispute_id: str, outcome: str, *,
                 granted: Any = None, credit_memo_ref: Optional[str] = None,
                 reason: Optional[str] = None, received_on: Optional[date] = None,
                 sender: Optional[str] = None, message_id: Optional[str] = None,
                 body: Optional[str] = None) -> Dict[str, Any]:
    """Record the landlord's reply (lease_api, in the caller's transaction).

    acknowledged / queried   status acknowledged
    full_credit              credited; the credit memo clears the receivable
    partial_credit           partially_credited; `granted` is credited, the
                             rest is reopened to the regional manager
    refused                  refused; reopened to the regional manager

    The ledger side (clearing) is the gateway's: gateway.sync_disputes."""
    if outcome not in OUTCOMES:
        raise DisputeError("outcome must be one of %s, got %r" % (", ".join(OUTCOMES), outcome))
    d = conn.execute(text("SELECT * FROM dispute WHERE id = :id FOR UPDATE"),
                     {"id": dispute_id}).mappings().first()
    if d is None:
        raise UnknownDispute("no dispute %s" % dispute_id)
    refusal = _reply_refusal(actor, outcome, d)
    if refusal:
        event = _record_reply_denial(conn, actor, dispute_id, outcome, refusal)
        raise ReplyRefused(refusal, event)
    if d["status"] not in REPLY_FROM:
        raise DisputeStateError("dispute %s is %s; a reply is recorded only once the letter is sent "
                           "and before it is settled" % (dispute_id, d["status"]))
    landlord = conn.execute(text("SELECT authorized_rep_email FROM landlord WHERE id = :id"),
                            {"id": d["landlord_id"]}).scalar()
    if sender and landlord and sender.strip().lower() != landlord.strip().lower():
        raise DisputeError("the reply is from %s, not the landlord's authorized representative "
                           "%s; under the notices clause it does not bind the landlord"
                           % (sender, landlord))

    remaining = _money(d["amount"]) - _money(d["credited_amount"])
    credit = ZERO
    if outcome == OUT_FULL:
        credit = _money(granted) if granted not in (None, "") else remaining
        if credit != remaining:
            raise DisputeError("a full credit is $%s (what remains in dispute), not $%s"
                               % (remaining, credit))
    elif outcome == OUT_PARTIAL:
        credit = _money(granted)
        if credit is None or not ZERO < credit < remaining:
            raise DisputeError("a partial credit must be more than 0 and less than the $%s in "
                               "dispute, got %r" % (remaining, granted))
    if outcome in REOPENS and not (reason or body or "").strip():
        raise DisputeError("a %s needs the landlord's reason" % outcome.replace("_", " "))

    credits = list(d["credits"] or [])
    ref = None
    if credit > 0:
        ref = (credit_memo_ref or message_id or "").strip()
        if not ref:
            raise DisputeError("a credit needs its credit memo reference")
        if any(c.get("credit_memo_ref") == ref for c in credits):
            raise DisputeError("credit memo %s is already matched to dispute %s"
                               % (ref, dispute_id))
        credits.append({"credit_memo_ref": ref, "amount": str(credit),
                        "received_on": (received_on or _today(conn)).isoformat()})

    status = STATUS_FOR[outcome]
    landlord_reason = (reason or body or "").strip() or None
    if outcome in REOPENS:
        _reopen(conn, actor, d, outcome, credit, remaining - credit, landlord_reason)

    conn.execute(text("""
        UPDATE dispute SET status = :status, credited_amount = :credited,
               credits = CAST(:credits AS jsonb), credit_memo_ref = coalesce(:ref, credit_memo_ref),
               refusal_reason = CASE WHEN :reopens THEN :why ELSE refusal_reason END,
               updated_at = now()
         WHERE id = :id
    """), {"status": status, "credited": _money(d["credited_amount"]) + credit,
           "credits": _json(credits), "ref": ref, "reopens": outcome in REOPENS,
           "why": landlord_reason, "id": dispute_id})
    append_event(conn, actor_id=actor.id, action="reply", subject_type=SUBJECT,
                 subject_id=dispute_id, reason=landlord_reason,
                 diff={"from": d["status"], "to": status},
                 evidence={"outcome": outcome, "credited": str(credit), "credit_memo_ref": ref,
                           "remaining": str(remaining - credit), "sender": sender,
                           "message_id": message_id,
                           "received_on": received_on.isoformat() if received_on else None})
    return load_dispute(conn, dispute_id)


def _reply_refusal(actor: Actor, outcome: str, d: Mapping) -> Optional[str]:
    allowed = RECORDERS.get(actor.role)
    if allowed is None:
        return "role %s may not record a landlord reply" % actor.role
    if outcome not in allowed:
        return ("only a controller records a %s: it changes what we expect to recover; %s is %s"
                % (outcome.replace("_", " "), actor.id, actor.role))
    if actor.entity_id is not None and actor.entity_id != d["entity_id"]:
        return "dispute %s is outside %s's entity %s" % (d["id"], actor.id, actor.entity_id)
    return None


def _record_reply_denial(conn: Connection, actor: Actor, dispute_id: str, outcome: str,
                         why: str):
    """On a connection of its own, committed at once, so the refusal outlives
    the caller's rollback (nothing was appended in the caller's transaction)."""
    fields = dict(actor_id=actor.id, action="reply", subject_type=SUBJECT, subject_id=dispute_id,
                  allowed=False, reason=why, evidence={"outcome": outcome})
    with conn.engine.connect() as side:
        with side.begin():
            return append_event(side, **fields)


def _reopen(conn: Connection, actor: Actor, d: Mapping, outcome: str, credit: Decimal,
            left: Decimal, landlord_reason: Optional[str]) -> None:
    """Put the DISPUTE item back in front of the regional manager: APPROVED ->
    HELD, the landlord's reason as the item's reason."""
    item = load_item(conn, d["work_item_id"])
    if item["state"] != "APPROVED":
        raise DisputeStateError("dispute %s: its work item is %s, not APPROVED with the letter out"
                           % (d["id"], item["state"]))
    head = ("Landlord credited $%s and refused the remaining $%s" % (_fmt(credit), _fmt(left))
            if outcome == OUT_PARTIAL else "Landlord refused the $%s in dispute" % _fmt(left))
    transition(conn, actor, item["id"], "hold",
               reason="%s: %s. Regional manager: resume to pursue (a follow-up letter), or "
                      "reject to concede." % (head, _clip(landlord_reason, 600)),
               evidence={"dispute_id": d["id"], "outcome": outcome, "credited": str(credit),
                         "remaining": str(left)})


# --------------------------------------------------------------------- reads

def load_dispute(conn: Connection, dispute_id: str) -> Dict[str, Any]:
    row = conn.execute(text("SELECT * FROM dispute WHERE id = :id"),
                       {"id": dispute_id}).mappings().first()
    if row is None:
        raise UnknownDispute("no dispute %s" % dispute_id)
    return dict(row)


def receivable_item(conn: Connection, dispute_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(text("""
        SELECT * FROM work_item WHERE kind = :k AND subject_type = :st AND subject_id = :id
    """), {"k": RECEIVABLE, "st": SUBJECT, "id": dispute_id}).mappings().first()
    return dict(row) if row else None


def history(conn: Connection, dispute_id: str) -> list:
    return events_for(conn, SUBJECT, dispute_id)


def receivable(conn: Connection, dispute_id: str) -> Dict[str, Any]:
    """The receivable as the books have it: what was recognised, cleared by
    credit memos and written off, and the open balance."""
    rows = conn.execute(text("""
        SELECT e.id, e.idempotency_key, e.date, e.period,
               coalesce(sum(l.debit) FILTER (WHERE a.name = :lr), 0) AS dr,
               coalesce(sum(l.credit) FILTER (WHERE a.name = :lr), 0) AS cr
          FROM journal_entry e
          JOIN journal_line l ON l.journal_entry_id = e.id
          JOIN account a ON a.id = l.account_id
         WHERE e.idempotency_key LIKE 'dispute\\_%'
           AND split_part(e.idempotency_key, ':', 2) = :id
         GROUP BY e.id ORDER BY e.id
    """), {"lr": LANDLORD_RECEIVABLE, "id": dispute_id}).mappings().all()
    recognised = sum((r["dr"] for r in rows), ZERO)
    reduced = sum((r["cr"] for r in rows), ZERO)
    return {"recognized": str(recognised), "cleared": str(reduced), "open": str(recognised - reduced),
            "entries": [{"journal_entry_id": r["id"], "key": r["idempotency_key"],
                         "date": r["date"].isoformat(), "debit": str(r["dr"]),
                         "credit": str(r["cr"])} for r in rows]}


# -------------------------------------------------------------------- agents

def ensure_agents(conn: Connection) -> None:
    """Make sure agent:disputes and agent:obligations exist (migration 0006
    inserts them; a test that empties the actor table, or a seed into a
    fresh database, calls this on a gateway or owner connection)."""
    conn.execute(text("""
        INSERT INTO actor (id, name, role, active) VALUES
            ('agent:disputes', 'Disputes agent', 'agent', true),
            ('agent:obligations', 'Obligations agent', 'agent', true)
        ON CONFLICT (id) DO NOTHING
    """))


# ------------------------------------------------------------------- helpers

def _disputed(item: Mapping) -> Decimal:
    evidence = item.get("evidence") or {}
    disputed = _money(evidence.get("disputed"))
    if disputed is None:
        billed = _money(evidence.get("billed", item.get("amount"))) or ZERO
        supported = _money(evidence.get("supported")) or ZERO
        disputed = billed - min(max(supported, ZERO), billed)
    return disputed


def _today(conn: Connection) -> date:
    from ..jobs import clock

    return clock.today(conn)


def _money(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount.quantize(CENT) if amount.is_finite() else None


def _fmt(value: Any) -> str:
    return "{:,.2f}".format(_money(value) or ZERO)


def _fmt_col(value: Any) -> str:
    return "%12s" % _fmt(value)


def _long(d: date) -> str:
    return "%s %d, %d" % (d.strftime("%B"), d.day, d.year)


def _clip(value: Optional[str], limit: int = 300) -> str:
    value = " ".join((value or "").split())
    return value if len(value) <= limit else value[:limit - 3].rstrip() + "..."


def _wrap(value: str, indent: str = "", width: int = 78) -> List[str]:
    import textwrap

    return textwrap.wrap(value, width=width, initial_indent=indent,
                         subsequent_indent=indent) or [indent.rstrip()]


def _json(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, default=str)
