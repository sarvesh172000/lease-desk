"use client";

import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { money, signedMoney } from "@/lib/format";
import { useException } from "@/lib/hooks";
import { chargeLabel, clinicLabel, monthLong } from "@/lib/labels";
import type { ExceptionSummary, LeaseSummary } from "@/lib/types";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight, Play } from "lucide-react";
import Link from "next/link";

/**
 * The one open item that matters most this month: in the business month if
 * any is open there, the biggest variance otherwise. Nothing is scored here;
 * the choice is "largest variance in the month the clock is on".
 */
export function pickHero(exceptions: ExceptionSummary[], asOf: string | null | undefined): ExceptionSummary | null {
  const open = exceptions.filter((e) => e.status !== "balanced");
  if (!open.length) return null;
  const month = asOf?.slice(0, 7);
  const inMonth = month ? open.filter((e) => e.period.slice(0, 7) === month) : [];
  const pool = inMonth.length ? inMonth : open;
  return pool.reduce((best, e) => (Math.abs(e.delta) > Math.abs(best.delta) ? e : best));
}

/** The hero item, with its documents behind it and what to do next. */
export function HeroCard({ ex, lease, eyebrow = "Needs you first" }: { ex: ExceptionSummary; lease?: LeaseSummary; eyebrow?: string }) {
  const reduce = useReducedMotion();
  const detail = useException(ex.exception_id);
  const inv = detail.data?.investigation;
  const under = ex.delta < 0;
  return (
    <motion.section
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.2, 0.8, 0.2, 1] }}
      aria-labelledby="hero-title"
      data-testid="hero-card"
      className="relative overflow-hidden rounded-md border border-accent/30 bg-surface p-6 shadow-raised"
    >
      <span aria-hidden className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-accent/10 blur-3xl" />
      <div className="relative flex items-start justify-between gap-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="eyebrow text-accent">{eyebrow}</span>
            <StatusBadge status={ex.status} />
          </div>
          <h2 id="hero-title" className="mt-2 text-2xl font-semibold leading-tight">
            {chargeLabel(ex.charge_type)} · {monthLong(ex.period)}
            <span className="font-normal text-ink-soft"> · {clinicLabel(lease?.location, ex.clinic_id)}</span>
          </h2>
          <p className="mt-2 max-w-2xl text-ink-soft">
            Billed <span className="num font-semibold text-ink">{money(ex.actual)}</span> against the{" "}
            <span className="num font-semibold text-ink">{money(ex.expected)}</span> the lease supports:{" "}
            <span className={`num font-semibold ${ex.delta === 0 ? "text-ink" : "text-bad"}`}>{signedMoney(ex.delta)}</span>
            {under ? " under the schedule. " : " over. "}
            {inv
              ? `Investigated: ${inv.explains_variance ? "the variance is explained" : "not explained"}, with ${inv.entries.length} proposed entries.`
              : detail.data?.reason ?? "Not investigated yet."}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <Link href={`/exceptions/${encodeURIComponent(ex.exception_id)}`} className="inline-flex">
            <Button variant="primary" size="lg" icon={inv ? <ArrowRight aria-hidden className="h-4 w-4" /> : <Play aria-hidden className="h-4 w-4" />} tabIndex={-1}>
              {inv ? "Open" : "Run investigation"}
            </Button>
          </Link>
          <span className="font-mono text-2xs text-ink-muted">
            {ex.lease_id} · {ex.clinic_id}
          </span>
        </div>
      </div>
    </motion.section>
  );
}
