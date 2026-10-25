"use client";

import { day, pct } from "@/lib/format";
import { rootCauseLabel, TRUST_RANKS } from "@/lib/labels";
import type { Evidence } from "@/lib/types";
import { cn } from "@/lib/utils";
import { motion, useReducedMotion } from "framer-motion";
import { cleanQuote } from "./money/EmailEvidence";
import { TrustLadder } from "./money/TrustLadder";

export function ConfidenceMeter({ value }: { value: number }) {
  const p = Math.max(0, Math.min(1, value));
  const tone = p >= 0.85 ? "bg-ok" : p >= 0.7 ? "bg-warn" : "bg-bad";
  return (
    <div className="flex items-center gap-2" aria-label={`Confidence ${pct(p)}`}>
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-sunken">
        <div className={cn("h-full", tone)} style={{ width: `${p * 100}%` }} />
      </div>
      <span className="num text-sm font-semibold">{pct(p)}</span>
    </div>
  );
}

/**
 * One piece of evidence: the quoted sentence first, then who said it and how
 * much that counts (the trust ladder, rank 1 at the top).
 */
export function EvidenceCard({
  evidence,
  confidence,
  rootCause,
  selected,
  onSelect,
  highlight,
}: {
  evidence: Evidence;
  confidence?: number;
  rootCause?: string;
  selected?: boolean;
  onSelect?: () => void;
  /** Just arrived from the investigation: the quote's highlight sweeps in. */
  highlight?: boolean;
}) {
  const reduce = useReducedMotion();
  const Wrapper = onSelect ? "button" : "div";
  const rank = TRUST_RANKS.find((r) => r.rank === evidence.trust_rank);
  return (
    <Wrapper
      type={onSelect ? "button" : undefined}
      onClick={onSelect}
      data-testid="evidence-card"
      className={cn(
        "block w-full rounded-md border bg-surface p-4 text-left transition-colors duration-base",
        selected ? "border-accent ring-1 ring-accent" : "border-line",
        onSelect && "hover:border-line-strong",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="eyebrow">Evidence{rootCause ? ` · ${rootCauseLabel(rootCause)}` : ""}</div>
          <div className="mt-0.5 truncate text-sm font-medium text-ink" title={evidence.source}>
            {evidence.source}
          </div>
          <div className="text-xs text-ink-muted">
            {[evidence.date ? day(evidence.date) : null, evidence.page != null ? `p.${evidence.page}` : "email"].filter(Boolean).join(" · ")}
          </div>
        </div>
        {confidence != null ? (
          <span className="num shrink-0 rounded-xs border border-ok-line bg-ok-soft px-2 py-0.5 text-xs font-semibold text-ok" title="Confidence the document explains the variance">
            {pct(confidence)}
          </span>
        ) : null}
      </div>

      <blockquote className="relative mt-3 overflow-hidden rounded-xs border-l-[3px] border-warn px-3 py-2 text-[0.98rem] leading-snug text-ink">
        <motion.span
          aria-hidden
          className="absolute inset-0 origin-left bg-warn-soft"
          initial={highlight && !reduce ? { scaleX: 0 } : false}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.6, ease: [0.2, 0.8, 0.2, 1], delay: 0.2 }}
        />
        <span className="relative">“{cleanQuote(evidence.quote)}”</span>
      </blockquote>

      {rank ? (
        <div className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
          <div className="min-w-0">
            <div className="eyebrow">Trust rank {evidence.trust_rank}</div>
            <p className="mt-0.5 text-sm text-ink-soft">{rank.long}</p>
          </div>
          <div className="w-40">
            <TrustLadder rank={evidence.trust_rank} compact />
          </div>
        </div>
      ) : (
        <p className="mt-3 text-xs text-ink-muted">The checker&apos;s own citation; not ranked against other sources.</p>
      )}
    </Wrapper>
  );
}
