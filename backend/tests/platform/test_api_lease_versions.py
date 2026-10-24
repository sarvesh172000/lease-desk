"""GET /api/leases/{id}/versions, and confirming a version through the
existing items action route, against a real seeded and drafted January."""

import dataclasses
import subprocess
import sys
from pathlib import Path

import lease_world as lw
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_data_dir, get_gateway_engine
from app.auth.deps import api_engine, auth_settings
from app.auth.sessions import COOKIE_NAME, issue_token
from app.main import create_app
from app.records.seed import seed
from app.settings import get_settings

ROOT = Path(__file__).resolve().parents[3]
SECRET = "test-lease-versions-secret"
RM = "PER-RM-BAY"
RM_DESERT = "PER-RM-DESERT"
AUDITOR = "PER-AUD"


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("generated")
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    return out


@pytest.fixture
def seeded(clean, generated):
    seed(Path(generated), clean["lease_agent"], clean["lease_gateway"])
    with clean["owner"].begin() as conn:
        conn.execute(text("INSERT INTO region (id, name) VALUES ('REG-DESERT', 'Desert')"))
        conn.execute(text("""
            INSERT INTO actor (id, name, role, region_id, entity_id, active)
            VALUES (:id, 'Desert manager', 'regional_manager', 'REG-DESERT', NULL, true)
        """), {"id": RM_DESERT})
    return clean


@pytest.fixture
def drafted(seeded, generated):
    lw.draft(seeded, generated)
    return seeded


@pytest.fixture
def client(seeded, generated):
    settings = dataclasses.replace(get_settings(), session_secret=SECRET)
    app = create_app(settings)
    app.dependency_overrides[api_engine] = lambda: seeded["lease_api"]
    app.dependency_overrides[get_gateway_engine] = lambda: seeded["lease_gateway"]
    app.dependency_overrides[auth_settings] = lambda: settings
    app.dependency_overrides[get_data_dir] = lambda: Path(generated)
    return TestClient(app)


def as_(client, actor_id):
    client.cookies.set(COOKIE_NAME, issue_token(SECRET, actor_id))
    return client


def test_needs_a_session(client):
    assert client.get("/api/leases/LEASE-01/versions").status_code == 401


def test_unknown_lease_is_404(client):
    assert as_(client, RM).get("/api/leases/LEASE-99/versions").status_code == 404


def test_before_abstraction_there_are_no_versions(client):
    assert as_(client, RM).get("/api/leases/LEASE-01/versions").json() == []


def test_a_draft_lists_every_term_with_its_page_box_quote_and_confidence(client, drafted):
    [v] = as_(client, RM).get("/api/leases/LEASE-01/versions").json()
    assert (v["version"], v["confirmed"], v["confirmed_by"], v["confirmed_at"]) == (
        1, False, None, None)
    assert v["effective_from"] == "2024-01-01"
    assert len(v["terms"]) == 13
    rent = next(t for t in v["terms"] if t["field"] == "base_rent_monthly")
    assert rent["value"] == 18500.0 and "$18,500.00" in rent["quote"]
    assert rent["page"] >= 1 and len(rent["bbox"]) == 4 and rent["confidence"] == 1.0
    assert rent["extracted_by"]["agent"] == "abstraction:generator"
    assert rent["extracted_by"]["model"] is None
    assert v["work_item"]["state"] == "PROPOSED" and v["work_item"]["proposal"] == "approve"
    assert "approve" in v["work_item"]["allowed_actions"]

    # The cited page is servable by the document id the term carries.
    pages = client.get("/api/documents/%s/pages" % rent["document_id"])
    assert pages.status_code == 200 and pages.json()["page_count"] >= rent["page"]


def test_confirm_is_only_offered_to_who_may_press_it(client, drafted):
    for who in (AUDITOR, RM_DESERT):
        [v] = as_(client, who).get("/api/leases/LEASE-01/versions").json()
        assert v["work_item"]["allowed_actions"] == [], who


def test_the_regional_manager_confirms_through_the_items_action(client, drafted):
    [v] = as_(client, RM).get("/api/leases/LEASE-03/versions").json()
    item_id = v["work_item"]["id"]

    refused = as_(client, RM_DESERT).post("/api/items/%d/actions/approve" % item_id)
    assert refused.status_code in (403, 404)

    done = as_(client, RM).post("/api/items/%d/actions/approve" % item_id)
    assert done.status_code == 200, done.text
    assert done.json()["state"] == "APPROVED" and done.json()["posting"] is None

    [v] = client.get("/api/leases/LEASE-03/versions").json()
    assert v["confirmed"] and v["confirmed_by"] == RM and v["confirmed_at"]
    assert v["work_item"]["state"] == "APPROVED" and v["work_item"]["allowed_actions"] == ["hold"]
    [other] = client.get("/api/leases/LEASE-04/versions").json()
    assert not other["confirmed"]

    # Pulled back after approval: no longer confirmed, the stamp stays as history.
    held = client.post("/api/items/%d/actions/hold" % item_id, json={"reason": "wrong rent"})
    assert held.status_code == 200, held.text
    [v] = client.get("/api/leases/LEASE-03/versions").json()
    assert not v["confirmed"] and v["confirmed_by"] == RM
    assert v["work_item"]["state"] == "HELD"
