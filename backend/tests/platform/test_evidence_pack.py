"""Evidence packs (chunk B9, PHASE_2 group 14; PHASE_3 group 2 step 8).

Against a real January: a Desert manager is refused on a Bay Area hold, the
Bay Area manager upholds it, the gateway posts the undisputed part. Then the
auditor asks for a pack. The PDF must open (PyMuPDF), quote the lease clause
with the page boxed, show the invoice line and the calculation, list every
approval and denial with actor and time, and carry a chain stamp that says
verified, or broken at the right seq once a row has been tampered with. It is
built as lease_reader, writes nothing, and the route is 401 / 403 / 404 / 422
where it should be.
"""

import dataclasses
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import lease_world as lw
import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_data_dir, get_gateway_engine
from app.api.why import get_reader_engine
from app.auth.deps import api_engine, auth_settings
from app.auth.sessions import COOKIE_NAME, issue_token
from app.db.bootstrap import execute_raw
from app.docs.storage import LocalStorage
from app.jobs.monthly import run_month
from app.jobs.worker import drain
from app.main import create_app
from app.records.seed import seed
from app.settings import get_settings
from app.work.charges import approve_charge
from app.work.evidence_pack import PackError, PackNotFound, Subject, build_pack, parse_subject
from app.work.gateway import post_approved
from app.work.roles import load_actor
from app.work.transitions import Denied, transition
from app.work.why import read_only

ROOT = Path(__file__).resolve().parents[3]
SECRET = "test-pack-secret"
RM_BAY, RM_DESERT, CTRL, AUDITOR, AP = "PER-RM-BAY", "PER-RM-DESERT", "PER-CTRL", "PER-AUD", "PER-AP"
JAN = date(2026, 1, 1)
WRITABLE = ("work_item", "question", "audit_event", "journal_entry", "journal_line", "outbox",
            "lease_version", "lease_term", "job", "policy")


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
    with clean["owner"].begin() as conn:
        conn.execute(text("INSERT INTO region (id, name) VALUES ('REG-DESERT', 'Desert')"))
        conn.execute(text("""
            INSERT INTO actor (id, name, role, region_id, entity_id, active)
            VALUES (:id, 'Desert manager', 'regional_manager', 'REG-DESERT', NULL, true)
        """), {"id": RM_DESERT})
    lw.draft_and_confirm(clean, generated)
    with clean["lease_agent"].begin() as conn:
        run_month(conn, "ENT-CA", "2026-01")
    drain(clean["lease_agent"], "test-pack")
    held = held_item(clean)
    with pytest.raises(Denied):
        with clean["lease_api"].begin() as conn:
            transition(conn, load_actor(conn, RM_DESERT), held["id"], "approve")
    with clean["lease_api"].begin() as conn:
        approve_charge(conn, load_actor(conn, RM_BAY), held["id"])
    with clean["lease_gateway"].begin() as conn:
        post_approved(conn, "ENT-CA", JAN)
    return clean


def held_item(engines):
    with engines["lease_reader"].connect() as conn:
        return dict(conn.execute(text("""
            SELECT * FROM work_item WHERE kind = 'CHARGE_CHECK' AND proposal = 'hold'
             ORDER BY (evidence ->> 'supported')::numeric > 0 DESC,
                      (evidence ->> 'billed')::numeric - (evidence ->> 'supported')::numeric DESC
        """)).mappings().first())


def footprint(engines):
    with engines["owner"].connect() as conn:
        return {t: conn.execute(text("SELECT count(*) FROM %s" % t)).scalar() for t in WRITABLE}


def pack_for(engines, generated, subject, **kw):
    storage = LocalStorage(Path(generated) / "documents")
    with read_only(engines["lease_reader"]) as conn:
        return build_pack(conn, subject, storage=storage, data_dir=Path(generated), **kw)


def pdf_text(pdf: bytes) -> str:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return " ".join(" ".join(page.get_text().split()) for page in doc)


def pdf_images(pdf: bytes) -> int:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return sum(len(page.get_images()) for page in doc)


def squash(s: str) -> str:
    return " ".join(s.split())


# --- the pack --------------------------------------------------------------------------

def test_a_pack_for_a_held_item_has_the_clause_amounts_approvals_and_a_verified_chain(
        january, generated):
    item = held_item(january)
    ev = item["evidence"]
    before = footprint(january)
    pack = pack_for(january, generated, "work_item:%s" % item["id"], requested_by=AUDITOR)
    assert pack.pdf.startswith(b"%PDF")
    words = pdf_text(pack.pdf)

    # The lease clause: the quote (the PDF wraps lines, so compare squashed), section, page box.
    assert squash(ev["proof"]["quote"])[:120] in words
    assert "section %s" % ev["proof"]["section"] in words
    assert "box [" in words and "in PDF points" in words
    # The invoice line and the calculation, to the cent.
    billed, supported = Decimal(str(ev["billed"])), Decimal(str(ev["supported"]))
    for amount in (billed, supported, billed - supported):
        assert "${:,.2f}".format(amount) in words
    assert ev["invoice_id"] in words
    assert "upheld (supported)" in words                     # what was payable, and why
    # Every approval and denial, with actor and time.
    assert "PER-RM-BAY (Dana Whitfield)" in words and "approve (upheld)" in words
    assert "PER-RM-DESERT (Desert manager)" in words and "DENIED" in words and "REG-DESERT" in words
    assert "system:gateway" in words and "agent:checker" in words
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", words)
    # The lease version the checker read was confirmed by the manager: on record too.
    with january["lease_reader"].connect() as conn:
        confirm_item = conn.execute(text("""
            SELECT id FROM work_item WHERE kind = 'LEASE_ABSTRACTION' AND subject_id = :v
        """), {"v": str(ev["lease_version_id"])}).scalar()
    assert "work item %s: propose approve" % confirm_item in words
    assert "work item %s: approve" % confirm_item in words
    # The journal entry posted for the undisputed part.
    assert "Journal entries posted" in words
    # Policies: none cited yet, and the pack says so.
    assert "No policy was cited" in words
    # The stamp.
    stamp = pack.summary["stamp"]
    assert stamp["chain_verified"] and stamp["broken_seq"] is None
    assert "CHAIN VERIFIED" in words and "chain verified" in words.lower()
    assert "seq %s, hash %s" % (stamp["last_event_seq"], stamp["last_event_hash"]) in words
    assert len(stamp["last_event_hash"]) == 64 and stamp["generated_as"] == "lease_reader"
    assert stamp["generated_at"][:4] == str(datetime.now(timezone.utc).year)
    assert pack.summary["denials"][0]["actor_id"] == RM_DESERT
    assert {(a["actor_id"], a["action"]) for a in pack.summary["approvals"]} >= {
        (RM_BAY, "approve"), ("system:gateway", "post")}
    # The lease page and the invoice page, each with its box drawn.
    assert pdf_images(pack.pdf) == 2
    assert footprint(january) == before


def test_a_tampered_chain_makes_the_stamp_say_broken_with_the_seq(january, generated):
    item = held_item(january)
    with january["owner"].connect() as conn:
        target = conn.execute(text("""
            SELECT seq FROM audit_event WHERE subject_type = 'work_item' AND subject_id = :i
             ORDER BY seq LIMIT 1
        """), {"i": str(item["id"])}).scalar()
    with january["owner"].begin() as conn:
        execute_raw(conn, "ALTER TABLE audit_event DISABLE TRIGGER USER;"
                          "UPDATE audit_event SET reason = 'quietly changed' WHERE seq = %d;"
                          "ALTER TABLE audit_event ENABLE TRIGGER USER;" % target)
    pack = pack_for(january, generated, {"type": "work_item", "id": item["id"]})
    words = pdf_text(pack.pdf)
    stamp = pack.summary["stamp"]
    assert not stamp["chain_verified"] and stamp["broken_seq"] == target
    assert "CHAIN BROKEN at seq %d" % target in words
    assert "hash does not match the event contents" in words
    assert "chain verified" not in words.lower()


def test_a_pack_for_a_lease_and_period_covers_every_charge_on_it(january, generated):
    item = held_item(january)
    lease_id = item["evidence"]["lease_id"]
    with january["lease_reader"].connect() as conn:
        n = conn.execute(text("""
            SELECT count(*) FROM work_item WHERE kind = 'CHARGE_CHECK' AND evidence ->> 'lease_id' = :l
        """), {"l": lease_id}).scalar()
    pack = pack_for(january, generated, "lease:%s:2026-01" % lease_id)
    assert len(pack.summary["items"]) == n >= 2
    assert item["id"] in [i["id"] for i in pack.summary["items"]]
    words = pdf_text(pack.pdf)
    assert "lease %s, January 2026" % lease_id in words and "CHAIN VERIFIED" in words
    empty = pack_for(january, generated, "lease:%s:2025-06" % lease_id)
    assert empty.summary["items"] == [] and "No work items are on record" in pdf_text(empty.pdf)


def test_a_pack_for_a_journal_entry_is_the_item_behind_it(january, generated):
    item = held_item(january)
    with january["lease_reader"].connect() as conn:
        entry = conn.execute(text("SELECT id FROM journal_entry WHERE work_item_id = :w"),
                             {"w": item["id"]}).scalar()
    pack = pack_for(january, generated, "journal_entry:%s" % entry)
    assert [i["id"] for i in pack.summary["items"]] == [item["id"]]
    words = pdf_text(pack.pdf)
    assert "Entry %s" % entry in words
    assert "${:,.2f}".format(Decimal(str(item["evidence"]["supported"]))) in words


def test_without_the_documents_the_pack_still_builds_without_boxes(january):
    item = held_item(january)
    with read_only(january["lease_reader"]) as conn:
        pack = build_pack(conn, "work_item:%s" % item["id"], storage=None, data_dir=None)
    words = pdf_text(pack.pdf)
    assert squash(item["evidence"]["proof"]["quote"])[:80] in words
    assert "box not located" in words and pdf_images(pack.pdf) == 0


def test_unknown_subjects_are_not_found(january, generated):
    for subject in ("work_item:999999", "journal_entry:999999", "lease:NO-SUCH:2026-01"):
        with pytest.raises(PackNotFound):
            pack_for(january, generated, subject)
    item = held_item(january)
    with pytest.raises(PackNotFound):
        pack_for(january, generated, "work_item:%s" % item["id"], visible=lambda i: False)


@pytest.mark.parametrize("value,expected", [
    ("work_item:42", Subject("work_item", id="42")),
    ("item:42", Subject("work_item", id="42")),
    ("entry:7", Subject("journal_entry", id="7")),
    ("lease:LEASE-01:2026-01", Subject("lease_period", lease_id="LEASE-01", period=JAN)),
    ({"type": "lease_period", "lease_id": "L:1", "period": "2026-01-01"},
     Subject("lease_period", lease_id="L:1", period=JAN)),
    ({"type": "journal_entry", "id": 3}, Subject("journal_entry", id="3")),
])
def test_parse_subject(value, expected):
    assert parse_subject(value) == expected


@pytest.mark.parametrize("bad", ["", "42", "work_item:", "work_item:x", "work_item:-1",
                                 "lease:LEASE-01", "lease:LEASE-01:2026-13", "lease::2026-01",
                                 {"type": "invoice", "id": 1}, {"type": "lease_period"},
                                 {"type": "lease_period", "lease_id": "L", "period": "2026-01-15"},
                                 ["work_item", 1], 42])
def test_parse_subject_refuses_malformed(bad):
    with pytest.raises(PackError):
        parse_subject(bad)


# --- HTTP ------------------------------------------------------------------------------

def make_client(engines, data_dir) -> TestClient:
    settings = dataclasses.replace(get_settings(), session_secret=SECRET)
    app = create_app(settings)
    app.dependency_overrides[api_engine] = lambda: engines["lease_api"]
    app.dependency_overrides[get_gateway_engine] = lambda: engines["lease_gateway"]
    app.dependency_overrides[get_reader_engine] = lambda: engines["lease_reader"]
    app.dependency_overrides[auth_settings] = lambda: settings
    app.dependency_overrides[get_data_dir] = lambda: Path(data_dir)
    return TestClient(app)


def as_(client, actor_id):
    client.cookies.set(COOKIE_NAME, issue_token(SECRET, actor_id))
    return client


def test_http_pack_is_401_without_a_session(january, generated):
    c = make_client(january, generated)
    assert c.post("/api/evidence-packs", json={"subject": "work_item:1"}).status_code == 401


@pytest.mark.parametrize("who", [RM_BAY, AP])
def test_http_pack_is_403_for_other_roles(january, generated, who):
    c = as_(make_client(january, generated), who)
    assert c.post("/api/evidence-packs", json={"subject": "work_item:1"}).status_code == 403


@pytest.mark.parametrize("who", [AUDITOR, CTRL])
def test_http_pack_returns_the_pdf_to_the_auditor_and_the_controller(january, generated, who):
    item = held_item(january)
    c = as_(make_client(january, generated), who)
    before = footprint(january)
    r = c.post("/api/evidence-packs", json={"subject": "work_item:%s" % item["id"]})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["x-chain-verified"] == "true" and "x-chain-broken-seq" not in r.headers
    assert "attachment" in r.headers["content-disposition"]
    words = pdf_text(r.content)
    assert "CHAIN VERIFIED" in words and "for %s" % who in words
    assert squash(item["evidence"]["proof"]["quote"])[:80] in words
    assert footprint(january) == before


def test_http_pack_reports_a_broken_chain_in_its_headers(january, generated):
    with january["owner"].connect() as conn:
        target = conn.execute(text("SELECT min(seq) + 2 FROM audit_event")).scalar()
    with january["owner"].begin() as conn:
        execute_raw(conn, "ALTER TABLE audit_event DISABLE TRIGGER USER;"
                          "UPDATE audit_event SET reason = 'x' WHERE seq = %d;"
                          "ALTER TABLE audit_event ENABLE TRIGGER USER;" % target)
    item = held_item(january)
    c = as_(make_client(january, generated), AUDITOR)
    r = c.post("/api/evidence-packs", json={"subject": {"type": "work_item", "id": item["id"]}})
    assert r.status_code == 200
    assert r.headers["x-chain-verified"] == "false" and r.headers["x-chain-broken-seq"] == str(target)
    assert "CHAIN BROKEN at seq %d" % target in pdf_text(r.content)


def test_http_pack_bad_and_unknown_subjects(january, generated):
    c = as_(make_client(january, generated), AUDITOR)
    assert c.post("/api/evidence-packs", json={"subject": "nonsense"}).status_code == 422
    assert c.post("/api/evidence-packs", json={}).status_code == 422
    assert c.post("/api/evidence-packs", json={"subject": "work_item:999999"}).status_code == 404
    assert c.post("/api/evidence-packs",
                  json={"subject": "lease:NOPE:2026-01"}).status_code == 404
