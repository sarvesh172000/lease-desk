"use client";

import { AgentActivityFeed } from "@/components/AgentActivityFeed";
import { humanize, timestamp } from "@/lib/format";
import { useAgentSteps, useLiveConnection } from "@/lib/live";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import Link from "next/link";

const AGENT_LABEL: Record<string, string> = {
  checker: "Charge checker",
  investigation: "Investigation agent",
  reconciliation: "Reconciliation",
  engine: "Accounting engine",
  abstraction: "Lease abstraction agent",
  gateway: "Gateway",
};

/**
 * What the agents are doing: the live mirror's steps when it is connected,
 * otherwise the last action of each agent from the audit trail.
 */
export function ActivityFeed({ limit = 8 }: { limit?: number }) {
  const live = useLiveConnection();
  const steps = useAgentSteps(limit);
  const reduce = useReducedMotion();
  if (live !== "connected" || steps.length === 0) return <AgentActivityFeed />;
  const rows = [...steps].reverse();
  return (
    <ul className="divide-y divide-line" data-testid="live-activity">
      <AnimatePresence initial={false}>
        {rows.map((s, i) => (
          <motion.li
            key={String(s.id)}
            initial={reduce ? false : { opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
            className="py-2.5 first:pt-0 last:pb-0"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="flex items-center gap-2 text-sm font-medium">
                {i === 0 ? <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-ok animate-pulse-dot" /> : null}
                {AGENT_LABEL[s.agent] ?? humanize(s.agent)}
              </span>
              <span className="text-2xs text-ink-faint">{timestamp(new Date(Number(s.at.microsSinceUnixEpoch / 1000n)).toISOString())}</span>
            </div>
            <div className="text-sm text-ink-soft">
              {humanize(s.kind)}
              {s.exceptionId ? (
                <>
                  {" "}
                  <Link href={`/exceptions/${encodeURIComponent(s.exceptionId)}`} className="font-mono text-xs text-ink-muted hover:text-accent">
                    {s.exceptionId}
                  </Link>
                </>
              ) : null}
            </div>
            {s.detail ? <div className="text-xs text-ink-muted">{s.detail}</div> : null}
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  );
}
