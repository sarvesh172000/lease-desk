"""What the web app needs on top of §16, against a real January (chunk A8).

    datagen.build -> seed -> run_month + worker (the real checker) -> the API

Every request carries a real signed session cookie for a seeded person; the
engines, the data directory and the SSE pacing are swapped through
`app.dependency_overrides`, nothing is patched. Covered here:

- GET  /api/exceptions/{id}: clinic_id, charge_type, invoice_line, lease_citation,
  with boxes found on the real PDFs, and null (never invented) when they cannot be
- GET  /api/documents/{doc_id}/pages|file by sha256 or by source_document.id
- POST /api/exceptions/{id}/hold and /approve (posting status, refusals on record)
- POST /api/exceptions/{id}/investigate: SSE frames from the evidence on record
  when the agent cannot run, and a recorded investigation replayed
- GET  /api/summary: held_total is the open over-bills only
"""

import dataclasses
import json
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import lease_world as lw
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agents.investigation_run import NoModel
from app.api.deps import get_data_dir, get_gateway_engine
from app.api.exceptions import investigation_runner, sse_delay
from app.auth.deps import api_engine, auth_settings
from app.auth.sessions import COOKIE_NAME, issue_token
from app.docs.pipeline import extract
from app.docs.storage import LocalStorage
from app.jobs.monthly import run_month
from app.jobs.worker import drain
from app.main import create_app
from app.records.seed import seed
from app.settings import get_settings

ROOT = Path(__file__).resolve().parents[3]
SECRET = "test-live-secret"
RM = "PER-RM-BAY"
CTRL = "PER-CTRL"
AUDITOR = "PER-AUD"
HELD_TOTAL = 25736.36          # the five January over-bills: 4,820 + 19,626.65 + 516.66 + 543.61 + 229.44


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("generated")
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    return out


@pytest.fixture
def january(clean, generated, monkeypatch):
    seed(Path(generated), clean["lease_agent"], clean["lease_gateway"])
    lw.use_documents(monkeypatch, generated)
    # The month drafts the five lease versions; the Bay Area manager confirms
    # them; the month again checks the twelve charges against confirmed terms.
    for confirm in (False, True):
        if confirm:
            lw.confirm(clean)
        with clean["lease_agent"].begin() as conn:
            run_month(conn, "ENT-CA", "2026-01")
        drain(clean["lease_agent"], "test-live")
    return clean


def no_model(**_):
    """The investigation agent with no key and a cold cache (the agent itself,
    with a fake model, is test_investigate_route.py's)."""
    raise NoModel("No model credentials, and this question is not cached yet.")


def make_client(engines, data_dir) -> TestClient:
    settings = dataclasses.replace(get_settings(), session_secret=SECRET)
    app = create_app(settings)
    app.dependency_overrides[api_engine] = lambda: engines["lease_api"]
    app.dependency_overrides[get_gateway_engine] = lambda: engines["lease_gateway"]
    app.dependency_overrides[auth_settings] = lambda: settings
    app.dependency_overrides[get_data_dir] = lambda: Path(data_dir)
    app.dependency_overrides[sse_delay] = lambda: 0.0
    app.dependency_overrides[investigation_runner] = lambda: no_model
    return TestClient(app)


@pytest.fixture
def client(january, generated):
    return make_client(january, generated)


def as_(client, actor_id):
    client.cookies.set(COOKIE_NAME, issue_token(SECRET, actor_id))
    return client


def items(engines):
    with engines["lease_reader"].connect() as conn:
        return conn.execute(text("""
            SELECT w.id, w.state, w.proposal, w.evidence, c.description, c.amount
              FROM work_item w JOIN landlord_charge c ON c.id = w.subject_id
             WHERE w.kind = 'CHARGE_CHECK' ORDER BY w.id
        """)).mappings().all()


def item_where(engines, **match):
    return next(i for i in items(engines)
                if all((i["evidence"].get(k) if k in i["evidence"] else i.get(k)) == v
                       for k, v in match.items()))


def words_in(generated, doc_id, page, box):
    """The words of `doc_id` whose centres fall inside `box` on `page`."""
    doc = extract(LocalStorage(generated / "documents").get(doc_id))
    x0, y0, x1, y1 = box
    return " ".join(w.text for w in doc.page(page).words
                    if x0 <= (w.x0 + w.x1) / 2 <= x1 and y0 <= (w.y0 + w.y1) / 2 <= y1)


def frames(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    chunks = [c for c in response.text.split("\n\n") if c.strip()]
    assert all(c.startswith("data: ") for c in chunks), chunks
    return [json.loads(c[len("data: "):]) for c in chunks]


# --- GET /api/exceptions/{id}: where on the page --------------------------------------

def test_every_january_hold_boxes_the_invoice_line_and_the_lease_clause(client, january, generated):
    manifest = json.loads((generated / "manifest.json").read_text())
    lease_shas = {l["lease_id"]: l["document_sha256"] for l in manifest["leases"]}
    holds = as_(client, RM).get("/api/exceptions").json()
    assert len(holds) == 5
    for summary in holds:
        body = client.get("/api/exceptions/%s" % summary["exception_id"]).json()
        assert (body["clinic_id"], body["charge_type"]) == (summary["clinic_id"], summary["charge_type"])
        line, cited = body["invoice_line"], body["lease_citation"]

        assert line["amount"] == body["actual"]
        assert line["description"] in words_in(generated, line["doc_id"], line["page"], line["box"])
        assert "${:,.2f}".format(line["amount"]) in words_in(generated, line["doc_id"], line["page"],
                                                             line["box"])

        assert cited["doc_id"] == lease_shas[body["lease_id"]]
        assert cited["match_score"] == 1.0
        located = words_in(generated, cited["doc_id"], cited["page"], cited["box"])
        assert cited["quote"].split()[0] in located and cited["quote"].split()[-1] in located
        assert cited["label"].startswith(body["lease_id"] + " · §")


def test_the_suite_118_line_is_boxed_on_its_own_invoice_row(client, january, generated):
    suite = item_where(january, rule="premises")
    body = as_(client, RM).get("/api/exceptions/exc_%d" % suite["id"]).json()
    line = body["invoice_line"]
    assert line["description"] == "Base Rent — Suite 118 — January 2026"
    assert words_in(generated, line["doc_id"], line["page"], line["box"]).split() == [
        "Base", "Rent", "—", "Suite", "118", "—", "January", "2026", "Suite", "118",
        "January", "2026", "$4,820.00"]
    assert body["lease_citation"]["quote"] == "those certain premises designated as Suite 115"
    assert (body["proposal"], body["rule"], body["state"], body["item_id"]) == (
        "hold", "premises", "PROPOSED", suite["id"])
    assert "Suite 118" in body["reason"]


def test_a_correct_charge_opens_on_the_same_screen_but_is_not_listed(client, january):
    good = next(i for i in items(january) if i["proposal"] == "approve")
    c = as_(client, RM)
    assert "exc_%d" % good["id"] not in {e["exception_id"] for e in c.get("/api/exceptions").json()}
    body = c.get("/api/exceptions/exc_%d" % good["id"]).json()
    assert (body["delta"], body["proposal"], body["status"]) == (0.0, "approve", "pending_review")
    assert body["invoice_line"]["amount"] == float(good["amount"])


def test_without_the_documents_there_is_no_box_rather_than_a_made_up_one(january, tmp_path):
    c = as_(make_client(january, tmp_path), RM)       # an empty data directory
    hold = c.get("/api/exceptions").json()[0]
    body = c.get("/api/exceptions/%s" % hold["exception_id"]).json()
    assert body["invoice_line"] is None and body["lease_citation"] is None
    assert body["delta"] == hold["delta"], "the numbers do not depend on the documents"


def test_a_quote_that_is_not_on_the_page_gets_no_box(client, january):
    item = item_where(january, rule="premises")
    evidence = dict(item["evidence"], proof={"quote": "a sentence this lease never says anywhere at all",
                                             "section": "9.9", "page": None, "box": None})
    with january["owner"].begin() as conn:
        conn.execute(text("UPDATE work_item SET evidence = CAST(:e AS jsonb) WHERE id = :id"),
                     {"e": json.dumps(evidence), "id": item["id"]})
    body = as_(client, RM).get("/api/exceptions/exc_%d" % item["id"]).json()
    assert body["lease_citation"] is None
    assert body["invoice_line"] is not None


# --- documents by sha or by source_document.id ------------------------------------------

def test_documents_by_source_document_id_and_by_sha(client, january, generated):
    with january["lease_reader"].connect() as conn:
        doc_id, sha = conn.execute(text(
            "SELECT id, sha256 FROM source_document WHERE kind = 'invoice' ORDER BY id LIMIT 1")).one()
    c = as_(client, AUDITOR)
    by_id = c.get("/api/documents/%s/pages" % doc_id).json()
    by_sha = c.get("/api/documents/%s/pages" % sha).json()
    assert by_id["sha256"] == by_sha["sha256"] == sha
    assert (by_id["doc_id"], by_id["kind"], by_sha["doc_id"]) == (doc_id, "invoice", sha)
    assert by_id["pages"] == by_sha["pages"]
    assert by_id["pages"][0]["page"] == by_id["pages"][0]["number"] == 1

    stored = LocalStorage(generated / "documents").get(sha)
    for key in (doc_id, sha):
        pdf = c.get("/api/documents/%s/file" % key)
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content == stored
    assert c.get("/api/documents/%s/pages/1.png" % doc_id).status_code == 200


def test_unknown_or_malformed_document_ids(client):
    c = as_(client, AUDITOR)
    assert c.get("/api/documents/%s/pages" % ("0" * 32)).status_code == 404
    assert c.get("/api/documents/%s/file" % ("0" * 32)).status_code == 404
    assert c.get("/api/documents/%s/file" % ("0" * 64)).status_code == 404
    for bad in ("eml_20260618", "abc", "0" * 33, "A" * 32):
        assert c.get("/api/documents/%s/file" % bad).status_code == 400, bad


def test_a_stored_file_that_is_not_a_pdf_is_not_served_as_one(january, tmp_path):
    sha = LocalStorage(tmp_path / "documents").put(b"not a pdf at all")
    c = as_(make_client(january, tmp_path), AUDITOR)
    assert c.get("/api/documents/%s/file" % sha).status_code == 415


# --- hold and approve --------------------------------------------------------------------

def test_hold_parks_the_item_and_answers_like_approve(client, january):
    hold = item_where(january, rule="duplicate")
    c = as_(client, RM)
    response = c.post("/api/exceptions/exc_%d/hold" % hold["id"], json={"reason": "asking the landlord"})
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "escalated", "exception_id": "exc_%d" % hold["id"],
                               "state": "HELD", "posting": None}
    assert c.get("/api/items/%d/allowed-actions" % hold["id"]).json() == {"actions": ["resume", "reject"]}
    assert c.post("/api/exceptions/exc_%d/hold" % hold["id"]).status_code == 409


def test_the_auditor_may_neither_hold_nor_approve_and_both_refusals_are_on_record(client, january):
    good = next(i for i in items(january) if i["proposal"] == "approve")
    c = as_(client, AUDITOR)
    assert c.get("/api/items/%d/allowed-actions" % good["id"]).json() == {"actions": []}
    assert c.post("/api/exceptions/exc_%d/approve" % good["id"]).status_code == 403
    assert c.post("/api/exceptions/exc_%d/hold" % good["id"]).status_code == 403
    trail = c.get("/api/audit", params={"subject_type": "work_item",
                                        "subject_id": str(good["id"])}).json()
    denied = [(e["actor_id"], e["action"], e["actor_name"]) for e in trail["events"] if not e["allowed"]]
    assert denied == [(AUDITOR, "approve", "External Auditor"), (AUDITOR, "hold", "External Auditor")]
    assert trail["chain_verified"] is True and trail["broken_at"] is None
    assert all(e["hash"] and len(e["hash"]) == 64 for e in trail["events"])


def test_approving_a_correct_charge_posts_it(client, january):
    good = next(i for i in items(january) if i["proposal"] == "approve")
    c = as_(client, RM)
    assert "approve" in c.get("/api/items/%d/allowed-actions" % good["id"]).json()["actions"]
    body = c.post("/api/exceptions/exc_%d/approve" % good["id"]).json()
    assert (body["status"], body["state"], body["posting"]["status"]) == ("balanced", "POSTED", "posted")
    assert body["posting"]["journal_entry_id"] > 0
    assert c.get("/api/exceptions/exc_%d" % good["id"]).json()["state"] == "POSTED"
    assert c.get("/api/items/%d/allowed-actions" % good["id"]).json() == {"actions": []}


def test_actions_on_something_that_is_not_a_charge_check_are_404(client):
    c = as_(client, RM)
    for path in ("/api/exceptions/exc_999999/hold", "/api/exceptions/exc_999999/approve",
                 "/api/exceptions/42/hold", "/api/exceptions/exc_1/investigate/x"):
        assert c.post(path).status_code == 404, path
    assert c.post("/api/exceptions/exc_999999/investigate").status_code == 404


# --- investigate (SSE) -------------------------------------------------------------------

def test_investigate_streams_the_checker_evidence_and_invents_no_remeasurement(client, january, generated):
    """No model to search the mailbox: the checker's own evidence, then why."""
    suite = item_where(january, rule="premises")
    got = frames(as_(client, RM).post("/api/exceptions/exc_%d/investigate" % suite["id"]))
    assert [f["stage"] for f in got] == ["searching", "found", "error"]
    assert "LEASE-02 §1.1" in got[0]["message"]
    found = got[1]
    manifest = json.loads((generated / "manifest.json").read_text())
    assert found["doc_id"] == next(l["document_sha256"] for l in manifest["leases"]
                                   if l["lease_id"] == "LEASE-02")
    assert found["quote"] == "those certain premises designated as Suite 115"
    # The resolver's documented score (work/resolver.py), read from evidence, never made up.
    assert found["confidence"] == suite["evidence"]["confidence"] == 0.56
    assert found["page"] == 2 and len(found["box"]) == 4
    assert "not cached" in got[2]["message"] and "not searched" in got[2]["message"]
    assert not any(f["stage"] == "remeasured" for f in got)


def test_investigate_without_a_cited_clause_says_not_found(client, january):
    item = item_where(january, rule="premises")
    evidence = {k: v for k, v in item["evidence"].items() if k != "proof"}
    with january["owner"].begin() as conn:
        conn.execute(text("UPDATE work_item SET evidence = CAST(:e AS jsonb) WHERE id = :id"),
                     {"e": json.dumps(evidence), "id": item["id"]})
    got = frames(as_(client, RM).post("/api/exceptions/exc_%d/investigate" % item["id"]))
    assert [f["stage"] for f in got] == ["searching", "not_found", "error"]


def test_investigate_replays_a_recorded_investigation(client, january):
    """The §16 July amendment, stored on an item as the investigation agent records it."""
    investigation = {
        "root_cause": "amendment", "confidence": 0.94, "explains_variance": True,
        "evidence": [{"doc_id": "eml_20260618", "date": "2026-06-18",
                      "source": "dana.reyes@serramonteretail.example", "trust_rank": 1,
                      "quote": "Base rent reduced to $17,400 per month effective July 1, 2026.",
                      "page": 1, "box": [85.0, 125.3, 527.0, 152.1]}],
        "liability_before": 559665.35, "liability_after": 1002921.05,
        "rou_before": 538771.19, "rou_after": 982026.89,
        "entries": [{"account": "Lease liability", "debit": 0, "credit": 443255.70},
                    {"account": "ROU asset", "debit": 443255.70, "credit": 0}],
        "balanced": True}
    item = item_where(january, rule="duplicate")
    with january["owner"].begin() as conn:
        conn.execute(text("UPDATE work_item SET evidence = CAST(:e AS jsonb) WHERE id = :id"),
                     {"e": json.dumps(dict(item["evidence"], investigation=investigation)),
                      "id": item["id"]})
    got = frames(as_(client, RM).post("/api/exceptions/exc_%d/investigate" % item["id"]))
    assert [f["stage"] for f in got] == ["searching", "found", "remeasured", "complete"]
    assert (got[1]["doc_id"], got[1]["confidence"], got[1]["trust_rank"]) == ("eml_20260618", 0.94, 1)
    assert got[2] == {"stage": "remeasured", "liability_delta": 443255.70, "rou_delta": 443255.70}
    assert got[3] == {"stage": "complete", "entries": 2, "balanced": True}


def test_investigate_needs_a_session(client):
    client.cookies.clear()
    assert client.post("/api/exceptions/exc_1/investigate").status_code == 401
    assert client.post("/api/exceptions/exc_1/hold").status_code == 401
    assert client.get("/api/summary").status_code == 401
    assert client.get("/api/documents/%s/file" % ("0" * 64)).status_code == 401


# --- GET /api/summary --------------------------------------------------------------------

def test_summary_is_the_dashboard_tiles(client, january):
    c = as_(client, CTRL)
    body = c.get("/api/summary").json()
    leases = c.get("/api/leases").json()
    assert body["as_of"] == "2026-01-01"
    assert (body["active_leases"], body["open_exceptions"], body["pending_review"]) == (5, 5, 5)
    assert (body["held_total"], body["held_count"]) == (HELD_TOTAL, 5)
    assert Decimal(str(body["portfolio_liability"])) == sum(Decimal(str(l["liability"])) for l in leases)


def test_held_total_counts_open_over_bills_only(client, january):
    """An explained under-bill held for review is not money held, and a
    resolved hold is no longer held; a parked (HELD) one still is."""
    c = as_(client, RM)
    with january["owner"].begin() as conn:     # a $300 under-bill the checker holds for review
        conn.execute(text("""
            INSERT INTO work_item (kind, state, subject_type, subject_id, clinic_id, region_id,
                                   entity_id, period, title, amount, proposal, evidence, proposed_by)
            VALUES ('CHARGE_CHECK', 'PROPOSED', 'landlord_charge', 'under', 'STORE-01', 'REG-BAY',
                    'ENT-CA', '2026-01-01', 'under-bill', 300, 'hold', CAST(:e AS jsonb), 'agent:checker')
        """), {"e": json.dumps({"lease_id": "LEASE-01", "billed": 19326.65, "supported": 19626.65})})
    body = c.get("/api/summary").json()
    assert (body["open_exceptions"], body["held_total"], body["held_count"]) == (6, HELD_TOTAL, 5)

    duplicate = item_where(january, rule="duplicate")
    c.post("/api/exceptions/exc_%d/hold" % duplicate["id"])
    assert c.get("/api/summary").json()["held_total"] == HELD_TOTAL, "HELD is still held"

    cam = item_where(january, rule="operating_expense")
    with january["owner"].begin() as conn:
        conn.execute(text("UPDATE work_item SET state = 'REJECTED' WHERE id = :id"), {"id": cam["id"]})
    after = c.get("/api/summary").json()
    assert after["held_total"] == round(HELD_TOTAL - 516.66, 2)
    assert (after["open_exceptions"], after["held_count"]) == (5, 4)


def test_schedule_says_which_version_is_active(client):
    body = as_(client, CTRL).get("/api/leases/LEASE-01/schedule").json()
    assert (body["version"], body["active"]) == (1, True)
    assert date.fromisoformat(body["effective_from"]) <= date(2026, 1, 1)
