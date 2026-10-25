"use client";

import { money, period } from "@/lib/format";
import type { Schedule } from "@/lib/types";
import { useReducedMotion } from "framer-motion";
import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

/**
 * The ASC 842 balances over the term: lease liability and the right-of-use
 * asset, month by month, from the schedule rows. With two versions the
 * remeasured schedule overlays the original, so the step shows. Nothing is
 * computed here; every point is a row the API returned.
 */
export function ScheduleChart({ before, after, highlightFrom }: { before: Schedule; after?: Schedule | null; highlightFrom?: string }) {
  const reduce = useReducedMotion();
  const byPeriod = new Map<string, { period: string; liability: number; rou: number; liability2?: number; rou2?: number }>();
  for (const r of before.rows) byPeriod.set(r.period.slice(0, 7), { period: r.period, liability: r.liability_close, rou: r.rou_close });
  for (const r of after?.rows ?? []) {
    const k = r.period.slice(0, 7);
    const row = byPeriod.get(k) ?? { period: r.period, liability: NaN, rou: NaN };
    byPeriod.set(k, { ...row, liability2: r.liability_close, rou2: r.rou_close });
  }
  const data = Array.from(byPeriod.values()).sort((a, b) => a.period.localeCompare(b.period));
  const compact = (v: number) => (Math.abs(v) >= 1_000_000 ? `$${(v / 1_000_000).toFixed(2)}M` : `$${Math.round(v / 1000)}k`);

  return (
    <div className="h-64 w-full" data-testid="schedule-chart" data-versions={after ? 2 : 1}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
          <defs>
            <linearGradient id="liab" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgb(var(--accent))" stopOpacity={0.35} />
              <stop offset="100%" stopColor="rgb(var(--accent))" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="rou" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgb(var(--esc))" stopOpacity={0.25} />
              <stop offset="100%" stopColor="rgb(var(--esc))" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="rgb(var(--line))" vertical={false} />
          <XAxis dataKey="period" tickFormatter={(p: string) => period(p)} tick={{ fill: "rgb(var(--ink-muted))", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "rgb(var(--line-strong))" }} minTickGap={48} />
          <YAxis tickFormatter={compact} tick={{ fill: "rgb(var(--ink-muted))", fontSize: 11 }} tickLine={false} axisLine={false} width={56} />
          <Tooltip
            contentStyle={{ background: "rgb(var(--raised))", border: "1px solid rgb(var(--line))", borderRadius: 10, fontSize: 12, color: "rgb(var(--ink))" }}
            labelFormatter={(p) => period(String(p))}
            formatter={(v, name) => [money(Number(v)), String(name)]}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: "rgb(var(--ink-soft))" }} />
          <Area type="monotone" dataKey="liability" name={`Lease liability · v${before.version}`} stroke="rgb(var(--accent))" strokeWidth={2} fill="url(#liab)" isAnimationActive={!reduce} animationDuration={900} dot={false} />
          <Area type="monotone" dataKey="rou" name={`ROU asset · v${before.version}`} stroke="rgb(var(--esc))" strokeWidth={1.5} fill="url(#rou)" isAnimationActive={!reduce} animationDuration={900} dot={false} />
          {after ? (
            <>
              <Area type="monotone" dataKey="liability2" name={`Lease liability · v${after.version}`} stroke="rgb(var(--accent))" strokeDasharray="5 4" strokeWidth={2} fill="none" isAnimationActive={!reduce} animationDuration={900} dot={false} />
              <Area type="monotone" dataKey="rou2" name={`ROU asset · v${after.version}`} stroke="rgb(var(--esc))" strokeDasharray="5 4" strokeWidth={1.5} fill="none" isAnimationActive={!reduce} animationDuration={900} dot={false} />
            </>
          ) : null}
        </AreaChart>
      </ResponsiveContainer>
      {highlightFrom ? <span className="sr-only">Remeasured from {period(highlightFrom)}</span> : null}
    </div>
  );
}
