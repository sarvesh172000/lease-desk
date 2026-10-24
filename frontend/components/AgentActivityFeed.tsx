"use client";

import { getAudit } from "@/lib/api";
import { humanize, timestamp } from "@/lib/format";
import type { AuditEvent } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import { EmptyState, ErrorState, LoadingBlock } from "./ui/States";

const isMachine = (e: AuditEvent) => e.actor_id.startsWith("agent:") || e.actor_id === "engine" || e.actor_id.startsWith("system");

/** Last action of each agent, read from the audit stream. */
export function AgentActivityFeed() {
  const q = useQuery({ queryKey: ["audit", null], queryFn: () => getAudit() });
  if (q.isLoading) return <LoadingBlock rows={3} />;
  if (q.isError) return <ErrorState title="Agent activity unavailable" error={q.error} onRetry={() => q.refetch()} />;
  const latest = new Map<string, AuditEvent>();
  for (const e of q.data?.events ?? []) if (isMachine(e)) latest.set(e.actor_id, e);
  const rows = Array.from(latest.values()).sort((a, b) => b.seq - a.seq);
  if (!rows.length) return <EmptyState title="No agent activity yet." />;
  return (
    <ul className="divide-y divide-line">
      {rows.map((e) => (
        <li key={e.actor_id} className="py-2.5 first:pt-0 last:pb-0">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-sm font-medium">{e.actor_name ?? e.actor_id}</span>
            <span className="num text-2xs text-ink-faint">#{e.seq}</span>
          </div>
          <div className="text-sm text-ink-soft">
            {humanize(e.action)} <span className="font-mono text-xs text-ink-muted">{e.subject_id}</span>
          </div>
          {e.reason ? <div className="text-xs text-ink-muted">{e.reason}</div> : null}
          <div className="mt-0.5 text-2xs text-ink-faint">{timestamp(e.at)}</div>
        </li>
      ))}
    </ul>
  );
}
