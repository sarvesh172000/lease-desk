// Bring the fixture documents in line with the live demo.
//
// Fixtures mode (NEXT_PUBLIC_USE_FIXTURES=1) shows the money screen with the
// same two cases the live demo opens on: the July base-rent under-bill (the
// hidden amendment) and the January CAM over-bill. This script asks the running
// API for those two exceptions and copies what it cites — the invoice line and
// lease clause boxes, the amounts, the PDF bytes and the page renders — into
// public/fixtures/docs and lib/fixtureDocs.json, so a box drawn offline lands
// where the live one does and no fixture amount contradicts the live one.
//
//   make demo-data                                   # a fresh desk
//   node frontend/scripts/sync_fixture_docs.mjs      # API_URL=http://localhost:8000 by default
//
// The amendment email keeps its hand-rendered fixture page (eml_20260618):
// live, the email body is evidence without a page or a box, so there is
// nothing to copy. Nothing here is accounting: it only copies what the API
// said and where it said it was.
import { mkdirSync, readFileSync, rmSync, writeFileSync, existsSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const DOCS = join(here, "..", "public", "fixtures", "docs");
const JSON_OUT = join(here, "..", "lib", "fixtureDocs.json");
const API = (process.env.API_URL || "http://localhost:8000").replace(/\/$/, "");
const EMAIL_ID = "eml_20260618";

// the fixture exception ids, and how to find the same case on the live desk
const CASES = {
  exc_01_jul_amendment: (e) => e.clinic_id === "CLINIC-01" && e.charge_type === "base_rent" && e.period.startsWith("2026-07"),
  exc_01_jan_cam: (e) => e.clinic_id === "CLINIC-01" && e.charge_type === "cam_estimate" && e.period.startsWith("2026-01"),
};

let cookie = "";
async function api(path, init = {}) {
  const r = await fetch(API + path, { ...init, headers: { ...(init.headers ?? {}), cookie } });
  if (!r.ok) throw new Error(`${init.method ?? "GET"} ${path}: ${r.status}`);
  const set = r.headers.get("set-cookie");
  if (set) cookie = set.split(";")[0];
  return r;
}
const json = (path) => api(path).then((r) => r.json());
const bytes = (path) => api(path).then((r) => r.arrayBuffer()).then((b) => Buffer.from(b));

await api("/api/auth/login", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email: "priya.raghunathan@northbaypt.example", password: "demo" }),
});

const previous = JSON.parse(readFileSync(JSON_OUT, "utf8"));
const exceptions = await json("/api/exceptions");
const citations = {};
const documents = { [EMAIL_ID]: previous.documents[EMAIL_ID] };

for (const [fixtureId, match] of Object.entries(CASES)) {
  const row = exceptions.find(match);
  if (!row) throw new Error(`no live exception for ${fixtureId}`);
  const d = await json(`/api/exceptions/${row.exception_id}`);
  if (!d.invoice_line || !d.lease_citation) throw new Error(`${row.exception_id} cites no documents`);
  citations[fixtureId] = { invoice_line: d.invoice_line, lease_citation: d.lease_citation };
  console.log(`${fixtureId} <- ${row.exception_id}: ${d.invoice_line.description} ${d.invoice_line.amount} · ${d.lease_citation.label}`);

  for (const cite of [d.invoice_line, d.lease_citation]) {
    const id = cite.doc_id;
    if (documents[id]) continue;
    const pages = await json(`/api/documents/${id}/pages`);
    const kind = cite === d.invoice_line ? "invoice" : "lease";
    documents[id] = {
      doc_id: id,
      kind: pages.kind ?? kind,
      title: pages.title ?? previous.documents[id]?.title ?? (kind === "invoice" ? `Invoice ${d.period.slice(0, 7)}` : `Lease ${d.lease_id}`),
      pages: pages.pages.map((p) => ({ page: p.number ?? p.page, width: p.width, height: p.height })),
    };
    mkdirSync(join(DOCS, id), { recursive: true });
    writeFileSync(join(DOCS, `${id}.pdf`), await bytes(`/api/documents/${id}/file`));
    for (const p of documents[id].pages) {
      writeFileSync(join(DOCS, id, `${p.page}.png`), await bytes(`/api/documents/${id}/pages/${p.page}.png`));
    }
    console.log(`  ${id.slice(0, 12)}… ${documents[id].pages.length} page(s)`);
  }
}

// documents nothing cites any more are stale copies of an older corpus
for (const name of readdirSync(DOCS)) {
  const id = name.replace(/\.pdf$/, "");
  if (documents[id]) continue;
  rmSync(join(DOCS, name), { recursive: true, force: true });
  console.log(`  removed stale ${name}`);
}

writeFileSync(JSON_OUT, JSON.stringify({ documents, citations }, null, 2) + "\n");
console.log("wrote", JSON_OUT, existsSync(JSON_OUT) ? "" : "(missing!)");
