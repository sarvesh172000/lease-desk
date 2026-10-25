"use client";

import { CountUp } from "@/components/data/CountUp";
import { MetricTile } from "@/components/MetricTile";
import { period } from "@/lib/format";
import type { Summary } from "@/lib/types";

/**
 * The four figures, counting up to the API's exact values: whole numbers for
 * counts, two decimals for money (never a rounded liability).
 */
export function Tiles({ summary, loading, error, leasesNeedingAttention }: { summary?: Summary; loading: boolean; error: boolean; leasesNeedingAttention?: number }) {
  const s = summary;
  return (
    <div className="grid grid-cols-4 gap-4" data-testid="tiles">
      <MetricTile
        index={0}
        label="Active leases"
        loading={loading}
        value={error || !s ? "—" : <CountUp value={s.active_leases} decimals={0} duration={700} />}
        sub={leasesNeedingAttention != null ? `${leasesNeedingAttention} need${leasesNeedingAttention === 1 ? "s" : ""} attention` : "Portfolio"}
      />
      <MetricTile
        index={1}
        label="Open exceptions"
        tone={s?.open_exceptions ? "warn" : "ok"}
        loading={loading}
        value={error || !s ? "—" : <CountUp value={s.open_exceptions} decimals={0} duration={700} />}
        sub={s ? `${s.pending_review} pending review` : "Pending review"}
      />
      <MetricTile
        index={2}
        label="Dollars held"
        tone={s?.held_total ? "bad" : "ok"}
        loading={loading}
        value={error || !s ? "—" : <CountUp value={s.held_total} prefix="$" duration={1100} />}
        sub={s ? `${s.held_count} over-bill${s.held_count === 1 ? "" : "s"} held back` : "Over-bills held back"}
      />
      <MetricTile
        index={3}
        label="Portfolio liability"
        loading={loading}
        value={error || !s ? "—" : <CountUp value={s.portfolio_liability} prefix="$" duration={1300} />}
        sub={s ? `ASC 842 · as of ${period(s.as_of)}` : "ASC 842"}
      />
    </div>
  );
}
