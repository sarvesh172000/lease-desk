"use client";

import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { motion, useReducedMotion } from "framer-motion";

/** Confidence as a ring that fills to the API's value. Colour reads at a glance; the number is always printed. */
export function ConfidenceRing({ value, size = 52, label = "Confidence" }: { value: number | null | undefined; size?: number; label?: string }) {
  const reduce = useReducedMotion();
  const p = value == null ? null : Math.max(0, Math.min(1, value));
  const tone = p == null ? "text-ink-faint" : p >= 0.85 ? "text-ok" : p >= 0.7 ? "text-warn" : "text-bad";
  const r = 15.5;
  return (
    <div className="flex items-center gap-2.5" role="img" aria-label={`${label} ${p == null ? "not stated" : pct(p)}`}>
      <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden className="-rotate-90">
        <circle cx="18" cy="18" r={r} fill="none" stroke="rgb(var(--line))" strokeWidth="3" />
        {p != null ? (
          <motion.circle
            cx="18"
            cy="18"
            r={r}
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            className={tone}
            initial={reduce ? false : { pathLength: 0 }}
            animate={{ pathLength: p }}
            transition={{ duration: 0.9, ease: [0.2, 0.8, 0.2, 1] }}
          />
        ) : null}
      </svg>
      <div className="leading-tight">
        <div className={cn("num text-lg font-semibold", tone)}>{p == null ? "—" : pct(p)}</div>
        <div className="text-2xs text-ink-muted">{label}</div>
      </div>
    </div>
  );
}
