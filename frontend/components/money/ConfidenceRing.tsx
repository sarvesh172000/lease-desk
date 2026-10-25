"use client";

import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { motion, useReducedMotion } from "framer-motion";

/**
 * How the ring presents the API's figure. The number itself never changes with the tone.
 *
 * - `value`: colour by the figure (green / amber / red), the default before an investigation and
 *   after one that explains the charge.
 * - `neutral`: plain ink. After an investigation that found nothing, the hold's figure is a weighing of
 *   the sources, not a grade of the verdict beside it, so it is not painted as an alarm.
 * - `busy`: the last-fetched figure dimmed under an indeterminate sweep while a run re-checks it.
 */
export type RingTone = "value" | "neutral" | "busy";

/**
 * Confidence as a ring that fills to the API's value. The number is always printed; only its colour and
 * label change with the state. With no value there is no ring: a dash would read as broken.
 */
export function ConfidenceRing({
  value,
  size = 52,
  label = "Confidence",
  tone = "value",
}: {
  value: number | null | undefined;
  size?: number;
  label?: string;
  tone?: RingTone;
}) {
  const reduce = useReducedMotion();
  if (value == null) return null;
  const p = Math.max(0, Math.min(1, value));
  const ink =
    tone === "busy" ? "text-ink-muted" : tone === "neutral" ? "text-ink-soft" : p >= 0.85 ? "text-ok" : p >= 0.7 ? "text-warn" : "text-bad";
  const r = 15.5;
  return (
    <div className="flex items-center gap-2.5" role="img" aria-label={`${label} ${pct(p)}`} data-testid="confidence-ring" data-tone={tone}>
      {tone === "busy" ? (
        // a quarter arc in the accent, sweeping; a static arc when motion is reduced
        <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden className="-rotate-90 animate-spin motion-reduce:animate-none" style={{ animationDuration: "1.2s" }}>
          <circle cx="18" cy="18" r={r} fill="none" stroke="rgb(var(--line))" strokeWidth="3" />
          <circle cx="18" cy="18" r={r} fill="none" stroke="rgb(var(--accent))" strokeWidth="3" strokeLinecap="round" pathLength={1} strokeDasharray="0.25 1" />
        </svg>
      ) : (
        <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden className="-rotate-90">
          <circle cx="18" cy="18" r={r} fill="none" stroke="rgb(var(--line))" strokeWidth="3" />
          <motion.circle
            cx="18"
            cy="18"
            r={r}
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            className={ink}
            initial={reduce ? false : { pathLength: 0 }}
            animate={{ pathLength: p }}
            transition={{ duration: 0.9, ease: [0.2, 0.8, 0.2, 1] }}
          />
        </svg>
      )}
      <div className="leading-tight">
        <div className={cn("num text-lg font-semibold", ink)}>{pct(p)}</div>
        <div className="text-2xs text-ink-muted">{label}</div>
      </div>
    </div>
  );
}
