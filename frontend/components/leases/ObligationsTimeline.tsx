"use client";

import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { day } from "@/lib/format";
import { useObligations } from "@/lib/hooks";
import { obligationLabel } from "@/lib/labels";
import { cn } from "@/lib/utils";

const TONE: Record<string, string> = {
  renewal_notice: "bg-warn",
  cam_audit_window: "bg-esc",
  deposit_return: "bg-accent",
  expiration: "bg-ink-soft",
};

/** What the lease asks of us next: renewal notices, audit windows, the deposit, the end. */
export function ObligationsTimeline({ leaseId }: { leaseId: string }) {
  const q = useObligations({ lease_id: leaseId, within_days: 2000 });
  if (q.isLoading) return <LoadingBlock rows={2} label="Loading obligations" />;
  if (q.isError) return <ErrorState title="Obligations unavailable" error={q.error} onRetry={() => q.refetch()} />;
  const rows = [...(q.data?.obligations ?? [])].sort((a, b) => a.days_left - b.days_left);
  if (!rows.length) return <EmptyState title="No deadlines on record for this lease.">Renewal notices, CAM audit windows and the deposit return appear here as the lease sets them.</EmptyState>;
  return (
    <ol className="relative ml-2 border-l border-line pl-5" data-testid="obligations">
      {rows.map((o) => (
        <li key={o.id} className="relative pb-4 last:pb-0">
          <span aria-hidden className={cn("absolute -left-[26px] top-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-surface", TONE[o.kind] ?? "bg-ink-soft")} />
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-sm font-medium">{obligationLabel(o.kind)}</span>
            <span className={cn("num text-xs", o.days_left < 60 ? "font-semibold text-warn" : "text-ink-muted")}>
              {day(o.due_date)} · {o.days_left} days
            </span>
          </div>
          <p className="text-sm text-ink-soft">{o.action}</p>
          {o.citation?.section || o.citation?.quote ? (
            <p className="mt-0.5 text-xs text-ink-muted">
              {o.citation.section ? `${o.citation.section}` : null}
              {o.citation.page ? ` · p.${o.citation.page}` : null}
              {o.citation.quote ? ` · “${o.citation.quote}”` : null}
            </p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
