// Build public/proof.json from real runs, so the welcome page never carries a
// figure that was typed in. Every number it shows offline comes from here, and
// the page says when and by what each one was measured.
//
//   cd ..                                   # repository root
//   make eval                               # writes eval/report.json
//   make prove-limits > /tmp/limits.log     # the three refused actions
//   cd frontend
//   node scripts/proof.mjs --limits /tmp/limits.log \
//     --backend "$(cd .. && .venv/bin/python -m pytest --collect-only -q | awk -F': ' '/: [0-9]+$/{s+=$NF} END{print s}')" \
//     --frontend "$(npx vitest run 2>&1 | sed -n 's/.*Tests *\([0-9]*\) passed.*/\1/p')"
//
// Nothing here is computed: the script copies what the runs reported.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1]]] : acc), []),
);

const report = JSON.parse(readFileSync(join(root, "eval", "report.json"), "utf8"));
const s = report.sections;
const checking = s.checking.detail;
const investigation = s.investigation.detail;

// "  (c) seq 260    agent:checker  post     refused by Postgres  database refused: ..."
const limits = args.limits ? readFileSync(args.limits, "utf8") : "";
const refusals = [...limits.matchAll(/\(\w\)\s+seq (\d+)\s+(\S+)\s+(\S+)\s+refused by (\S+(?: \S+)?)\s{2,}(.+)$/gm)].map((m) => ({
  seq: Number(m[1]),
  actor_id: m[2],
  action: m[3],
  refused_by: m[4].trim(),
  reason: m[5].trim(),
}));
const chainOk = /verify_chain\(\): OK/.test(limits);

const proof = {
  eval: {
    measured_at: report.at,
    by: "make eval",
    seed: report.seed,
    passed: report.passed,
    charges_checked: checking.charges_checked,
    held: checking.held,
    planted: checking.caught.length + checking.missed.length,
    caught: checking.caught.length,
    missed: checking.missed.length,
    false_holds: checking.false_holds.length,
    dollars_flagged: checking.dollars_flagged,
    dollars_expected: checking.dollars_expected,
    citations_correct: checking.citations_correct,
    sources_searched: investigation.searched,
    sources_refused: s.safety.detail.sources_refused.length,
    confidence: investigation.confidence,
    entries_balance: investigation.checks.entries_balance,
    never_posts_alone: investigation.checks.never_posts_alone,
    held_out_clinics: s.held_out.detail.clinics,
  },
  limits: refusals.length
    ? { measured_at: new Date().toISOString(), by: "make prove-limits", refusals, chain_verified: chainOk }
    : null,
  tests: {
    counted_at: new Date().toISOString(),
    backend: args.backend ? Number(args.backend) : null,
    frontend: args.frontend ? Number(args.frontend) : null,
  },
};

const out = join(here, "..", "public", "proof.json");
writeFileSync(out, JSON.stringify(proof, null, 2) + "\n");
console.log("wrote", out);
