"""Generate the corpus: lease PDFs into the content-addressed store, terms as
JSON the engine can load.

    python -m datagen.build --out data/generated

Deterministic: same seed, same bytes, same sha256. Re-running overwrites
nothing in the store because the key is the content.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.docs.pipeline import extract  # noqa: E402
from app.docs.storage import LocalStorage  # noqa: E402

from .company import build_company  # noqa: E402
from .leases import build_leases  # noqa: E402
from .month import (  # noqa: E402
    build_month, build_payments, write_ap_export, write_bank_export,
)
from .render_invoice import render_invoice  # noqa: E402
from .render_lease import render_lease  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate the Northbay corpus")
    parser.add_argument("--out", default="data/generated")
    parser.add_argument("--month", default="2026-01",
                        help="billing month to generate, YYYY-MM")
    args = parser.parse_args(argv)
    period = date(int(args.month[:4]), int(args.month[5:7]), 1)

    out = Path(args.out)
    store = LocalStorage(out / "documents")
    (out / "leases").mkdir(parents=True, exist_ok=True)

    company = build_company()
    manifest = {"company": company.entity.name, "seed": company.seed, "leases": []}

    print("%-10s %-11s %-9s %5s %6s  %s" % ("LEASE", "CLINIC", "PAGES", "WORDS", "KB", "SHA256"))
    for terms in build_leases(company):
        pdf = render_lease(terms, company)
        sha = store.put(pdf)
        doc = extract(pdf, sha256=sha)

        engine_json = terms.to_engine_json(company)
        (out / "leases" / ("%s.json" % terms.lease_id.lower())).write_text(
            json.dumps(engine_json, indent=2) + "\n"
        )
        manifest["leases"].append({
            "lease_id": terms.lease_id,
            "clinic_id": terms.clinic_id,
            "document_sha256": sha,
            "pages": doc.page_count,
        })
        print("%-10s %-11s %-9d %5d %6.1f  %s"
              % (terms.lease_id, terms.clinic_id, doc.page_count,
                 sum(len(p.words) for p in doc.pages), len(pdf) / 1024, sha[:16]))

    # --- the billing month --------------------------------------------
    leases = build_leases(company)
    invoices = build_month(period, company, leases)
    payments = build_payments(invoices, company)

    (out / "invoices").mkdir(parents=True, exist_ok=True)
    print()
    print("%-18s %-11s %-9s %10s  %s" % ("INVOICE", "CLINIC", "CHARGES", "TOTAL", "SHA256"))
    manifest["invoices"] = []
    for invoice in invoices:
        pdf = render_invoice(invoice, company)
        sha = store.put(pdf)
        invoice.document_sha256 = sha
        (out / "invoices" / ("%s.pdf" % invoice.invoice_id)).write_bytes(pdf)
        manifest["invoices"].append({
            "invoice_id": invoice.invoice_id,
            "clinic_id": invoice.clinic_id,
            "period": invoice.period.isoformat(),
            "total": invoice.total(),
            "document_sha256": sha,
        })
        print("%-18s %-11s %-9d %10s  %s"
              % (invoice.invoice_id, invoice.clinic_id, len(invoice.charges),
                 "{:,.2f}".format(invoice.total()), sha[:16]))

    write_ap_export(invoices, out / "ap_export.csv")
    write_bank_export(payments, out / "bank_export.csv")
    manifest["period"] = period.isoformat()
    manifest["invoice_total"] = round(sum(i.total() for i in invoices), 2)

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print()
    print("%d leases, %d invoices, %d bank lines, $%s billed for %s -> %s"
          % (len(manifest["leases"]), len(invoices), len(payments),
             "{:,.2f}".format(manifest["invoice_total"]),
             period.strftime("%B %Y"), out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
