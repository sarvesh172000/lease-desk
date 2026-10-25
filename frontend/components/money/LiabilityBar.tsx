"use client";

import { CountUp } from "@/components/data/CountUp";
import { money, signedMoney } from "@/lib/format";
import { motion, useReducedMotion } from "framer-motion";

/**
 * The remeasurement as two bars, before and after, with the delta called out.
 * Bar lengths are drawn relative to the larger balance (a picture of the API's
 * two figures, not a new figure); every printed number is the API's.
 */
export function LiabilityBar({
  before,
  after,
  delta,
  animate,
}: {
  before: number;
  after: number;
  /** The engine's delta when it sent one; otherwise the bars speak alone. */
  delta?: number | null;
  /** Play the count-up and the growth; false shows the result at once. */
  animate: boolean;
}) {
  const reduce = useReducedMotion();
  const play = animate && !reduce;
  const max = Math.max(Math.abs(before), Math.abs(after)) || 1;
  const w = (v: number) => `${(Math.abs(v) / max) * 100}%`;
  return (
    <div className="space-y-3" data-testid="liability-bar">
      <div>
        <div className="flex items-baseline justify-between text-sm">
          <span className="text-ink-muted">Lease liability before</span>
          <span className="num font-medium text-ink-soft">{money(before)}</span>
        </div>
        <div className="mt-1 h-2.5 overflow-hidden rounded-full bg-sunken">
          <div className="h-full rounded-full bg-ink-faint" style={{ width: w(before) }} />
        </div>
      </div>
      <div>
        <div className="flex items-baseline justify-between text-sm">
          <span className="text-ink-muted">After remeasurement</span>
          {play ? (
            <CountUp value={after} from={before} prefix="$" duration={1400} className="text-lg font-semibold text-ink" />
          ) : (
            <span className="num text-lg font-semibold text-ink">{money(after)}</span>
          )}
        </div>
        <div className="mt-1 h-2.5 overflow-hidden rounded-full bg-sunken">
          <motion.div
            className="h-full rounded-full bg-accent"
            initial={play ? { width: w(before) } : false}
            animate={{ width: w(after) }}
            transition={{ duration: 1.4, ease: [0.2, 0.8, 0.2, 1] }}
          />
        </div>
      </div>
      {delta != null ? (
        <motion.div
          initial={play ? { opacity: 0, y: 6 } : false}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: play ? 1.2 : 0 }}
          className="flex items-center justify-between rounded-sm border border-accent/30 bg-accent-soft px-3 py-2"
        >
          <span className="text-sm text-ink-soft">Missing from the balance sheet</span>
          <span className="num text-lg font-semibold text-accent">{signedMoney(delta)}</span>
        </motion.div>
      ) : null}
    </div>
  );
}
