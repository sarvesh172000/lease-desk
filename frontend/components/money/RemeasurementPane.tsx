"use client";

import { CountUp } from "@/components/data/CountUp";
import { JournalEntryTable } from "@/components/JournalEntryTable";
import { money, signedMoney } from "@/lib/format";
import type { Investigation } from "@/lib/types";
import { motion, useReducedMotion } from "framer-motion";

/**
 * The remeasurement on the stage: lease liability and ROU asset before and
 * after, the delta called out, then the proposed entries with the balance
 * seal. Sized to sit in a document pane at 1280×800 without scrolling. Every
 * figure is the API's; the bars only picture the two balances.
 */
export function RemeasurementPane({
  inv,
  liabilityDelta,
  rouDelta,
  animate,
  entries,
  posted = false,
}: {
  inv: Investigation;
  /** The engine's deltas (from the stream or the record); shown only when sent. */
  liabilityDelta: number | null;
  rouDelta: number | null;
  /** Play the count-up, growth and row reveal; false shows the result at once. */
  animate: boolean;
  /** Show the entries yet (the "complete" beat has arrived or is on record). */
  entries: boolean;
  /** The controller approved the lease change and the gateway posted these entries. */
  posted?: boolean;
}) {
  const reduce = useReducedMotion();
  const play = animate && !reduce;
  return (
    <div className="flex h-full flex-col gap-2.5 overflow-y-auto bg-sunken p-3" data-testid="remeasurement-pane">
      <div className="rounded-sm border border-line bg-surface px-3.5 py-3">
        <div className="eyebrow mb-2">Remeasured under ASC 842</div>
        <div className="space-y-2.5">
          <Row label="Lease liability" before={inv.liability_before} after={inv.liability_after} play={play} />
          <Row label="Right-of-use asset" before={inv.rou_before} after={inv.rou_after} play={play} delay={0.15} />
        </div>
        {liabilityDelta != null ? (
          <motion.div
            initial={play ? { opacity: 0, y: 6 } : false}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: play ? 1.3 : 0 }}
            className="mt-2.5 flex items-center justify-between rounded-sm border border-accent/30 bg-accent-soft px-3 py-1.5"
            data-testid="remeasurement-delta"
          >
            <span className="text-sm text-ink-soft">
              Missing from the balance sheet
              {rouDelta != null ? <span className="text-ink-muted"> · ROU {signedMoney(rouDelta)}</span> : null}
            </span>
            <span className="num text-lg font-semibold text-accent">{signedMoney(liabilityDelta)}</span>
          </motion.div>
        ) : null}
      </div>

      {entries && inv.entries.length ? (
        <motion.div
          initial={play ? { opacity: 0, y: 8 } : false}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: play ? 0.2 : 0 }}
          className="rounded-sm border border-line bg-surface px-3.5 py-3"
        >
          <div className="eyebrow mb-1.5">{posted ? "Entries · posted through the gateway" : "Proposed entries · not posted"}</div>
          <JournalEntryTable entries={inv.entries} balanced={inv.balanced} reveal={animate} dense />
        </motion.div>
      ) : null}
    </div>
  );
}

/** One balance: label, before → after on a line, and a bar that grows from the one to the other. */
function Row({ label, before, after, play, delay = 0 }: { label: string; before: number | null; after: number | null; play: boolean; delay?: number }) {
  if (before == null || after == null) {
    return (
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-ink-soft">{label}</span>
        <span className="num text-ink-muted">—</span>
      </div>
    );
  }
  const max = Math.max(Math.abs(before), Math.abs(after)) || 1;
  const w = (v: number) => `${(Math.abs(v) / max) * 100}%`;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-ink-soft">{label}</span>
        <span className="num whitespace-nowrap">
          <span className="text-ink-muted">{money(before)}</span>
          <span aria-hidden className="mx-1.5 text-ink-faint">→</span>
          {play ? <CountUp value={after} from={before} prefix="$" duration={1400} className="font-semibold text-ink" /> : <span className="font-semibold text-ink">{money(after)}</span>}
        </span>
      </div>
      <div className="relative mt-1 h-2 overflow-hidden rounded-full bg-sunken">
        <motion.div
          className="h-full rounded-full bg-accent"
          initial={play ? { width: w(before) } : false}
          animate={{ width: w(after) }}
          transition={{ duration: 1.4, delay, ease: [0.2, 0.8, 0.2, 1] }}
        />
        {/* where it stood before */}
        <span aria-hidden className="absolute inset-y-0 w-0.5 bg-ink" style={{ left: w(before) }} />
      </div>
    </div>
  );
}
