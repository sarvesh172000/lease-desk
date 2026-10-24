import Link from "next/link";
import type { Metadata } from "next";
import {
  ArrowRight, Blocks, BrainCircuit, Calculator, Database, FileWarning,
  Inbox, Layers, ShieldCheck,
} from "lucide-react";
import { CountUp } from "@/components/data/CountUp";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody } from "@/components/ui/Card";
import { Reveal, Section } from "@/components/welcome/Section";
import { TheMoment } from "@/components/welcome/TheMoment";

export const metadata: Metadata = {
  title: "Lease Desk — the lease accountant's seat",
  description:
    "$443,255.70 of lease liability was missing from the balance sheet. The amendment was in somebody's inbox.",
};

const PROBLEMS = [
  {
    icon: Layers,
    title: "Dozens of leases, each its own rulebook",
    body:
      "Every store, clinic and warehouse has one, with escalations, caps, " +
      "exclusions and a proportionate share that is rarely the obvious one.",
  },
  {
    icon: Inbox,
    title: "The amendment is in somebody's inbox",
    body:
      "It was signed, it went to facilities, the landlord invoiced the new " +
      "amount and AP paid it. Accounting was never told.",
  },
  {
    icon: FileWarning,
    title: "Nobody finds out until audit",
    body:
      "KPMG found that identifying lease changes stayed a persistent problem " +
      "after ASC 842 adoption, with many companies reacting only after the fact.",
  },
];

const PROOF = [
  { value: 476, decimals: 0, label: "tests, every one offline" },
  { value: 5, decimals: 0, label: "of 5 planted errors caught", sub: "0 false holds" },
  { value: 3, decimals: 0, label: "real SEC lease exhibits", sub: "hand-labelled" },
  { value: 184, decimals: 0, label: "real BLS CPI observations" },
  { value: 18, decimals: 0, label: "clinics in a held-out company", sub: "never seen in development" },
];

const STACK = [
  {
    icon: BrainCircuit,
    group: "Reads",
    items: ["Claude claude-opus-5-5", "Structured outputs", "Per-claim citations", "Untrusted-content fencing"],
    note: "Messy PDFs, scanned faxes and email threads — the only job a model is given.",
  },
  {
    icon: Calculator,
    group: "Computes",
    items: ["Python 3.13", "ASC 842 engines", "CAM pools & CPI", "476 tests"],
    note: "Every schedule, balance and journal entry. Deterministic, and reproducible to the cent.",
  },
  {
    icon: Database,
    group: "Remembers",
    items: ["PostgreSQL 16", "Hash-chained audit", "Four database roles", "Event-sourced work"],
    note: "The agent process physically cannot write to the ledger. It is a grant, not a policy.",
  },
  {
    icon: Blocks,
    group: "Shows",
    items: ["Next.js 15", "TypeScript", "Tailwind", "TanStack Query"],
    note: "The UI formats and asserts. It does no lease accounting of its own.",
  },
];

export default function WelcomePage() {
  return (
    <main className="relative">
      {/* A single slow gradient. No particles, no parallax. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-40 left-1/2 h-[42rem] w-[72rem] -translate-x-1/2 animate-drift rounded-full bg-accent/10 blur-[120px]" />
        <div className="absolute right-0 top-[38rem] h-[30rem] w-[40rem] rounded-full bg-esc/5 blur-[120px]" />
      </div>

      {/* ---- Hero: lead with the money ---- */}
      <section className="relative mx-auto w-full max-w-6xl px-6 pb-20 pt-24 md:pt-32">
        <Reveal>
          <Badge tone="accent" dot>Cal Hacks 13.0 · autonomous lease accounting</Badge>
        </Reveal>

        <Reveal delay={0.05}>
          <h1 className="mt-8 text-display font-semibold">
            <CountUp value={443255.7} prefix="$" className="text-accent" />
            <span className="block text-ink">was missing from the balance sheet.</span>
          </h1>
        </Reveal>

        <Reveal delay={0.12}>
          <p className="mt-8 max-w-2xl text-xl leading-relaxed text-ink-soft">
            Nobody knew. A lease had been amended nine months earlier, the landlord
            billed the new amount, and the books kept running the old schedule.
          </p>
          <p className="mt-4 max-w-2xl text-lg leading-relaxed text-ink-muted">
            <strong className="font-medium text-ink">Lease Desk</strong> fills the lease
            accountant&rsquo;s seat. It reads every lease, checks every landlord bill
            against what the lease actually says, and holds only the money that is
            wrong — showing the invoice line and the lease clause side by side.
          </p>
        </Reveal>

        <Reveal delay={0.18}>
          <div className="mt-10 flex flex-wrap items-center gap-3">
            <Link
              href="/login"
              className="inline-flex h-12 items-center gap-2 rounded-sm bg-accent px-6 font-medium text-accent-ink shadow-raised transition-all duration-fast ease-out hover:bg-accent-strong hover:shadow-glow active:translate-y-px"
            >
              Open the app <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
            <a
              href="#moment"
              className="inline-flex h-12 items-center gap-2 rounded-sm border border-line bg-raised px-6 font-medium text-ink transition-colors duration-fast ease-out hover:border-line-strong hover:bg-surface"
            >
              See how it works
            </a>
          </div>
        </Reveal>

        <Reveal delay={0.24}>
          <p className="mt-12 flex items-center gap-2 text-sm text-ink-faint">
            <ShieldCheck className="h-4 w-4 text-accent" aria-hidden />
            It never pays and never signs off. A human approves, and every action is
            written to a tamper-evident history.
          </p>
        </Reveal>
      </section>

      <div className="rule-soft" />

      {/* ---- The problem ---- */}
      <Section
        eyebrow="The problem"
        title="The schedule is only right until someone signs an amendment"
        lead="Lease accounting does not break because the maths is hard. It breaks because the source of truth is not in any system."
      >
        <div className="grid gap-5 md:grid-cols-3">
          {PROBLEMS.map((p, i) => {
            const Icon = p.icon;
            return (
              <Reveal key={p.title} delay={i * 0.08}>
                <Card className="h-full">
                  <CardBody>
                    <Icon className="h-5 w-5 text-accent" aria-hidden />
                    <h3 className="mt-4 font-semibold tracking-tight">{p.title}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-ink-muted">{p.body}</p>
                  </CardBody>
                </Card>
              </Reveal>
            );
          })}
        </div>
      </Section>

      {/* ---- The moment ---- */}
      <Section
        id="moment"
        eyebrow="The moment"
        title="One store, four steps, $443,255.70"
        lead="Every figure below is produced by the running system, not written into this page."
      >
        <Reveal><TheMoment /></Reveal>
      </Section>

      {/* ---- The principle ---- */}
      <Section className="py-20 md:py-28">
        <Reveal>
          <div className="rounded-lg border border-line bg-surface p-8 md:p-12">
            <h2 className="text-headline font-semibold">
              The model reads.{" "}
              <span className="text-accent">The code calculates.</span>
            </h2>
            <div className="mt-10 grid gap-10 md:grid-cols-2">
              <div>
                <div className="eyebrow mb-3">What Claude does</div>
                <p className="leading-relaxed text-ink-soft">
                  Reads a lease PDF, a scanned amendment or an email thread and returns
                  structured terms — each carrying the exact sentence it came from, and
                  an explicit list of what it could not determine.
                </p>
              </div>
              <div>
                <div className="eyebrow mb-3">What the code does</div>
                <p className="leading-relaxed text-ink-soft">
                  Every schedule, every balance, every journal entry. Ordinary
                  arithmetic with a test suite, reproducible to the cent, identical on
                  every run.
                </p>
              </div>
            </div>
            <p className="mt-10 border-t border-line pt-6 text-lg leading-relaxed">
              No balance, schedule row or journal entry is ever produced by a language
              model. That is what makes a wrong extraction a{" "}
              <strong className="font-medium text-accent">reviewable error</strong>{" "}
              instead of a silently wrong balance sheet.
            </p>
          </div>
        </Reveal>
      </Section>

      {/* ---- Proof ---- */}
      <Section
        eyebrow="How we know"
        title="Checked against things we did not write"
        lead="A generator and the system that reads it drift toward each other. These are the measurements that do not."
      >
        <div className="grid gap-px overflow-hidden rounded-md border border-line bg-line sm:grid-cols-2 lg:grid-cols-5">
          {PROOF.map((p, i) => (
            <Reveal key={p.label} delay={i * 0.05} className="bg-surface">
              <div className="h-full p-6">
                <div className="text-4xl font-semibold tracking-tight text-accent">
                  <CountUp value={p.value} decimals={p.decimals} />
                </div>
                <div className="mt-3 text-sm leading-snug text-ink-soft">{p.label}</div>
                {p.sub ? <div className="mt-1 text-xs text-ink-faint">{p.sub}</div> : null}
              </div>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* ---- Stack ---- */}
      <Section
        eyebrow="Technology"
        title="Four jobs, and what does each one"
        lead="Grouped by what it is for, because a logo wall says nothing about whether a system works."
      >
        <div className="grid gap-5 md:grid-cols-2">
          {STACK.map((s, i) => {
            const Icon = s.icon;
            return (
              <Reveal key={s.group} delay={i * 0.06}>
                <Card className="h-full">
                  <CardBody>
                    <div className="flex items-center gap-3">
                      <span className="grid h-9 w-9 place-items-center rounded-sm border border-accent/30 bg-accent-soft text-accent">
                        <Icon className="h-4 w-4" aria-hidden />
                      </span>
                      <h3 className="text-lg font-semibold tracking-tight">{s.group}</h3>
                    </div>
                    <ul className="mt-5 flex flex-wrap gap-2">
                      {s.items.map((it) => (
                        <li
                          key={it}
                          className="rounded-full border border-line bg-raised px-3 py-1 font-mono text-2xs text-ink-soft"
                        >
                          {it}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-5 text-sm leading-relaxed text-ink-muted">{s.note}</p>
                  </CardBody>
                </Card>
              </Reveal>
            );
          })}
        </div>
      </Section>

      {/* ---- Close ---- */}
      <Section className="pb-32">
        <Reveal>
          <div className="rounded-lg border border-accent/25 bg-accent-soft/40 p-10 text-center md:p-14">
            <h2 className="text-headline font-semibold">
              It is looking for the next one right now.
            </h2>
            <p className="mx-auto mt-4 max-w-xl leading-relaxed text-ink-soft">
              One store found $443,255.70. The same run covers every lease, every
              month, and asks a human the moment it is unsure.
            </p>
            <Link
              href="/login"
              className="mt-8 inline-flex h-12 items-center gap-2 rounded-sm bg-accent px-7 font-medium text-accent-ink shadow-raised transition-all duration-fast ease-out hover:bg-accent-strong hover:shadow-glow active:translate-y-px"
            >
              Open the app <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </div>
        </Reveal>

        <Reveal delay={0.1}>
          <footer className="mt-16 flex flex-col items-center gap-3 text-sm text-ink-faint">
            <a
              href="https://github.com/sarvesh172000/lease-desk"
              className="transition-colors hover:text-ink-soft"
            >
              github.com/sarvesh172000/lease-desk
            </a>
            <p>Built at Cal Hacks 13.0 by Sarvesh Waghmare and Jenil.</p>
          </footer>
        </Reveal>
      </Section>
    </main>
  );
}
