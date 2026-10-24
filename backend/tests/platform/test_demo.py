"""C2: demo snapshots, the one-command reset, judge-provided tagging, the run summary.

A database of this module's own is built to the demo state exactly as
`make demo-data` builds it (datagen, seed, January, the Bay Area manager
confirms the five leases, January again), snapshotted with pg_dump, and then
mutated and reset. The session database (freshly migrated) is the reference
for the grant matrix. Every request goes through the real app with a signed
session cookie; nothing is patched but the engines, the settings and the
snapshot path.
"""

import dataclasses
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import lease_world as lw
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api.demo import demo_snapshot
from app.api.deps import get_gateway_engine
from app.auth.deps import api_engine, auth_settings
from app.auth.sessions import COOKIE_NAME, issue_token
from app.db.engine import make_engine
from app.demo import judge
from app.demo.reset import BUDGET_SECONDS, ResetRefused, reset_database
from app.demo.snapshot import (
    SnapshotError,
    load_manifest,
    manifest_path,
    read_state,
    take_snapshot,
    target,
)
from app.demo.summary import month_items, month_summary, parse_month
from app.jobs.monthly import run_month
from app.jobs.worker import drain
from app.main import create_app
from app.records.seed import seed
from app.settings import DB_ROLES, get_settings
from app.work.events import verify_chain
from app.work.roles import load_actor
from app.work.transitions import transition

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
JAN = parse_month("2026-01")
ENTITY = "ENT-CA"
SECRET = "test-demo-secret"
HELD_TOTAL = 25736.36


# --- the demo database ----------------------------------------------------------------

@pytest.fixture(scope="module")
def demo(database, tmp_path_factory):
    """A database of its own in the `make demo-data` state, and its snapshot."""
    name = "leasedesk_test_demo_%s" % uuid.uuid4().hex[:8]
    admin = create_engine(get_settings().db_url("owner", "postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text('CREATE DATABASE "%s"' % name))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", get_settings().db_url("owner", name))
    command.upgrade(cfg, "head")
    engines = {role: make_engine(role, name) for role in DB_ROLES + ("owner",)}

    generated = tmp_path_factory.mktemp("demo-generated")
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(generated)],
                   cwd=ROOT, check=True, capture_output=True)
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("ANTHROPIC_API_KEY", raising=False)
        mp.setenv("LEASEDESK_LLM_CACHE", str(tmp_path_factory.mktemp("no-llm-cache")))
        lw.use_documents(mp, generated)
        seed(generated, engines["lease_agent"], engines["lease_gateway"])
        for confirm in (False, True):
            if confirm:
                lw.confirm(engines)
            with engines["lease_agent"].begin() as conn:
                run_month(conn, ENTITY, "2026-01")
            drain(engines["lease_agent"], "demo-test")

    dump = tmp_path_factory.mktemp("snapshots") / "demo.dump"
    t = target(database=name)
    manifest = take_snapshot(t, dump)
    try:
        yield {"name": name, "engines": engines, "target": t, "dump": dump, "manifest": manifest}
    finally:
        for eng in engines.values():
            eng.dispose()
        for _attempt in range(20):        # role processes exit a moment after disposal
            try:
                with admin.connect() as conn:
                    conn.execute(text('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % name))
                break
            except Exception:  # noqa: BLE001 - a leftover test database is not a failure
                time.sleep(0.1)
        admin.dispose()


@pytest.fixture
def fresh(demo):
    """Every test starts from the snapshot."""
    result = reset_database(demo["target"], demo["dump"], demo_mode=True)
    assert result.ok, result.mismatches
    return demo


def q(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def approve_a_correct_charge(engines) -> int:
    item_id = q(engines["lease_reader"], """
        SELECT min(id) FROM work_item
         WHERE kind = 'CHARGE_CHECK' AND proposal = 'approve' AND state = 'PROPOSED'""")
    with engines["lease_api"].begin() as conn:
        transition(conn, load_actor(conn, "PER-RM-BAY"), item_id, "approve", reason="matches")
    return item_id


def grants(eng):
    with eng.connect() as conn:
        return sorted(tuple(r) for r in conn.execute(text("""
            SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants
             WHERE grantee = ANY(:roles) AND table_schema = 'public'
            UNION
            SELECT grantee, table_name || '.' || column_name, privilege_type
              FROM information_schema.column_privileges
             WHERE grantee = ANY(:roles) AND table_schema = 'public'
        """), {"roles": list(DB_ROLES)}))


# --- snapshot and reset ---------------------------------------------------------------

def test_the_snapshot_is_the_demo_state_with_a_manifest(demo):
    m = demo["manifest"]
    assert m == load_manifest(demo["dump"])
    assert manifest_path(demo["dump"]).name == "demo.manifest.json"
    assert m["chain_ok"] and m["chain_head"]["hash"]
    assert m["counts"]["work_item"] == 17          # 5 lease confirmations + 12 charge checks
    assert m["counts"]["audit_event"] > 0 and m["judge_provided"] == 0
    assert m["alembic_version"] and m["dump"]["sha256"] and m["created_at"].endswith("Z")
    assert m["git_sha"] is None or len(m["git_sha"]) == 40


def test_mutate_then_reset_gives_back_the_snapshot(fresh):
    eng, m = fresh["engines"], fresh["manifest"]
    item_id = approve_a_correct_charge(eng)
    with eng["lease_api"].begin() as conn:
        judge.append_judge_event(conn, actor_id="PER-CTRL", action="studio_upload",
                                 subject_type="source_document", subject_id="judge-invoice.pdf",
                                 evidence={"filename": "judge-invoice.pdf"})
    moved = read_state(fresh["target"])
    assert moved["counts"]["audit_event"] == m["counts"]["audit_event"] + 2
    assert moved["chain_head"] != m["chain_head"] and moved["judge_provided"] == 1

    result = reset_database(fresh["target"], fresh["dump"], demo_mode=True)

    assert result.ok and result.counts_match and result.head_match and result.chain_ok
    assert result.seconds < BUDGET_SECONDS and result.within_budget
    assert result.judge_provided_cleared == 1
    now = read_state(fresh["target"])
    assert now["counts"] == m["counts"] and now["chain_head"] == m["chain_head"]
    assert now["judge_provided"] == 0
    assert q(eng["lease_reader"], "SELECT state FROM work_item WHERE id = :i", i=item_id) == "PROPOSED"
    with eng["lease_reader"].connect() as conn:
        assert verify_chain(conn) is None


def test_the_four_roles_keep_their_exact_grants_after_a_reset(fresh, engines):
    assert grants(fresh["engines"]["owner"]) == grants(engines["owner"])
    # And they work: the agent may not write the ledger, the API may write events.
    eng = fresh["engines"]
    assert q(eng["lease_reader"], "SELECT has_table_privilege('lease_agent', 'journal_entry', 'INSERT')") is False
    assert q(eng["lease_reader"], "SELECT has_table_privilege('lease_api', 'audit_event', 'INSERT')") is True
    assert q(eng["lease_reader"], "SELECT count(*) FROM work_item") == 17


def test_reset_is_refused_outside_demo_mode_and_touches_nothing(fresh):
    approve_a_correct_charge(fresh["engines"])
    before = read_state(fresh["target"])
    with pytest.raises(ResetRefused):
        reset_database(fresh["target"], fresh["dump"], demo_mode=False)
    assert read_state(fresh["target"]) == before


def test_a_missing_or_stale_snapshot_is_refused_before_anything_changes(fresh, tmp_path):
    with pytest.raises(SnapshotError, match="no snapshot"):
        reset_database(fresh["target"], tmp_path / "nope.dump", demo_mode=True)

    stale = tmp_path / "demo.dump"
    stale.write_bytes(fresh["dump"].read_bytes())
    manifest = dict(fresh["manifest"], alembic_version="0000_old")
    manifest_path(stale).write_text(json.dumps(manifest))
    with pytest.raises(SnapshotError, match="make demo-snapshot"):
        reset_database(fresh["target"], stale, demo_mode=True)

    stale.write_bytes(b"not a dump")
    with pytest.raises(SnapshotError, match="does not match its manifest"):
        reset_database(fresh["target"], stale, demo_mode=True)


def test_judge_evidence_tags_without_mutating():
    original = {"filename": "x.pdf"}
    tagged = judge.judge_evidence(original)
    assert tagged == {"filename": "x.pdf", "judge_provided": True} and original == {"filename": "x.pdf"}
    assert judge.is_judge_provided(tagged) and not judge.is_judge_provided(original)
    assert judge.judge_evidence() == {"judge_provided": True}


# --- POST /api/demo/reset ---------------------------------------------------------------

def client_for(demo, *, demo_mode=True, actor_id=None) -> TestClient:
    settings = dataclasses.replace(get_settings(), session_secret=SECRET, demo_mode=demo_mode)
    app = create_app(settings)
    app.dependency_overrides[api_engine] = lambda: demo["engines"]["lease_api"]
    app.dependency_overrides[get_gateway_engine] = lambda: demo["engines"]["lease_gateway"]
    app.dependency_overrides[auth_settings] = lambda: settings
    app.dependency_overrides[demo_snapshot] = lambda: demo["dump"]
    client = TestClient(app)
    if actor_id:
        client.cookies.set(COOKIE_NAME, issue_token(SECRET, actor_id))
    return client


def test_the_reset_route_does_not_exist_outside_demo_mode(fresh):
    approve_a_correct_charge(fresh["engines"])
    before = read_state(fresh["target"])
    for who in ("PER-CTRL", None):
        assert client_for(fresh, demo_mode=False, actor_id=who).post("/api/demo/reset").status_code == 404
    assert read_state(fresh["target"]) == before


@pytest.mark.parametrize("actor_id", ["PER-RM-BAY", "PER-AP", "PER-AUD"])
def test_only_a_controller_may_reset_and_a_refusal_is_on_record(fresh, actor_id):
    eng = fresh["engines"]
    res = client_for(fresh, actor_id=actor_id).post("/api/demo/reset")
    assert res.status_code == 403 and "controller" in res.json()["detail"]
    with eng["lease_reader"].connect() as conn:
        last = conn.execute(text("SELECT * FROM audit_event ORDER BY seq DESC LIMIT 1")).mappings().one()
        assert verify_chain(conn) is None
    assert (last["actor_id"], last["action"], last["subject_type"], last["allowed"]) == (
        actor_id, "demo_reset", "demo", False)
    assert last["subject_id"] == fresh["name"]
    assert q(eng["lease_reader"], "SELECT count(*) FROM audit_event") == fresh["manifest"]["counts"]["audit_event"] + 1


def test_signed_out_is_401(fresh):
    assert client_for(fresh).post("/api/demo/reset").status_code == 401


def test_a_controller_resets_the_demo_from_the_app(fresh):
    eng, m = fresh["engines"], fresh["manifest"]
    item_id = approve_a_correct_charge(eng)
    res = client_for(fresh, actor_id="PER-CTRL").post("/api/demo/reset")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "reset" and body["verified"] and body["chain_ok"]
    assert body["counts_match"] and body["head_match"] and body["within_budget"]
    assert body["seconds"] < BUDGET_SECONDS and body["database"] == fresh["name"]
    assert q(eng["lease_reader"], "SELECT state FROM work_item WHERE id = :i", i=item_id) == "PROPOSED"
    # The snapshot's history, then one event: who reset it.
    with eng["lease_reader"].connect() as conn:
        last = conn.execute(text("SELECT * FROM audit_event ORDER BY seq DESC LIMIT 1")).mappings().one()
        assert verify_chain(conn) is None
    assert last["seq"] == body["event_seq"] and last["prev_hash"] == m["chain_head"]["hash"]
    assert (last["actor_id"], last["action"], last["allowed"]) == ("PER-CTRL", "demo_reset", True)
    assert q(eng["lease_reader"], "SELECT count(*) FROM audit_event") == m["counts"]["audit_event"] + 1


def test_the_reset_route_says_when_there_is_no_snapshot(fresh, tmp_path):
    client = client_for(dict(fresh, dump=tmp_path / "missing.dump"), actor_id="PER-CTRL")
    res = client.post("/api/demo/reset")
    assert res.status_code == 409 and "make demo-snapshot" in res.json()["detail"]


# --- the run summary --------------------------------------------------------------------

def test_january_summary_matches_a_direct_count(fresh):
    eng = fresh["engines"]
    with eng["lease_api"].connect() as conn:
        s = month_summary(conn, JAN, ENTITY)
    m = s["metrics"]
    direct = {
        "clinics": q(eng["lease_reader"], """SELECT count(DISTINCT c.clinic_id) FROM landlord_charge c
                     JOIN clinic k ON k.id = c.clinic_id WHERE c.period = '2026-01-01' AND k.entity_id = 'ENT-CA'"""),
        "checked": q(eng["lease_reader"], """SELECT count(*) FROM work_item
                     WHERE kind = 'CHARGE_CHECK' AND period = '2026-01-01'"""),
        "held": q(eng["lease_reader"], """SELECT count(*) FROM work_item WHERE kind = 'CHARGE_CHECK'
                  AND period = '2026-01-01' AND proposal = 'hold'
                  AND state IN ('NEW', 'PROPOSED', 'NEEDS_INFO', 'HELD')"""),
        "held_amount": float(q(eng["lease_reader"], """
                  SELECT sum((evidence->>'billed')::numeric - (evidence->>'supported')::numeric)
                    FROM work_item WHERE kind = 'CHARGE_CHECK' AND period = '2026-01-01'
                     AND proposal = 'hold'
                     AND (evidence->>'billed')::numeric > (evidence->>'supported')::numeric""")),
    }
    assert direct == {"clinics": 5, "checked": 12, "held": 5, "held_amount": HELD_TOTAL}
    assert (m["clinics"]["value"], m["checked"]["value"], m["held"]["value"], m["held"]["amount"]) == (
        5, 12, 5, HELD_TOTAL)
    assert (m["approved"]["value"], m["disputes"]["value"], m["questions"]["value"]) == (0, 0, 0)
    assert m["batch"]["value"] is False and s["batch"]["awaiting_decision"] == 12
    assert s["month"] == "January 2026" and s["entity_name"].startswith("Northbay")
    assert s["headline"] == (
        "January 2026, %s: 5 clinics, 12 charges checked, 0 approved, 5 held for $25,736.36, "
        "0 disputes drafted, 0 questions out, batch ready for AP: no" % s["entity_name"])


def test_every_number_drills_down_to_exactly_its_rows(fresh):
    approve_a_correct_charge(fresh["engines"])
    client = client_for(fresh, actor_id="PER-AUD")
    res = client.get("/api/summary/month", params={"period": "2026-01", "entity": ENTITY})
    assert res.status_code == 200, res.text
    s = res.json()
    assert s["metrics"]["approved"]["value"] == 1
    for name, metric in s["metrics"].items():
        drill = metric["drill"]
        assert drill["endpoint"] == "/api/summary/month/items" and drill["params"]["metric"] == name
        assert drill["filter"]["period"] == "2026-01-01" and drill["filter"]["entity_id"] == ENTITY
        rows = client.get(drill["endpoint"], params=drill["params"]).json()
        expected = s["batch"]["releasable"] if name == "batch" else metric["value"]
        assert len(rows) == expected, name
    held = client.get("/api/summary/month/items",
                      params={"period": "2026-01", "entity": ENTITY, "metric": "held"}).json()
    assert round(sum(r["variance"] for r in held if r["variance"] > 0), 2) == HELD_TOTAL
    assert all(r["exception_id"].startswith("exc_") for r in held)


def test_summary_for_every_entity_unknown_entity_and_bad_input(fresh):
    client = client_for(fresh, actor_id="PER-CTRL")
    every = client.get("/api/summary/month", params={"period": "2026-01-01", "entity": ""}).json()
    one = client.get("/api/summary/month", params={"period": "2026-01", "entity": ENTITY}).json()
    assert every["entity_id"] is None and every["metrics"]["checked"]["value"] == 12
    assert every["headline"] == one["headline"]          # one entity in the demo
    assert client.get("/api/summary/month", params={"period": "2026-01", "entity": "ENT-XX"}).status_code == 404
    assert client.get("/api/summary/month", params={"period": "January"}).status_code == 422
    assert client.get("/api/summary/month/items",
                      params={"period": "2026-01", "metric": "nope"}).status_code == 422
    assert client_for(fresh).get("/api/summary/month", params={"period": "2026-01"}).status_code == 401
    feb = client.get("/api/summary/month", params={"period": "2026-02"}).json()
    assert feb["metrics"]["checked"]["value"] == 0 and feb["metrics"]["batch"]["value"] is False


def test_the_batch_is_ready_once_every_charge_is_decided(fresh):
    eng = fresh["engines"]
    with eng["lease_api"].begin() as conn:
        rm = load_actor(conn, "PER-RM-BAY")
        for (item_id,) in conn.execute(text(
                "SELECT id FROM work_item WHERE kind = 'CHARGE_CHECK' AND state = 'PROPOSED' ORDER BY id")).all():
            transition(conn, rm, item_id, "approve", reason="signed off")
    with eng["lease_api"].connect() as conn:
        s = month_summary(conn, JAN, ENTITY)
        payable = month_items(conn, JAN, ENTITY, "batch")
    assert s["metrics"]["approved"]["value"] == 12 and s["metrics"]["held"]["value"] == 0
    assert s["batch"]["ready"] is True and s["batch"]["awaiting_decision"] == 0
    assert s["batch"]["releasable"] == len(payable) > 0 and s["batch"]["released"] is False
    assert s["headline"].endswith("batch ready for AP: yes")
