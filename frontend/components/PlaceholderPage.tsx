"use client";

import { motion, useReducedMotion } from "framer-motion";
import {
  BookMarked,
  CalendarClock,
  CalendarRange,
  MailWarning,
  MessageSquareText,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

const ICONS = {
  month: CalendarRange,
  exceptions: TriangleAlert,
  questions: MessageSquareText,
  obligations: CalendarClock,
  disputes: MailWarning,
  policies: BookMarked,
} satisfies Record<string, LucideIcon>;

export interface PlaceholderPageProps {
  icon: keyof typeof ICONS;
  eyebrow: string;
  title: string;
  /** One sentence: what this screen is for. */
  lead: string;
  /** What will appear here, in the order a person reads it. */
  shows: { label: string; detail: string }[];
  /** Where to go meanwhile. */
  meanwhile?: { href: string; label: string };
}

/**
 * A screen whose data the API already serves but whose design is not built
 * yet. It says what will appear and why it is empty, never a blank panel.
 */
export function PlaceholderPage({ icon, eyebrow, title, lead, shows, meanwhile }: PlaceholderPageProps) {
  const Icon = ICONS[icon];
  const reduce = useReducedMotion();
  return (
    <div className="space-y-6">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1 className="mt-1 text-2xl font-semibold">{title}</h1>
        <p className="mt-1 max-w-2xl text-ink-soft">{lead}</p>
      </div>

      <section
        aria-labelledby="placeholder-title"
        className="relative overflow-hidden rounded-md border border-dashed border-line-strong bg-surface/60 px-8 py-10"
      >
        <div className="flex items-start gap-6">
          <span aria-hidden className="flex h-12 w-12 shrink-0 items-center justify-center rounded-sm border border-line bg-raised text-accent">
            <Icon className="h-6 w-6" strokeWidth={1.75} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-3">
              <h2 id="placeholder-title" className="text-lg font-semibold">
                This screen is being designed
              </h2>
              <span className="rounded-xs border border-esc-line bg-esc-soft px-2 py-0.5 text-2xs font-semibold uppercase tracking-wide text-esc">
                Next
              </span>
            </div>
            <p className="mt-1 text-sm text-ink-muted">
              The data behind it is already served by the API. Here is what will appear:
            </p>
            <ol className="mt-5 grid grid-cols-2 gap-3">
              {shows.map((s, i) => (
                <motion.li
                  key={s.label}
                  initial={reduce ? false : { opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2, delay: reduce ? 0 : 0.04 * i, ease: [0.2, 0.8, 0.2, 1] }}
                  className="flex gap-3 rounded-sm border border-line bg-bg/40 px-4 py-3"
                >
                  <span aria-hidden className="num mt-0.5 text-xs font-semibold text-ink-faint">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="flex flex-col">
                    <span className="text-sm font-medium text-ink">{s.label}</span>
                    <span className="text-sm text-ink-muted">{s.detail}</span>
                  </span>
                </motion.li>
              ))}
            </ol>
            {meanwhile ? (
              <Link href={meanwhile.href} className="mt-6 inline-flex text-sm font-medium text-accent hover:underline">
                {meanwhile.label} →
              </Link>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}
