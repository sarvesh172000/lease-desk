"use client";

import { motion, useReducedMotion } from "framer-motion";
import { money, period as fmtPeriod, signedMoney } from "@/lib/format";
import type { Schedule, ScheduleRow } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface BalanceDiff {
  liability_before: number | null;
  liability_after: number | null;
  rou_before: number | null;
  rou_after: number | null;
  /** Engine-supplied deltas; shown only when present (never computed here). */
  liability_delta?: number | null;
  rou_delta?: number | null;
}

/**
 * Before/after, side by side: the remeasured balances on top, then the first
 * months of schedule v1 next to v2 from the effective period. Every figure is
 * read from the API; nothing is recalculated.
 */
export function ScheduleDiff({
  diff,
  before,
  after,
  fromPeriod,
  months = 6,
}: {
  diff: BalanceDiff;
  before?: Schedule | null;
  after?: Schedule | null;
  fromPeriod?: string;
  months?: number;
}) {
  const reduce = useReducedMotion();
  const hasDelta = diff.liability_delta != null || diff.rou_delta != null;
  const rows: Array<{ label: string; before: number | null; after: number | null; delta?: number | null }> = [
    { label: "Lease liability", before: diff.liability_before, after: diff.liability_after, delta: diff.liability_delta },
    { label: "ROU asset", before: diff.rou_before, after: diff.rou_after, delta: diff.rou_delta },
  ];

  const key = fromPeriod?.slice(0, 7);
  const pick = (s?: Schedule | null): ScheduleRow[] => {
    if (!s) return [];
    const start = key ? s.rows.findIndex((r) => r.period.slice(0, 7) >= key) : 0;
    return start < 0 ? [] : s.rows.slice(start, start + months);
  };
  const v1 = pick(before);
  const v2 = pick(after);
  const periods = Array.from(new Set([...v1, ...v2].map((r) => r.period.slice(0, 7)))).sort().slice(0, months);
  const byPeriod = (rs: ScheduleRow[]) => new Map(rs.map((r) => [r.period.slice(0, 7), r]));
  const m1 = byPeriod(v1);
  const m2 = byPeriod(v2);

  return (
    <div className="space-y-4">
      <table className="w-full border-collapse text-[0.95rem]" aria-label="Balances before and after">
        <thead>
          <tr className="table-head">
            <th className="py-2 pl-3 font-semibold" />
            <th className="px-3 py-2 text-right font-semibold">Before{before ? ` · v${before.version}` : ""}</th>
            <th className="px-3 py-2 text-right font-semibold">After{after ? ` · v${after.version}` : ""}</th>
            {hasDelta ? <th className="px-3 py-2 text-right font-semibold">Change</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-b border-line/70">
              <td className="py-2.5 pl-3 font-medium">{r.label}</td>
              <td className="num px-3 py-2.5 text-right text-ink-muted">{money(r.before)}</td>
              <td className="num px-3 py-2.5 text-right font-semibold">{money(r.after)}</td>
              {hasDelta ? (
                <td className="num px-3 py-2.5 text-right">
                  <motion.span
                    className="font-semibold text-accent"
                    initial={reduce ? false : { opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={reduce ? { duration: 0 } : { duration: 0.32, ease: "easeOut" }}
                  >
                    {signedMoney(r.delta)}
                  </motion.span>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>

      {periods.length ? (
        <div>
          <div className="eyebrow mb-1.5">Schedule from {fmtPeriod(fromPeriod)}</div>
          <table className="w-full border-collapse text-sm" aria-label="Schedule rows before and after">
            <thead>
              <tr className="table-head">
                <th className="py-1.5 pl-3 font-semibold">Period</th>
                <th className="px-2 py-1.5 text-right font-semibold">Payment v1</th>
                <th className="px-2 py-1.5 text-right font-semibold">Payment v2</th>
                <th className="px-2 py-1.5 text-right font-semibold">Liability v1</th>
                <th className="px-2 py-1.5 pr-3 text-right font-semibold">Liability v2</th>
              </tr>
            </thead>
            <tbody>
              {periods.map((p) => {
                const a = m1.get(p);
                const b = m2.get(p);
                const changed = a && b && a.payment !== b.payment;
                return (
                  <motion.tr
                    key={p}
                    layout={reduce ? false : "position"}
                    className={cn("border-b border-line/60", changed && "bg-accent-soft/50")}
                  >
                    <td className="relative py-1.5 pl-3">
                      {changed ? <span aria-hidden className="absolute left-0 top-0 h-full w-[3px] bg-accent" /> : null}
                      {fmtPeriod(`${p}-01`)}
                    </td>
                    <td className="num px-2 py-1.5 text-right text-ink-muted">{a ? money(a.payment) : "—"}</td>
                    <td className={cn("num px-2 py-1.5 text-right", changed && "font-semibold text-accent")}>{b ? money(b.payment) : "—"}</td>
                    <td className="num px-2 py-1.5 text-right text-ink-muted">{a ? money(a.liability_close) : "—"}</td>
                    <td className="num px-2 py-1.5 pr-3 text-right">{b ? money(b.liability_close) : "—"}</td>
                  </motion.tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
