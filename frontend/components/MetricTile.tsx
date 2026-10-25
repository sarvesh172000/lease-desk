"use client";

import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { Skeleton } from "./ui/States";

/**
 * A figure with a coloured rule down its left edge, so the state of the
 * portfolio reads from across a room before any of the words do.
 */
export function MetricTile({
  label, value, sub, tone = "neutral", loading, index = 0, emphasis = false,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "neutral" | "bad" | "warn" | "ok";
  loading?: boolean;
  index?: number;
  /** The one figure the room should read first: set solid in the accent, the others stay white. */
  emphasis?: boolean;
}) {
  if (emphasis) tone = "neutral";
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: index * 0.06, ease: [0.2, 0.8, 0.2, 1] }}
      className={cn(
        "group relative overflow-hidden rounded-md border px-5 py-4",
        emphasis ? "border-accent bg-accent text-accent-ink" : "border-line bg-surface",
        "shadow-raised transition-colors duration-base ease-out hover:border-line-strong",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "absolute inset-y-0 left-0 w-1 transition-all duration-base ease-out group-hover:w-1.5",
          tone === "bad" && "bg-bad",
          tone === "warn" && "bg-warn",
          tone === "ok" && "bg-ok",
          tone === "neutral" && "bg-accent",
        )}
      />
      {/* A wash that only appears on hover, so the tile feels live without
          anything moving on the page at rest. */}
      <span
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-base",
          "group-hover:opacity-100",
          tone === "bad" && "bg-bad/[0.04]",
          tone === "warn" && "bg-warn/[0.04]",
          tone === "ok" && "bg-ok/[0.04]",
          tone === "neutral" && "bg-accent/[0.04]",
        )}
      />
      <div className={cn("eyebrow relative", emphasis && "text-accent-ink/75")}>{label}</div>
      <div className="num relative mt-1.5 text-[2rem] font-semibold leading-none tracking-tight">
        {loading ? <Skeleton className="h-8 w-28" /> : value}
      </div>
      {sub ? <div className={cn("relative mt-2 text-sm", emphasis ? "text-accent-ink/80" : "text-ink-muted")}>{sub}</div> : null}
    </motion.div>
  );
}
