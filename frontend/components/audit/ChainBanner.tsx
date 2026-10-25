"use client";

import { Button } from "@/components/ui/Button";
import type { ChainState } from "@/lib/chain";
import { cn } from "@/lib/utils";
import { motion, useReducedMotion } from "framer-motion";
import { RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

/**
 * The verdict, front and centre, and only ever the API's: verified with the
 * count, or broken at an exact sequence number in red. "Verify again"
 * refetches; the check draws itself when the answer comes back clean.
 */
export function ChainBanner({ state, loading, onVerify, verifiedAt }: { state: ChainState; loading: boolean; onVerify: () => void; verifiedAt: number | null }) {
  const reduce = useReducedMotion();
  const ok = state.verified;
  // replay the check each time a fresh verdict lands
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (verifiedAt != null) setTick((t) => t + 1);
  }, [verifiedAt]);
  const ago = verifiedAt == null ? null : Math.max(0, Math.round((Date.now() - verifiedAt) / 1000));

  return (
    <div
      role={ok ? "status" : "alert"}
      data-testid="chain-banner"
      data-verified={ok ? "true" : "false"}
      className={cn(
        "flex items-center gap-4 rounded-md border px-4 py-3",
        ok ? "border-ok-line bg-ok-soft" : "border-bad bg-bad-soft shadow-[0_0_0_1px_rgb(var(--bad)/0.4),0_0_32px_-8px_rgb(var(--bad)/0.7)]",
      )}
    >
      <span className={cn("relative flex h-11 w-11 shrink-0 items-center justify-center rounded-full border-2", ok ? "border-ok text-ok" : "border-bad text-bad")}>
        {ok ? (
          <svg key={tick} viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <motion.path d="M5 12l5 5L20 7" initial={reduce ? false : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }} />
          </svg>
        ) : (
          <ShieldAlert className="h-6 w-6" aria-hidden />
        )}
        {ok && !reduce ? (
          <motion.span key={`ring${tick}`} aria-hidden className="absolute inset-0 rounded-full border-2 border-ok" initial={{ scale: 1, opacity: 0.8 }} animate={{ scale: 1.7, opacity: 0 }} transition={{ duration: 0.9, ease: "easeOut" }} />
        ) : null}
      </span>
      <div className="min-w-0 flex-1">
        <div className={cn("text-lg font-bold leading-tight", ok ? "text-ok" : "text-bad")}>
          {ok ? `Chain verified · ${state.count.toLocaleString("en-US")} events` : `Chain broken at #${state.brokenSeq ?? "?"}`}
        </div>
        <div className="text-xs text-ink-soft">
          {ok
            ? `Each sealed by the one before it${ago != null ? ` · verified by the API ${ago === 0 ? "just now" : `${ago}s ago`}` : ""}`
            : `The prev_hash of #${state.brokenSeq ?? "?"} no longer matches the hash before it. Every row from there on is unverifiable; ${state.count.toLocaleString("en-US")} events on record.`}
        </div>
      </div>
      <Button variant={ok ? "secondary" : "danger"} size="sm" icon={ok ? <ShieldCheck aria-hidden className="h-3.5 w-3.5" /> : <RefreshCw aria-hidden className="h-3.5 w-3.5" />} loading={loading} onClick={onVerify}>
        Verify again
      </Button>
    </div>
  );
}
