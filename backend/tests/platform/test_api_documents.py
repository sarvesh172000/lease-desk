"""GET /api/documents/{sha}/pages and /pages/{n}.png: page sizes in PDF points
for scaling citation boxes, and the 150 dpi page image. No database needed."""

import json
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_data_dir
from app.auth.deps import SessionActor, current_actor
from app.docs.storage import LocalStorage
from app.main import create_app

ROOT = Path(__file__).resolve().parents[3]
PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("generated")
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    return out


def client_for(data_dir) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_data_dir] = lambda: Path(data_dir)
    app.dependency_overrides[current_actor] = lambda: SessionActor(
        id="PER-AUD", name="Auditor", role="auditor", region_id=None, entity_id=None)
    return TestClient(app)


@pytest.fixture(scope="module")
def client(generated):
    return client_for(generated)


@pytest.fixture(scope="module")
def lease_sha(generated):
    manifest = json.loads((generated / "manifest.json").read_text())
    return manifest["leases"][0]["document_sha256"]


def test_pages_reports_count_and_size_in_points(client, lease_sha, generated):
    body = client.get("/api/documents/%s/pages" % lease_sha).json()
    with pymupdf.open(LocalStorage(generated / "documents")._path(lease_sha)) as doc:
        assert body["page_count"] == doc.page_count == 8
        assert body["pages"][0] == {"number": 1, "page": 1, "width": round(doc[0].rect.width, 2),
                                    "height": round(doc[0].rect.height, 2)}
    assert body["sha256"] == lease_sha
    assert [p["number"] for p in body["pages"]] == list(range(1, 9))
    assert (body["pages"][0]["width"], body["pages"][0]["height"]) == (612.0, 792.0)  # US Letter


def test_page_png_is_rendered_at_150_dpi(client, lease_sha):
    response = client.get("/api/documents/%s/pages/1.png" % lease_sha)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG)
    pix = pymupdf.Pixmap(response.content)
    assert (pix.width, pix.height) == (round(612 * 150 / 72), round(792 * 150 / 72))
    assert "immutable" in response.headers["cache-control"]


def test_unknown_sha_is_404(client):
    assert client.get("/api/documents/%s/pages" % ("0" * 64)).status_code == 404
    assert client.get("/api/documents/%s/pages/1.png" % ("0" * 64)).status_code == 404


@pytest.mark.parametrize("bad", ["abc", "g" * 64, "A" * 64, "0" * 63, "0" * 65, "..%2F..%2Fetc"])
def test_non_hex_sha_is_400(client, bad):
    assert client.get("/api/documents/%s/pages" % bad).status_code in (400, 404)
    if "%2F" not in bad:  # an encoded slash may not even reach the route
        assert client.get("/api/documents/%s/pages" % bad).status_code == 400
        assert client.get("/api/documents/%s/pages/1.png" % bad).status_code == 400


@pytest.mark.parametrize("page,status", [("9", 404), ("0", 422), ("-1", 422), ("one", 422)])
def test_bad_page_numbers(client, lease_sha, page, status):
    assert client.get("/api/documents/%s/pages/%s.png" % (lease_sha, page)).status_code == status


def test_a_stored_file_that_is_not_a_pdf_is_415(tmp_path):
    sha = LocalStorage(tmp_path / "documents").put(b"not a pdf at all")
    c = client_for(tmp_path)
    assert c.get("/api/documents/%s/pages" % sha).status_code == 415
    assert c.get("/api/documents/%s/pages/1.png" % sha).status_code == 415


def test_no_store_yet_is_404_and_creates_nothing(tmp_path):
    c = client_for(tmp_path)
    assert c.get("/api/documents/%s/pages" % ("a" * 64)).status_code == 404
    assert not (tmp_path / "documents").exists()
