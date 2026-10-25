"""`make seed`: the generated company into the database, under the right
roles, idempotently, and refusing bad input without leaving half a load."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from app.records.ingest import IngestError, stable_id
from app.records.seed import seed

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("generated")
    subprocess.run([sys.executable, "-m", "datagen.build", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    return out


def run(engines, data_dir):
    return seed(Path(data_dir), engines["lease_agent"], engines["lease_gateway"])


def scalar(eng, sql, **params):
    with eng.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def test_seed_loads_the_company(clean, generated):
    counts = run(clean, generated)
    assert counts["clinic"]["total"] == 5
    assert counts["lease"]["total"] == 5
    assert counts["account"]["total"] == 12
    assert counts["period"]["total"] == 24          # 2025 and 2026
    jan = scalar(clean["lease_reader"],
                 "SELECT count(*) FROM landlord_charge WHERE period = '2026-01-01'")
    assert jan == 12


def test_seed_twice_adds_nothing(clean, generated):
    run(clean, generated)
    second = run(clean, generated)
    assert all(c["added"] == 0 for c in second.values()), second


def test_january_billing_matches_the_generator_to_the_cent(clean, generated):
    run(clean, generated)
    total = scalar(clean["lease_reader"],
                   "SELECT sum(amount) FROM landlord_charge WHERE period = '2026-01-01'")
    assert str(total) == "112759.69"


def test_every_charge_traces_to_its_raw_row_and_invoice_pdf(clean, generated):
    run(clean, generated)
    reader = clean["lease_reader"]
    orphans = scalar(reader, """SELECT count(*) FROM landlord_charge c
                                LEFT JOIN raw_row r ON r.id = c.raw_ref WHERE r.id IS NULL""")
    assert orphans == 0
    unlinked = scalar(reader, """SELECT count(*) FROM landlord_charge
                                 WHERE period = '2026-01-01' AND document_id IS NULL""")
    assert unlinked == 0, "every January charge should point at its invoice PDF"


def test_the_stray_suite_line_survives_as_its_own_charge(clean, generated):
    """E3: STORE-02 was billed for Suite 118 on the same invoice as its real
    rent. Two lines, two charges, not one overwriting the other."""
    run(clean, generated)
    suites = scalar(clean["lease_reader"], """
        SELECT string_agg(suite, ',' ORDER BY suite) FROM landlord_charge
         WHERE clinic_id = 'STORE-02' AND period = '2026-01-01' AND charge_type = 'base_rent'""")
    assert suites == "Suite 115,Suite 118"


def test_ids_are_stable_hashes_of_source_and_source_id(clean, generated):
    run(clean, generated)
    expected = stable_id("ap_export", "SERRA-202601-0001-L1")
    assert scalar(clean["lease_reader"], "SELECT count(*) FROM raw_row WHERE id = :i", i=expected) == 1


def test_reseeding_never_reopens_a_closed_period(clean, generated):
    run(clean, generated)
    with clean["lease_gateway"].begin() as conn:
        conn.execute(text("UPDATE period SET status = 'closed' WHERE period = '2025-06-01'"))
    run(clean, generated)
    assert scalar(clean["lease_reader"],
                  "SELECT status FROM period WHERE period = '2025-06-01'") == "closed"


# --- bad input ---------------------------------------------------------------

def _copy(generated, tmp_path):
    target = tmp_path / "data"
    shutil.copytree(generated, target, ignore=shutil.ignore_patterns("documents", "invoices"))
    return target


def _rewrite(path: Path, old: str, new: str):
    content = path.read_text()
    assert old in content
    path.write_text(content.replace(old, new, 1))


def test_a_missing_data_directory_is_a_clear_error(clean, tmp_path):
    with pytest.raises(IngestError, match="datagen.build"):
        run(clean, tmp_path / "nowhere")


def test_a_missing_manifest_is_a_clear_error(clean, generated, tmp_path):
    data = _copy(generated, tmp_path)
    (data / "manifest.json").unlink()
    with pytest.raises(IngestError, match="no manifest"):
        run(clean, data)


def test_a_missing_column_names_the_file(clean, generated, tmp_path):
    data = _copy(generated, tmp_path)
    _rewrite(data / "ap_export.csv", "invoice_id,vendor_id", "invoice_no,vendor_id")
    with pytest.raises(IngestError, match="ap_export.csv is missing column.*invoice_id"):
        run(clean, data)
    assert scalar(clean["lease_reader"], "SELECT count(*) FROM raw_row") == 0


def test_an_unquoted_comma_that_shifts_the_columns_is_refused(clean, generated, tmp_path):
    data = _copy(generated, tmp_path)
    _rewrite(data / "ap_export.csv", ",19626.65,", ",19,626.65,")
    with pytest.raises(IngestError, match="ap_export.csv line 2 has more fields"):
        run(clean, data)


def test_a_bad_amount_names_the_row_and_loads_no_golden_records(clean, generated, tmp_path):
    data = _copy(generated, tmp_path)
    _rewrite(data / "ap_export.csv", ",19626.65,", ",19626.65 USD,")
    with pytest.raises(IngestError, match="SERRA-202601-0001-L1.*'19626.65 USD' is not a number"):
        run(clean, data)
    reader = clean["lease_reader"]
    assert scalar(reader, "SELECT count(*) FROM landlord_charge") == 0
    assert scalar(reader, "SELECT count(*) FROM clinic") == 0, "the golden step rolls back whole"


def test_a_charge_for_an_unknown_lease_is_refused(clean, generated, tmp_path):
    data = _copy(generated, tmp_path)
    _rewrite(data / "ap_export.csv", ",LEASE-01,", ",LEASE-99,")
    with pytest.raises(IngestError, match="unknown lease_id 'LEASE-99'"):
        run(clean, data)


def test_a_mid_month_period_is_refused(clean, generated, tmp_path):
    data = _copy(generated, tmp_path)
    _rewrite(data / "bank_export.csv", "2026-01-01,LEASE-01", "2026-01-15,LEASE-01")
    with pytest.raises(IngestError, match="not the first of a month"):
        run(clean, data)
