"use client";

import { motion } from "framer-motion";
import { Link2, ShieldAlert, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The audit trail drawn as what it actually is: a chain.
 *
 * Each event carries the hash of the one before it, so changing any row
 * invalidates every row after it. Rendering that as a list of timestamps
 * throws away the only thing that makes it worth having — you cannot see that
 * it is linked. A line between the blocks, and each block showing where its
 * hash came from, makes the claim visible instead of asserted.
 */
export function ChainVerdict({
  verified, brokenAt, count,
}: { verified: boolean; brokenAt?: number | null; count: number }) {
  const Icon = verified ? ShieldCheck : ShieldAlert;
  return (
    <div
      data-testid="chain-badge"
      data-verified={verified ? "true" : "false"}
      className={cn(
        "flex items-center gap-3 rounded-md border px-4 py-3",
        verified ? "border-ok-line bg-ok-soft" : "border-bad-line bg-bad-soft",
      )}
    >
      <span className={cn("grid h-9 w-9 place-items-center rounded-full border",
        verified ? "border-ok/40 text-ok" : "border-bad/40 text-bad")}>
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0">
        <div className={cn("text-sm font-semibold", verified ? "text-ok" : "text-bad")}>
          {verified ? "Chain verified" : `Chain broken at #${brokenAt ?? "?"}`}
        </div>
        <div className="text-2xs text-ink-muted">
          {verified
            ? `${count.toLocaleString()} events, each sealed by the one before it`
            : "A row was changed after it was written"}
        </div>
      </div>
    </div>
  );
}

export function ChainLink({
  seq, hash, prevHash, allowed = true, index = 0,
}: {
  seq: number;
  hash?: string | null;
  prevHash?: string | null;
  allowed?: boolean;
  index?: number;
}) {
  const short = (h?: string | null) => (h ? h.slice(0, 10) : "—");
  return (
    <motion.div
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.3, delay: Math.min(index, 12) * 0.03 }}
      className="flex items-center gap-2 font-mono text-2xs"
    >
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-xs border px-2 py-1",
          allowed ? "border-line bg-raised text-ink-muted" : "border-bad-line bg-bad-soft text-bad",
        )}
        title={hash ? `hash ${hash}` : undefined}
      >
        <Link2 className="h-3 w-3 opacity-60" aria-hidden />
        #{seq}
        <span className="text-ink-faint">{short(hash)}</span>
      </span>
      <span className="text-ink-faint" aria-hidden>←</span>
      <span className="text-ink-faint" title={prevHash ? `previous ${prevHash}` : undefined}>
        {short(prevHash)}
      </span>
    </motion.div>
  );
}
