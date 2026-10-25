"use client";

import { Reveal, Section } from "./Section";

/** Every track the project is entered in, and the one job each piece does here. */
const TECH = [
  { name: "Claude", by: "Anthropic", job: "Reads the documents: leases, amendments, bills, emails. Returns terms with the sentence each came from, and says what it could not find.", where: "backend/app/agents" },
  { name: "Fetch.ai · ASI:One", by: "uAgents on Agentverse", job: "The whole desk inside an ASI:One chat, as yourself, under the same permissions as the web app. Four agents.", where: "agents_fetch/" },
  { name: "SpacetimeDB", by: "live mirror", job: "Every committed approval mirrored live, so other screens update with no refresh. Postgres stays the system of record.", where: "spacetime/" },
  { name: "Azure", by: "deployment", job: "Where the stack runs for the demo: API, worker, database and this web app.", where: "ops/" },
  { name: "Postgres", by: "roles · hash chain", job: "Four roles with exact grants. The agent's role cannot write the ledger; the audit table is hash-chained and verified on request.", where: "backend/app/db" },
  { name: "Python · FastAPI", by: "engines and API", job: "ASC 842 schedules, CAM pools, CPI, remeasurement, journal entries. Deterministic, with a test suite.", where: "backend/" },
  { name: "Next.js", by: "this web app", job: "Formats and asserts what the API says. Does no lease accounting of its own.", where: "frontend/" },
];

export function TechStrip() {
  return (
    <Section
      id="built"
      eyebrow="Built with"
      title="Seven pieces, one job each"
      lead="Grouped by what each is for. A logo says nothing about whether a system works; the job it does here says something."
    >
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="tech-strip">
        {TECH.map((t, i) => (
          <Reveal key={t.name} delay={i * 0.05} className="h-full lg:last:col-span-2">
            <li className="flex h-full flex-col rounded-md border border-line bg-surface p-5">
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="font-semibold tracking-tight">{t.name}</h3>
                <span className="font-mono text-2xs text-ink-faint">{t.by}</span>
              </div>
              <p className="mt-2 flex-1 text-sm leading-relaxed text-ink-muted">{t.job}</p>
              <code className="mt-4 text-2xs text-ink-faint">{t.where}</code>
            </li>
          </Reveal>
        ))}
      </ul>
    </Section>
  );
}
