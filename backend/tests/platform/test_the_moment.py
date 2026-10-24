"""The moment, end to end, with no model: the demo's whole story replays from
the answers committed in data/reference/llm_cache.

The world is built the way `make demo-data` builds it: January generated,
seeded, the leases confirmed and checked; then July generated, seeded and
checked. CLINIC-01's amendment takes effect in July, so July's rent is billed
$2,226.65 under the schedule and held. Investigating that hold, with no key
and an empty cache of its own, must find the amendment in the mailbox and
remeasure the lease to the figures the pitch quotes.

If this fails after a change to a prompt, a schema or the documents, the
committed answers no longer match: re-run the warm-up with a key (see
data/reference/llm_cache/README.md) and commit the new files.
"""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import lease_world as lw
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_data_dir, get_engine
from app.api.exceptions import sse_delay
from app.auth.deps import current_actor
from app.auth.sessions import SessionActor
from app.jobs.monthly import run_month
from app.jobs.worker import drain
from app.llm import client as llm_client
from app.llm.client import REPLAY_DIR
from app.main import create_app
from app.records.seed import seed

ROOT = Path(__file__).resolve().parents[3]
ENTITY = "ENT-CA"
CONTROLLER = SessionActor(id="PER-CTRL", name="Priya Raghunathan", role="controller",
                          region_id=None, entity_id=None)


def generate(out: Path, month: str) -> None:
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(out), "--month", month],
                   cwd=ROOT, check=True, capture_output=True)


def run(engines, month: str) -> None:
    with engines["lease_agent"].begin() as conn:
        run_month(conn, ENTITY, month)
    drain(engines["lease_agent"], "moment-test")


@pytest.fixture
def july(clean, tmp_path, monkeypatch):
    """January then July, as `make demo-data` runs them."""
    generated = tmp_path / "generated"
    lw.use_documents(monkeypatch, generated)
    generate(generated, "2026-01")
    seed(generated, clean["lease_agent"], clean["lease_gateway"])
    run(clean, "2026-01")
    lw.confirm(clean)
    run(clean, "2026-01")
    generate(generated, "2026-07")
    seed(generated, clean["lease_agent"], clean["lease_gateway"])
    run(clean, "2026-07")
    return clean, generated


@pytest.fixture
def client(july, tmp_path, monkeypatch):
    engines, generated = july
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # A cache of its own, empty: only the committed answers can serve.
    monkeypatch.setattr(llm_client, "_default_cache_dir", lambda: str(tmp_path / "empty-cache"))
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engines["lease_api"]
    app.dependency_overrides[current_actor] = lambda: CONTROLLER
    app.dependency_overrides[get_data_dir] = lambda: Path(generated)
    app.dependency_overrides[sse_delay] = lambda: 0.0
    return TestClient(app)


def frames(response) -> list:
    return [json.loads(block.strip()[len("data:"):])
            for block in response.text.split("\n\n") if block.strip().startswith("data:")]


def test_the_committed_answers_are_in_the_repository():
    assert any(REPLAY_DIR.rglob("*.json")), "data/reference/llm_cache is empty"


def test_july_holds_exactly_the_amended_rent(client):
    july = [e for e in client.get("/api/exceptions").json() if e["period"] == "2026-07-01"]
    assert [(e["lease_id"], e["charge_type"], e["expected"], e["actual"]) for e in july] == [
        ("LEASE-01", "base_rent", 19_626.65, 17_400.00)]


def test_the_investigation_finds_the_amendment_and_remeasures_with_no_model(client):
    exc = next(e["exception_id"] for e in client.get("/api/exceptions").json()
               if e["period"] == "2026-07-01")
    stream = frames(client.post("/api/exceptions/%s/investigate" % exc))

    assert [f["stage"] for f in stream] == ["searching", "found", "remeasured", "complete"]
    found = stream[1]
    assert found["doc_id"] == "eml-20260618-amend" and found["trust_rank"] == 1
    assert "$17,400 per month effective July 1, 2026" in found["quote"]
    assert stream[2]["liability_delta"] == 443_255.70
    assert stream[3] == {"stage": "complete", "entries": 4, "balanced": True}

    detail = client.get("/api/exceptions/%s" % exc).json()["investigation"]
    assert (detail["liability_before"], detail["liability_after"]) == (559_665.35, 1_002_921.05)
    assert sum(e["debit"] for e in detail["entries"]) == pytest.approx(447_880.44)
    assert detail["balanced"] is True


def test_the_portfolio_is_read_as_of_july_once_the_clock_says_so(client, july):
    from app.jobs.clock import set_today

    engines, _ = july
    with engines["lease_agent"].begin() as conn:
        set_today(conn, date(2026, 7, 1))
    assert client.get("/api/summary").json()["as_of"] == "2026-07-01"
