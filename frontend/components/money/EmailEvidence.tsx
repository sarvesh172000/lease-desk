"use client";

import { day } from "@/lib/format";
import type { Evidence } from "@/lib/types";
import { motion, useReducedMotion } from "framer-motion";
import { Mail } from "lucide-react";

/** "  - Base rent reduced…" → "Base rent reduced…": the bullet is the email's layout, not the claim. */
export function cleanQuote(q: string): string {
  return q.trim().replace(/^[-–•*]\s+/, "");
}

/**
 * Evidence that lives in the mailbox as text, with no page image to box: shown
 * as the message itself, the cited sentence highlighted where it sits.
 */
export function EmailEvidence({ evidence, highlight }: { evidence: Evidence; highlight?: boolean }) {
  const reduce = useReducedMotion();
  return (
    <div className="flex h-full flex-col overflow-y-auto bg-sunken p-4" data-testid="email-evidence">
      <article className="rounded-xs border border-line bg-surface p-5 shadow-raised">
        <header className="flex items-start gap-3 border-b border-line pb-3">
          <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
            <Mail className="h-4 w-4" />
          </span>
          <dl className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-3 text-sm">
            <dt className="text-ink-muted">From</dt>
            <dd className="break-words font-medium text-ink">{evidence.source.replace("@", "@\u200b")}</dd>
            {evidence.date ? (
              <>
                <dt className="text-ink-muted">Date</dt>
                <dd className="text-ink-soft">{day(evidence.date)}</dd>
              </>
            ) : null}
            <dt className="text-ink-muted">Message</dt>
            <dd className="truncate font-mono text-xs text-ink-muted">{evidence.doc_id}</dd>
          </dl>
        </header>
        <p className="relative mt-4 overflow-hidden rounded-xs px-2 py-1.5 text-[1.05rem] leading-relaxed text-ink">
          <motion.span
            aria-hidden
            className="absolute inset-0 origin-left rounded-xs border-l-[3px] border-warn bg-warn-soft"
            initial={highlight && !reduce ? { scaleX: 0 } : false}
            animate={{ scaleX: 1 }}
            transition={{ duration: 0.6, delay: 0.3, ease: [0.2, 0.8, 0.2, 1] }}
          />
          <span className="relative">{cleanQuote(evidence.quote)}</span>
        </p>
        <p className="mt-4 text-xs text-ink-muted">
          The mailbox keeps this message as text, so there is no page image to box; the cited sentence is shown as written.
        </p>
      </article>
    </div>
  );
}
