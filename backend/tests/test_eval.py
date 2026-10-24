"""The eval runner itself: it must score honestly and fail when it should."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from datagen.answer_key import build_answer_key, write
from eval.run import main, score_checking, score_safety


@pytest.fixture(scope="module")
def key():
    return build_answer_key()


def test_checking_scores_a_clean_run(key):
    section = score_checking(key)
    assert section.ok
    assert section.detail["missed"] == []
    assert section.detail["false_holds"] == []
    assert section.detail["dollars_match"]


def test_checking_reports_the_dollars(key):
    section = score_checking(key)
    assert section.detail["dollars_flagged"] == 25_736.36


def test_safety_refuses_every_unauthorized_source(key):
    section = score_safety(key)
    assert section.ok
    assert section.detail["injection_fenced_not_stripped"]


def test_a_tampered_answer_key_makes_the_eval_fail(key):
    """If the checker stopped catching something, the eval must notice."""
    broken = json.loads(json.dumps(key))
    broken["errors"].append({
        "error_id": "E99", "kind": "invented", "clinic_id": "CLINIC-03",
        "period": "2026-01-01", "charge_type": "cam_estimate",
        "billed": 1.0, "correct": 0.0, "variance": 1.0, "is_error": True,
        "lease_section": "0", "proof_quote": "", "expected_route": "auto",
        "expected_outcome": "hold", "description": "never actually billed",
    })
    section = score_checking(broken)
    assert not section.ok
    assert "E99" in section.detail["missed"]


def test_a_false_hold_fails_the_eval(key):
    """Flip the correct-but-odd charge to one the checker does hold."""
    broken = json.loads(json.dumps(key))
    odd = next(e for e in broken["errors"] if not e["is_error"])
    odd["clinic_id"] = "CLINIC-03"          # a clinic that IS held
    odd["charge_type"] = "base_rent"
    section = score_checking(broken)
    assert not section.ok
    assert odd["error_id"] in section.detail["false_holds"]


def test_end_to_end_run_writes_a_report(tmp_path):
    key_path = write(tmp_path / "answer_key.json")
    out = tmp_path / "report.json"
    history = tmp_path / "history.csv"

    code = main(["--key", str(key_path), "--out", str(out), "--history", str(history)])

    assert code == 0
    report = json.loads(out.read_text())
    assert report["passed"]
    assert report["sections"]["checking"]["ok"]
    assert history.exists()


def test_history_csv_appends_rather_than_overwrites(tmp_path):
    key_path = write(tmp_path / "answer_key.json")
    out = tmp_path / "report.json"
    history = tmp_path / "history.csv"

    main(["--key", str(key_path), "--out", str(out), "--history", str(history)])
    main(["--key", str(key_path), "--out", str(out), "--history", str(history)])

    assert len(history.read_text().strip().splitlines()) == 3  # header + 2 runs


def test_a_missing_answer_key_is_a_clear_failure(tmp_path):
    assert main(["--key", str(tmp_path / "nope.json"),
                 "--out", str(tmp_path / "r.json"),
                 "--history", str(tmp_path / "h.csv")]) == 2


def test_sections_needing_a_model_are_skipped_not_failed(tmp_path, monkeypatch):
    """Without a warm cache or a key, the eval says so rather than scoring zero."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    key_path = write(tmp_path / "answer_key.json")
    out = tmp_path / "report.json"

    main(["--key", str(key_path), "--out", str(out),
          "--history", str(tmp_path / "h.csv"), "--extraction"])

    report = json.loads(out.read_text())
    assert report["sections"]["investigation"]["skipped"]
    assert report["sections"]["extraction"]["skipped"]
    assert report["passed"], "a skipped section must not fail the run"
