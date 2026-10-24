"""The §16 contract, read literally out of docs/DESIGN.md.

The frontend is built against the JSON fixtures in DESIGN.md §16. This parses
each `GET` fixture from the markdown itself, so editing the doc or the API
without the other fails here: same keys at every level, same JSON value types
(int and float are both "number", as JSON has one number type).

A response may carry keys the fixture does not: the contract is frozen
against renames and removals, and fields may be added (frontend/README.md
lists the ones the web app reads). A missing or retyped key still fails.
"""

import json
import re
from pathlib import Path

import pytest
from test_api_read import (  # noqa: F401 — fixtures
    checked,
    client,
    generated,
    insert_work_item,
    seeded,
)

DESIGN = Path(__file__).resolve().parents[3] / "docs" / "DESIGN.md"


def fixtures() -> dict:
    """{"GET /api/leases": <parsed json>, ...} from §16."""
    doc = DESIGN.read_text()
    section = doc[doc.index("## 16. API surface"):doc.index("## 17.")]
    found = {}
    # Each fixture is introduced by a line starting `GET ...`; its JSON is the
    # first ```json block before the next such line or heading.
    chunks = re.split(r"^(?=`GET |#)", section, flags=re.M)
    for chunk in chunks:
        head = re.match(r"`(GET [^`]+)`", chunk)
        block = re.search(r"```json\n(.*?)\n```", chunk, re.S)
        if head and block:
            found[head.group(1)] = json.loads(block.group(1))
    return found


FIXTURES = fixtures()


def kind(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def same_shape(expected, actual, path="$"):
    """Every mismatch between the fixture's shape and the response's."""
    if kind(expected) != kind(actual):
        return ["%s: fixture has %s, response has %s (%r)"
                % (path, kind(expected), kind(actual), actual)]
    problems = []
    if isinstance(expected, dict):
        if set(expected) - set(actual):
            return ["%s: keys missing %s" % (path, sorted(set(expected) - set(actual)))]
        for key in expected:
            problems += same_shape(expected[key], actual[key], "%s.%s" % (path, key))
    elif isinstance(expected, list) and expected:
        if not actual:
            return ["%s: fixture has items, response is empty" % path]
        for i, item in enumerate(actual):
            problems += same_shape(expected[0], item, "%s[%d]" % (path, i))
    elif isinstance(expected, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", expected):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", actual):
            problems.append("%s: fixture is an ISO date, response is %r" % (path, actual))
    return problems


def test_design_md_still_has_the_three_get_fixtures():
    assert set(FIXTURES) == {"GET /api/leases", "GET /api/exceptions", "GET /api/exceptions/{id}"}


@pytest.fixture
def as_in_the_fixtures(seeded):
    """The data the fixtures describe: LEASE-01's January CAM over-bill
    (pending review, 0.94) and its July amendment variance, investigated."""
    owner = seeded["owner"]
    cam = FIXTURES["GET /api/exceptions"][0]
    insert_work_item(owner, state="PROPOSED", subject_id="cam", clinic_id=cam["clinic_id"],
                     period=cam["period"],
                     evidence={"lease_id": cam["lease_id"], "charge_type": cam["charge_type"],
                               "billed": cam["actual"], "supported": cam["expected"],
                               "confidence": cam["confidence"]})
    detail = FIXTURES["GET /api/exceptions/{id}"]
    july = insert_work_item(owner, state="PROPOSED", subject_id="jul", clinic_id="CLINIC-01",
                            period=detail["period"],
                            evidence={"lease_id": detail["lease_id"], "charge_type": "base_rent",
                                      "billed": detail["actual"], "supported": detail["expected"],
                                      "investigation": detail["investigation"]})
    return july


def test_leases_matches_the_fixture(client, as_in_the_fixtures):
    body = client.get("/api/leases").json()
    assert same_shape(FIXTURES["GET /api/leases"], body) == []


def test_lease_01_matches_the_fixture_values_as_of_june(client, as_in_the_fixtures):
    """The fixture's numbers are real engine output at 30 June 2026."""
    [fixture] = FIXTURES["GET /api/leases"]
    first = client.get("/api/leases", params={"as_of": "2026-06-01"}).json()[0]
    assert first == fixture


def test_exceptions_matches_the_fixture(client, as_in_the_fixtures):
    body = client.get("/api/exceptions").json()
    assert same_shape(FIXTURES["GET /api/exceptions"], body) == []
    [fixture] = FIXTURES["GET /api/exceptions"]
    cam = next(e for e in body if e["charge_type"] == "cam_estimate")
    assert {**cam, "exception_id": fixture["exception_id"]} == fixture


def test_exception_detail_matches_the_fixture(client, as_in_the_fixtures):
    body = client.get("/api/exceptions/exc_%d" % as_in_the_fixtures).json()
    fixture = FIXTURES["GET /api/exceptions/{id}"]
    assert same_shape(fixture, body) == []
    assert {**{k: body[k] for k in fixture}, "exception_id": fixture["exception_id"]} == fixture
    # The additions the web app reads; no box is invented for rows with no documents.
    assert set(body) - set(fixture) == {"item_id", "state", "clinic_id", "charge_type", "confidence",
                                        "proposal", "reason", "rule", "invoice_line", "lease_citation",
                                        "payable", "disputed", "resolution", "resolved_by",
                                        "override_reason"}
    assert body["invoice_line"] is None and body["lease_citation"] is None


def test_the_live_checker_output_has_the_fixture_shape(client, checked):
    """Not just hand-inserted rows: real checker holds fit the contract too,
    except `confidence`, which the checker does not produce (null)."""
    body = client.get("/api/exceptions").json()
    problems = same_shape(FIXTURES["GET /api/exceptions"], body)
    assert problems and all(p.endswith("response has null (None)") and ".confidence" in p
                            for p in problems), problems


def test_the_shape_check_itself_catches_drift():
    fixture = FIXTURES["GET /api/leases"]
    assert same_shape(fixture, [dict(fixture[0], end=None)])
    assert same_shape(fixture, [{k: v for k, v in fixture[0].items() if k != "lessor"}])
    assert same_shape(fixture, [dict(fixture[0], monthly_rent="19626.65")])
    assert same_shape(fixture, [dict(fixture[0], end="31/12/2028")])
    assert same_shape(fixture, [dict(fixture[0], liability=559665)]) == []
    assert same_shape(fixture, [dict(fixture[0], added_later="ok")]) == [], "additions are allowed"
