"""Write the engine-backed fixtures the UI needs beyond the frozen §16 JSON.

§16 freezes the money-screen JSON but not the rows behind
`GET /api/leases/{id}/schedule?version=`, and its `GET /api/leases` fixture has
one lease. Rather than invent numbers, this runs the real deterministic engine
(`leasedesk/`) and dumps its output verbatim:

* ``lib/fixtureSchedules.json`` — LEASE-01 (the sample lease whose liability is
  $559,665.35 in §16) schedule v1 (original) and v2 (post-amendment).
* ``lib/fixturePortfolio.json`` — LEASE-02..05 from a datagen corpus, in the
  §16 `GET /api/leases` shape, liability = carrying balance at 2026-06-30 (the
  same as-of the §16 LEASE-01 row uses). Status is ``balanced``: this script
  does not read the answer key.

    python -m datagen.build --out /tmp/gen
    python3 frontend/scripts/build_fixture_engine.py /tmp/gen

Run from the repo root.
"""

import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from leasedesk.models import load_lease  # noqa: E402
from leasedesk.remeasure import remeasure  # noqa: E402
from leasedesk.schedule import build  # noqa: E402

BOOKS_CLOSED_THROUGH = date(2026, 9, 1)  # same as leasedesk/cli.py
EFFECTIVE = date(2026, 7, 1)
AS_OF = date(2026, 6, 30)


def dump(schedule, version, effective_from, active):
    rows = []
    for p in schedule.periods:
        row = asdict(p)
        row["period"] = p.period.isoformat()
        rows.append(row)
    return {
        "lease_id": "LEASE-01",
        "version": version,
        "effective_from": effective_from,
        "active": active,
        "opening_liability": schedule.opening_liability,
        "opening_rou": schedule.opening_rou,
        "rows": rows,
    }


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    gen = Path(sys.argv[1])
    out_dir = ROOT / "frontend" / "lib"

    lease = load_lease(str(ROOT / "data" / "leases" / "store-14.json"))
    r = remeasure(lease, effective=EFFECTIVE, through=BOOKS_CLOSED_THROUGH)
    assert r.liability_before == 559665.35 and r.liability_after == 1002921.05, (r.liability_before, r.liability_after)
    schedules = {
        "LEASE-01": {
            "1": dump(r.old, 1, lease.commencement.isoformat(), True),
            "2": dump(r.new, 2, EFFECTIVE.isoformat(), False),
        }
    }
    (out_dir / "fixtureSchedules.json").write_text(json.dumps(schedules, indent=1) + "\n")

    manifest = json.loads((gen / "manifest.json").read_text())
    portfolio = []
    for entry in manifest["leases"]:
        if entry["lease_id"] == "LEASE-01":
            continue  # §16 fixture row is used verbatim
        terms = load_lease(str(gen / "leases" / ("%s.json" % entry["lease_id"].lower())))
        bal = build(terms).balances_at(AS_OF)
        portfolio.append({
            "lease_id": terms.lease_id,
            "clinic_id": entry["clinic_id"],
            "location": terms.location,
            "lessor": terms.lessor,
            "status": "balanced",
            "monthly_rent": round(terms.rent_for(date(2026, 6, 1)), 2),
            "liability": bal["liability"],
            "end": terms.end.isoformat(),
        })
    (out_dir / "fixturePortfolio.json").write_text(json.dumps(portfolio, indent=1, ensure_ascii=False) + "\n")
    print("wrote schedules (%d + %d rows) and %d portfolio rows" % (len(r.old.periods), len(r.new.periods), len(portfolio)))


if __name__ == "__main__":
    main()
