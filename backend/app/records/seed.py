"""`make seed`: load the generated company into the database.

    python -m app.records.seed [--data data/generated]

Two steps, each under the role the architecture assigns it, each one
transaction:

  1. **Ingest** as `lease_agent`: documents and CSV rows into the raw layer.
  2. **Standardize** as `lease_gateway`: org chart, leases, charges, payments,
     chart of accounts and open periods into the golden and ledger tables.

Idempotent: a second run adds nothing. A bad input fails with the file, line
or raw row named, and that step's transaction rolls back whole.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from ..db import models as m
from ..db.engine import engine
from ..ledger.chart import install_chart, open_periods
from ..settings import get_settings
from .golden import load_actors, load_leases, load_org, standardize_charges, standardize_payments
from .ingest import IngestError, ingest_all

COUNTED = (m.source_document, m.raw_row, m.clinic, m.actor, m.lease, m.landlord_charge,
           m.payment, m.account, m.period)


def table_counts(eng: Engine) -> dict:
    with eng.connect() as conn:
        return {t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
                for t in COUNTED}


def seed(data_dir: Path, agent: Engine, gateway: Engine) -> dict:
    """Returns how many rows each table holds after the seed, and how many of
    them this run added."""
    # Imported here so the API process never loads the generator.
    from datagen.company import build_company
    from datagen.leases import build_leases

    if not data_dir.is_dir():
        raise IngestError("no data directory at %s; run `python -m datagen.build` first" % data_dir)

    before = table_counts(gateway)
    with agent.begin() as conn:
        ingest_all(conn, data_dir)

    company = build_company()
    with gateway.begin() as conn:
        load_org(conn, company)
        load_actors(conn, company)
        load_leases(conn, build_leases(company))
        standardize_charges(conn)
        standardize_payments(conn)
        install_chart(conn, company.entity.entity_id)
        first, last = conn.execute(
            select(func.min(m.landlord_charge.c.period), func.max(m.landlord_charge.c.period))
        ).one()
        if first is None:
            raise IngestError("no landlord charges were standardized; the AP export is empty")
        open_periods(conn, company.entity.entity_id,
                     date(first.year, 1, 1), date(last.year, 12, 1))

    after = table_counts(gateway)
    return {name: {"total": after[name], "added": after[name] - before[name]} for name in after}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Load the generated company into Postgres")
    parser.add_argument("--data", default=get_settings().data_dir)
    args = parser.parse_args(argv)
    try:
        counts = seed(Path(args.data), engine("lease_agent"), engine("lease_gateway"))
    except IngestError as exc:
        print("seed failed: %s" % exc, file=sys.stderr)
        return 2
    for name, c in counts.items():
        print("  %-16s %5d  (+%d)" % (name, c["total"], c["added"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
