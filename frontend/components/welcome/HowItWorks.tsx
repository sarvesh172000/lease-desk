"use client";

import { motion, useReducedMotion } from "framer-motion";
import { BookOpen, Database, Link2, PauseCircle, Scale, UserCheck } from "lucide-react";
import { Reveal, Section } from "./Section";

const STEPS = [
  { icon: BookOpen, label: "Read", body: "Leases, amendments, landlord bills and the mailbox. Claude returns terms with the sentence each came from." },
  { icon: Scale, label: "Check", body: "Every charge against the schedule the lease implies. Ordinary arithmetic, reproducible to the cent." },
  { icon: PauseCircle, label: "Hold", body: "Only what is wrong, with the invoice line and the clause boxed on the page. The rest pays." },
  { icon: UserCheck, label: "A person approves", body: "Controller or regional manager. Never the agent, and never the person who answered its question." },
  { icon: Database, label: "The gateway posts", body: "The one database role that may write the ledger. The agent's role is refused by Postgres itself." },
  { icon: Link2, label: "The chain seals it", body: "Every event hashed to the one before it. Anyone can verify; an edit shows as a break." },
] as const;

export function HowItWorks() {
  const reduce = useReducedMotion();
  return (
    <Section
      id="how"
      eyebrow="How it works"
      title="Read, check, hold. Then a person, then the gateway, then the chain."
      lead="The model reads. The code calculates. The database decides who may write. Each step leaves a record the next one cannot alter."
    >
      <ol className="relative grid gap-6 md:grid-cols-3 lg:grid-cols-6 lg:gap-4">
        {STEPS.map((s, i) => {
          const Icon = s.icon;
          return (
            <Reveal key={s.label} delay={i * 0.08}>
              <li className="relative h-full">
                {i < STEPS.length - 1 ? (
                  <svg aria-hidden className="absolute -right-3 top-5 hidden h-px w-6 overflow-visible text-line-strong lg:block" viewBox="0 0 24 1" preserveAspectRatio="none">
                    <motion.line
                      x1="0" y1="0.5" x2="24" y2="0.5"
                      stroke="currentColor" strokeWidth="1"
                      initial={reduce ? false : { pathLength: 0 }}
                      whileInView={{ pathLength: 1 }}
                      viewport={{ once: true }}
                      transition={{ duration: 0.4, delay: 0.3 + i * 0.08 }}
                    />
                  </svg>
                ) : null}
                <div className="flex h-full flex-col rounded-md border border-line bg-surface p-4">
                  <div className="flex items-center gap-2.5">
                    <span className="grid h-9 w-9 place-items-center rounded-sm border border-accent/30 bg-accent-soft text-accent">
                      <Icon aria-hidden className="h-4 w-4" />
                    </span>
                    <span className="font-mono text-2xs text-ink-faint">0{i + 1}</span>
                  </div>
                  <h3 className="mt-3 font-semibold tracking-tight">{s.label}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{s.body}</p>
                </div>
              </li>
            </Reveal>
          );
        })}
      </ol>
    </Section>
  );
}
