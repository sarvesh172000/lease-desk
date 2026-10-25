"use client";

import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { day, humanize, money, pct } from "@/lib/format";
import { useItemSources } from "@/lib/hooks";
import type { ResolverSource } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CircleCheck, CircleSlash, UserRound } from "lucide-react";

function value(s: ResolverSource): string {
  if (typeof s.value === "number") return money(s.value);
  return s.value ?? "—";
}

/**
 * The resolver's view of this item: every source it weighed, ranked; which
 * one it trusted and why; how confident it is and the reasons; who was asked.
 */
export function SourcesPanel({ itemId }: { itemId: number | string }) {
  const q = useItemSources(itemId);
  if (q.isLoading) return <LoadingBlock rows={4} label="Loading sources" />;
  if (q.isError) return <ErrorState title="Sources unavailable" error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data!;
  const sources = [...d.sources].sort((a, b) => a.rank - b.rank);
  const trusted = d.decision?.trusted ?? null;

  return (
    <div className="space-y-4">
      {d.decision?.explanation || d.explanation ? (
        <p className="rounded-sm border border-line bg-sunken/60 px-3 py-2 text-sm text-ink">{d.decision?.explanation ?? d.explanation}</p>
      ) : null}

      {sources.length ? (
        <ol className="space-y-2" aria-label="Sources, most authoritative first">
          {sources.map((s) => {
            const isTrusted = s.source_id === trusted;
            const setAside = s.suspect || d.decision?.set_aside.includes(s.source_id);
            return (
              <li
                key={s.source_id}
                className={cn(
                  "rounded-sm border px-3 py-2",
                  isTrusted ? "border-ok-line bg-ok-soft/50" : setAside ? "border-bad-line bg-bad-soft/40" : "border-line",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="num flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-line-strong text-2xs font-semibold">
                      {s.rank}
                    </span>
                    <span className="truncate text-sm font-medium">{s.label}</span>
                  </span>
                  <span className="num shrink-0 text-sm font-semibold">{value(s)}</span>
                </div>
                <div className="mt-1 flex items-center gap-1.5 text-xs text-ink-muted">
                  {isTrusted ? (
                    <>
                      <CircleCheck aria-hidden className="h-3.5 w-3.5 text-ok" /> <span className="font-medium text-ok">Trusted</span> ·
                    </>
                  ) : setAside ? (
                    <>
                      <CircleSlash aria-hidden className="h-3.5 w-3.5 text-bad" /> <span className="font-medium text-bad">Set aside</span> ·
                    </>
                  ) : null}
                  <span className="truncate">{s.rank_name}</span>
                </div>
                {s.note ? <p className="mt-1 text-xs text-ink-soft">{s.note}</p> : null}
              </li>
            );
          })}
        </ol>
      ) : (
        <EmptyState title="No ranked sources on record.">The resolver lists sources for items it has weighed; this one has none yet.</EmptyState>
      )}

      {d.confidence != null || d.confidence_reasons.length ? (
        <div>
          <div className="eyebrow">Confidence {d.confidence != null ? pct(d.confidence) : ""}</div>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm text-ink-soft">
            {d.confidence_reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {d.route || d.asked_to ? (
        <div className="flex items-start gap-2 rounded-sm border border-line px-3 py-2 text-sm">
          <UserRound aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted" />
          <div>
            <div>
              Asked <span className="font-medium">{d.asked_to ?? d.route?.asked_to ?? humanize(d.route?.role)}</span>
              {d.route?.also_to.length ? <span className="text-ink-muted"> · copied {d.route.also_to.join(", ")}</span> : null}
            </div>
            {d.payment_due ? <div className="text-xs text-ink-muted">Payment due {day(d.payment_due)}</div> : null}
            {d.question?.body ? <p className="mt-1 text-xs text-ink-soft">“{d.question.body}”</p> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
