"""The eval runner itself: it must score honestly and fail when it should."""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import eval.run as eval_run
from app.agents.checker import APPROVE, HOLD, check_month
from datagen.answer_key import build_answer_key, write
from datagen.month import build_month
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
        "error_id": "E99", "kind": "invented", "clinic_id": "STORE-03",
        "period": "2026-01-01", "charge_type": "cam_estimate",
        "billed": 1.0, "correct": 0.0, "variance": 1.0, "is_error": True,
        "lease_section": "0", "proof_quote": "", "expected_route": "auto",
        "expected_outcome": "hold", "description": "never actually billed",
    })
    section = score_checking(broken)
    assert not section.ok
    assert "E99" in section.detail["missed"]


def _checker_that(flip):
    """The real checker, with its proposal flipped on the lines `flip` picks."""
    def check(charges, rules, period):
        findings = check_month(charges, rules, period)
        for f in findings:
            if flip(f.charge):
                f.proposal = APPROVE if f.is_hold else HOLD
        return findings
    return check


def test_a_false_hold_fails_the_eval(key, monkeypatch):
    """Make the checker hold STORE-04's $400 step, which is correct."""
    monkeypatch.setattr(eval_run, "check_month", _checker_that(
        lambda c: c.clinic_id == "STORE-04" and c.charge_type == "base_rent"))
    section = score_checking(key)
    assert not section.ok
    assert section.detail["false_holds"] == ["E6"]


def test_holding_the_right_clinic_on_the_wrong_line_is_not_a_catch(key, monkeypatch):
    """STORE-01 has two rent lines. Holding the genuine one and paying the
    duplicate must score E2 as missed, not caught."""
    monkeypatch.setattr(eval_run, "check_month", _checker_that(
        lambda c: c.clinic_id == "STORE-01" and c.charge_type == "base_rent"))
    section = score_checking(key)
    assert not section.ok
    assert section.detail["missed"] == ["E2"]


def test_charge_ids_are_unique():
    """E3's stray Suite 118 line shares an invoice and charge type with
    STORE-02's real rent. Ingestion and per-charge scoring key on the id."""
    ids = [c.charge_id for i in build_month(date(2026, 1, 1)) for c in i.charges]
    assert len(ids) == len(set(ids))


def test_every_hold_cites_the_clause_that_proves_it(key):
    """Jenil pinned this as a known gap: the escalation errors E4 and E5 cited
    the initial-rent clause 3.1 instead of the escalation clause 3.3. The
    checker now picks the proof by what kind of amount error it is — a billed
    figure matching a different year of the schedule is an escalation problem —
    so all five cite correctly.
    """
    section = score_checking(key)
    citations = section.detail["citations"]
    assert set(citations) == {"E1", "E2", "E3", "E4", "E5"}

    wrong = [e for e, c in sorted(citations.items()) if not c["correct"]]
    assert wrong == [], "citing the wrong clause: %s" % wrong
    assert section.detail["citations_correct"] == 5


def test_the_escalation_errors_cite_the_escalation_clause(key):
    section = score_checking(key)
    for error_id in ("E4", "E5"):
        assert section.detail["citations"][error_id]["cited"] == "3.3"


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


def cold(monkeypatch, tmp_path):
    """No key, an empty cache, and none of the repository's committed answers."""
    from app.llm import client as llm_client

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(llm_client, "_default_cache_dir", lambda: str(tmp_path / "cold-cache"))
    monkeypatch.setattr(llm_client, "REPLAY_DIR", tmp_path / "no-committed-answers")


def test_sections_needing_a_model_are_skipped_not_failed(tmp_path, monkeypatch):
    """Without a warm cache or a key, the eval says so rather than scoring zero."""
    cold(monkeypatch, tmp_path)
    key_path = write(tmp_path / "answer_key.json")
    out = tmp_path / "report.json"

    main(["--key", str(key_path), "--out", str(out),
          "--history", str(tmp_path / "h.csv"), "--extraction"])

    report = json.loads(out.read_text())
    assert report["sections"]["investigation"]["skipped"]
    assert report["sections"]["extraction"]["skipped"]
    assert report["passed"], "a skipped section must not fail the run"


def test_the_investigation_is_scored_from_the_committed_answers(tmp_path, monkeypatch):
    """No key, but the repository's answers: the July story is scored, not skipped."""
    from app.llm import client as llm_client

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(llm_client, "_default_cache_dir", lambda: str(tmp_path / "own-cache"))
    key_path = write(tmp_path / "answer_key.json")
    out = tmp_path / "report.json"

    main(["--key", str(key_path), "--out", str(out), "--history", str(tmp_path / "h.csv")])

    section = json.loads(out.read_text())["sections"]["investigation"]
    assert not section["skipped"] and section["passed"], section


# --- the held-out company (chunk B8) ---------------------------------------

def test_the_engines_hold_up_on_a_company_never_seen():
    from eval.run import score_heldout

    section = score_heldout()
    assert section.ok, section.detail
    assert all(section.detail["checks"].values())


def test_the_held_out_section_names_the_other_company():
    from datagen.company import FULL, build_company
    from eval.run import score_heldout

    section = score_heldout()
    assert section.detail["seed"] != build_company(FULL).seed
    assert "Stonebridge" in section.detail["company"]


def test_held_out_appears_in_the_report(tmp_path):
    import json

    from datagen.answer_key import write
    from eval.run import main

    key_path = write(tmp_path / "answer_key.json")
    out = tmp_path / "report.json"
    main(["--key", str(key_path), "--out", str(out), "--history", str(tmp_path / "h.csv")])
    report = json.loads(out.read_text())
    assert report["sections"]["held_out"]["ok"]
