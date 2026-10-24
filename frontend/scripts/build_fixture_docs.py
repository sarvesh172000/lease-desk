"""Build the PDF assets the fixtures-mode money screen renders.

The §16 fixtures cite documents by id and box but ship no bytes. This script
takes a datagen corpus (January and July 2026), copies the three documents the
fixture exceptions point at into ``public/fixtures/docs/``, renders the
amendment email to a one-page PDF so the frozen evidence box
``[85.0, 125.3, 527.0, 152.1]`` lands on the quoted sentence, and writes every
box it found to ``lib/fixtureDocs.json``.

    python -m datagen.build --out /tmp/gen   --month 2026-01
    python -m datagen.build --out /tmp/gen07 --month 2026-07
    python3 frontend/scripts/build_fixture_docs.py /tmp/gen /tmp/gen07

Boxes are ``[x0, y0, x1, y1]`` in PDF points, origin top-left, the same
convention as §16. Nothing here is accounting: it only locates text.
"""

import json
import shutil
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import fitz  # noqa: E402  (PyMuPDF)

HERE = Path(__file__).resolve().parent.parent
OUT_DOCS = HERE / "public" / "fixtures" / "docs"
OUT_JSON = HERE / "lib" / "fixtureDocs.json"

EMAIL_QUOTE = "Base rent reduced to $17,400 per month effective July 1, 2026."
EMAIL_BOX = (85.0, 125.3, 527.0, 152.1)  # frozen in DESIGN.md §16


def find_doc(gen: Path, sha_prefix: str) -> Path:
    hits = list((gen / "documents").rglob(sha_prefix + "*"))
    if not hits:
        sys.exit("no document %s under %s" % (sha_prefix, gen))
    return hits[0]


def manifest(gen: Path) -> dict:
    return json.loads((gen / "manifest.json").read_text())


def union(rects, pad=3.0):
    r = fitz.Rect(rects[0])
    for x in rects[1:]:
        r |= x
    return [round(r.x0 - pad, 1), round(r.y0 - pad, 1), round(r.x1 + pad, 1), round(r.y1 + pad, 1)]


def row_box(page, label: str, amount: str):
    """Box an invoice row from its description to its amount."""
    a = page.search_for(label)
    b = [r for r in page.search_for(amount) if a and abs(r.y0 - a[0].y0) < 4]
    if not a or not b:
        sys.exit("row not found: %r %r" % (label, amount))
    return union([a[0], b[0]])


def text_box(page, text: str):
    hits = page.search_for(text)
    if not hits:
        sys.exit("text not found: %r" % text)
    return union(hits, pad=2.0)


def page_size(doc):
    return [{"page": i + 1, "width": p.rect.width, "height": p.rect.height} for i, p in enumerate(doc)]


def render_email(path: Path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    mono = "cour"
    y = 40
    for line in [
        "From:    dana.reyes@serramonteretail.example",
        "To:      ap@northbay-clinics.example",
        "Cc:      facilities@northbay-clinics.example",
        "Date:    Thu, 18 Jun 2026 16:41:02 -0700",
        "Subject: RE: RE: Store 14 renewal - executed copy attached",
    ]:
        page.insert_text((60, y), line, fontname=mono, fontsize=8.5)
        y += 11
    page.draw_line((60, y - 4), (552, y - 4), color=(0.75, 0.75, 0.75), width=0.5)
    y += 6
    for line in [
        "Hi team, attaching the countersigned Second Amendment for Store 14",
        "(Serramonte). To recap what we agreed on the call:",
    ]:
        page.insert_text((60, y), line, fontname="helv", fontsize=9.5)
        y += 12
    # the quoted sentence sits exactly in the frozen fixture box
    x0, y0, x1, y1 = EMAIL_BOX
    page.insert_text((70, y0 + 17), "-", fontname="helv", fontsize=11)
    page.insert_text((x0 + 4, y0 + 17), EMAIL_QUOTE, fontname="helv", fontsize=11)
    y = y1 + 16
    for line in [
        "  -  Term extended three (3) years, new expiration 12/31/2031.",
        "  -  Annual escalation drops from 3.0% to 2.5%, first bump 7/1/2027.",
        "  -  All other terms of the Original Lease and First Amendment unchanged.",
        "",
        "Please route the July ACH at the new amount so we don't have to true up.",
        "",
        "Thanks,",
        "Dana Reyes",
        "Serramonte Retail Partners LLC",
        "",
        "> On Jun 11, 2026, at 9:02 AM, facilities@northbay-clinics.example wrote:",
        "> Dana - confirming we want the extension. Sending to legal today.",
    ]:
        page.insert_text((60, y), line, fontname="helv", fontsize=10)
        y += 14
    doc.save(path, garbage=4, deflate=True)
    doc.close()


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    jan, jul = Path(sys.argv[1]), Path(sys.argv[2])
    OUT_DOCS.mkdir(parents=True, exist_ok=True)

    lease_sha = next(l["document_sha256"] for l in manifest(jan)["leases"] if l["lease_id"] == "LEASE-01")
    inv_jan_sha = next(i["document_sha256"] for i in manifest(jan)["invoices"] if i["invoice_id"] == "SERRA-202601-0001")
    inv_jul_sha = next(i["document_sha256"] for i in manifest(jul)["invoices"] if i["invoice_id"] == "SERRA-202607-0001")

    docs = {}

    def add(doc_id, src, kind, title):
        shutil.copyfile(src, OUT_DOCS / (doc_id + ".pdf"))
        d = fitz.open(OUT_DOCS / (doc_id + ".pdf"))
        docs[doc_id] = {"doc_id": doc_id, "kind": kind, "title": title, "pages": page_size(d)}
        return d

    lease = add(lease_sha, find_doc(jan, lease_sha), "lease", "Office Lease Agreement — LEASE-01")
    jan_doc = add(inv_jan_sha, find_doc(jan, inv_jan_sha), "invoice", "Invoice SERRA-202601-0001")
    jul_doc = add(inv_jul_sha, find_doc(jul, inv_jul_sha), "invoice", "Invoice SERRA-202607-0001")

    eml_path = OUT_DOCS / "eml_20260618.pdf"
    render_email(eml_path)
    eml = fitz.open(eml_path)
    docs["eml_20260618"] = {"doc_id": "eml_20260618", "kind": "email",
                            "title": "RE: RE: Store 14 renewal - executed copy attached",
                            "pages": page_size(eml)}
    assert EMAIL_QUOTE in eml[0].get_textbox(fitz.Rect(*EMAIL_BOX)).replace("\n", " ")

    out = {
        "documents": docs,
        "citations": {
            "exc_01_jul_amendment": {
                "invoice_line": {"doc_id": inv_jul_sha, "page": 1,
                                 "box": row_box(jul_doc[0], "Base Rent — July 2026", "$19,626.65"),
                                 "description": "Base Rent — July 2026", "amount": 19626.65},
                "lease_citation": {"doc_id": lease_sha, "page": 3,
                                   "box": row_box(lease[2], "Jan 1, 2026 – Dec 31, 2026", "$19,626.65"),
                                   "label": "§3.1 Base Rent Schedule, lease year 3",
                                   "quote": "Jan 1, 2026 – Dec 31, 2026 $19,626.65"},
            },
            "exc_01_jan_cam": {
                "invoice_line": {"doc_id": inv_jan_sha, "page": 1,
                                 "box": row_box(jan_doc[0], "Operating Expense Estimate — January 2026", "$6,458.33"),
                                 "description": "Operating Expense Estimate — January 2026", "amount": 6458.33},
                "lease_citation": {"doc_id": lease_sha, "page": 4,
                                   "box": text_box(lease[3], "payable in monthly installments of $5,941.67"),
                                   "label": "§4.1 Estimated Operating Expenses",
                                   "quote": "Landlord’s current estimate of Operating Expenses is $11.50 per rentable square foot per annum, payable in monthly installments of $5,941.67 concurrently with Base Rent."},
            },
        },
    }
    # the CAM clause spans two lines; box both
    out["citations"]["exc_01_jan_cam"]["lease_citation"]["box"] = union(
        lease[3].search_for("Landlord’s current estimate of Operating Expenses")
        + lease[3].search_for("payable in monthly installments of $5,941.67"), pad=2.0)
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print("wrote", OUT_JSON)
    for k in docs:
        print(" ", k[:20], docs[k]["kind"], docs[k]["pages"][0])


if __name__ == "__main__":
    main()
