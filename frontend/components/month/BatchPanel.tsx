"use client";

import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ApiError } from "@/lib/api";
import { money } from "@/lib/format";
import { useMe, useReleaseBatch } from "@/lib/hooks";
import { monthLong } from "@/lib/labels";
import type { MonthSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Send } from "lucide-react";
import { useState } from "react";

/**
 * The month's payment batch: what is ready, what was released, what is still
 * waiting on a decision. Release is the AP clerk's; the gateway has the final
 * say and records a refusal, so the button shows for the clerk and the server
 * answers.
 */
export function BatchPanel({ summary, compact }: { summary: MonthSummary; compact?: boolean }) {
  const b = summary.batch;
  const me = useMe();
  const release = useReleaseBatch(summary.period, summary.entity_id);
  const [confirm, setConfirm] = useState(false);
  const isAp = me.data?.role === "ap_clerk";
  const notLive = release.error instanceof ApiError && release.error.status === 501;

  const stat = (label: string, value: string, tone?: "ok" | "warn") => (
    <div className="flex flex-col gap-0.5">
      <span className="text-2xs font-semibold uppercase tracking-wide text-ink-muted">{label}</span>
      <span className={cn("num font-semibold", compact ? "text-base" : "text-xl", tone === "ok" && "text-ok", tone === "warn" && "text-warn")}>{value}</span>
    </div>
  );

  return (
    <div className="space-y-4" data-testid="batch-panel" data-ready={b.ready ? "true" : "false"} data-released={b.released ? "true" : "false"}>
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "rounded-full border px-2.5 py-0.5 text-xs font-semibold",
            b.released ? "border-ok-line bg-ok-soft text-ok" : b.ready ? "border-accent/40 bg-accent-soft text-accent" : "border-warn-line bg-warn-soft text-warn",
          )}
        >
          {b.released ? "Released" : b.ready ? "Ready for AP" : "Not ready"}
        </span>
        <span className="text-sm text-ink-muted">
          {b.released
            ? `The ${monthLong(summary.period)} batch has gone to the outbox.`
            : b.ready
              ? "Every approved charge is in; the clerk can release."
              : `${b.awaiting_decision} charge${b.awaiting_decision === 1 ? "" : "s"} still waiting on a decision.`}
        </span>
      </div>
      <div className={cn("grid gap-4", compact ? "grid-cols-3" : "grid-cols-3")}>
        {stat("Awaiting decision", String(b.awaiting_decision), b.awaiting_decision ? "warn" : undefined)}
        {stat("Releasable", String(b.releasable), b.releasable ? "ok" : undefined)}
        {stat("Releasable total", money(b.releasable_total))}
      </div>
      {isAp ? (
        <div className="flex items-center gap-3">
          <Button
            variant="primary"
            icon={<Send aria-hidden className="h-4 w-4" />}
            loading={release.isPending}
            disabled={b.released || !b.releasable}
            disabledReason={b.released ? "Already released" : !b.releasable ? "Nothing approved to release yet" : undefined}
            onClick={() => setConfirm(true)}
            data-testid="release-batch"
          >
            Release batch
          </Button>
          {release.data ? (
            <span role="status" className="text-sm text-ok">
              {release.data.created ? "Released" : "Already released"} · {release.data.item_count} item{release.data.item_count === 1 ? "" : "s"} ·{" "}
              <span className="num">{money(release.data.total)}</span>
            </span>
          ) : release.isError ? (
            <span role="alert" className="text-sm text-bad">
              {notLive ? "Releasing needs the live API." : release.error.message}
            </span>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-ink-muted">Only the AP clerk releases a batch; the gateway records who tried.</p>
      )}
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={`Release the ${monthLong(summary.period)} batch?`}
        confirmLabel="Release batch"
        loading={release.isPending}
        onConfirm={() => release.mutate(undefined, { onSettled: () => setConfirm(false) })}
      >
        <p>
          This sends <strong>{b.releasable}</strong> approved charge{b.releasable === 1 ? "" : "s"} totalling{" "}
          <span className="num font-semibold text-ink">{money(b.releasable_total)}</span> to the outbox. Held charges stay held.
        </p>
        <p className="mt-2 text-ink-muted">Recorded in the audit trail under your name.</p>
      </ConfirmDialog>
    </div>
  );
}
