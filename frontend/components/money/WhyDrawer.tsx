"use client";

import { Button } from "@/components/ui/Button";
import { ErrorState, LoadingBlock } from "@/components/ui/States";
import { ApiError } from "@/lib/api";
import { humanize } from "@/lib/format";
import { useAskWhy } from "@/lib/hooks";
import type { WhyRow } from "@/lib/types";
import * as Dialog from "@radix-ui/react-dialog";
import { HelpCircle, X } from "lucide-react";
import { useEffect, useState } from "react";

const TOOL_LABEL: Record<WhyRow["tool"], string> = {
  timeline_for: "Timeline",
  decisions_by_policy: "Decisions under a policy",
  sources_for: "Sources",
  denied_attempts: "Refused attempts",
  as_known_on: "As known on a date",
};

/** One row the answer rests on, shown as its own key/value pairs. */
function Row({ row }: { row: WhyRow }) {
  const pairs = Object.entries(row).filter(([k, v]) => k !== "tool" && v != null && v !== "");
  return (
    <li className="rounded-xs border border-line px-3 py-2 text-xs">
      <div className="eyebrow">{TOOL_LABEL[row.tool] ?? humanize(row.tool)}</div>
      <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5">
        {pairs.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-ink-muted">{humanize(k)}</dt>
            <dd className="truncate font-mono text-ink-soft" title={String(v)}>
              {typeof v === "object" ? JSON.stringify(v) : String(v)}
            </dd>
          </div>
        ))}
      </dl>
    </li>
  );
}

/**
 * "Why?": a side drawer that asks the server about this item and shows its
 * short answer with the rows it was built from. Fixed queries, not a chat.
 */
export function WhyDrawer({ itemId }: { itemId: number | string | null | undefined }) {
  const [open, setOpen] = useState(false);
  const why = useAskWhy(itemId);
  const { mutate, reset } = why;

  useEffect(() => {
    if (open && itemId != null) mutate(undefined);
    if (!open) reset();
  }, [open, itemId, mutate, reset]);

  const notLive = why.error instanceof ApiError && why.error.status === 501;

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button variant="secondary" size="sm" icon={<HelpCircle aria-hidden className="h-3.5 w-3.5" />} disabled={itemId == null} disabledReason={itemId == null ? "No work item behind this exception" : undefined}>
          Why?
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40 motion-safe:animate-in motion-safe:fade-in" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-50 flex w-[min(28rem,100vw)] flex-col border-l border-line bg-surface shadow-float motion-safe:animate-in motion-safe:slide-in-from-right">
          <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
            <div>
              <Dialog.Title className="text-lg font-semibold">Why is this item here?</Dialog.Title>
              <Dialog.Description className="text-sm text-ink-muted">Answered from the audit trail and the resolver, with the rows behind it.</Dialog.Description>
            </div>
            <Dialog.Close className="rounded-xs p-1 text-ink-muted hover:bg-raised hover:text-ink" aria-label="Close">
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>
          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
            {why.isPending ? (
              <LoadingBlock rows={3} label="Asking why" />
            ) : notLive ? (
              <p className="rounded-sm border border-line bg-sunken px-3 py-3 text-sm text-ink-soft">
                &ldquo;Why?&rdquo; reads the live audit trail, so it needs the live API. The offline demo has no rows to answer from.
              </p>
            ) : why.isError ? (
              <ErrorState title="Could not get an answer" error={why.error} onRetry={() => mutate(undefined)} />
            ) : why.data ? (
              <>
                <p className="text-[1.02rem] leading-relaxed text-ink" data-testid="why-answer">
                  {why.data.answer}
                </p>
                <div className="text-xs text-ink-muted">
                  {why.data.path === "template" ? "Composed from the rows below" : `Phrased by ${why.data.path.replace(/^llm:/, "")} from the rows below`}
                </div>
                {why.data.rows.length ? (
                  <div>
                    <div className="eyebrow mb-2">The rows behind it ({why.data.rows.length})</div>
                    <ul className="space-y-2">
                      {why.data.rows.map((r, i) => (
                        <Row key={i} row={r} />
                      ))}
                    </ul>
                  </div>
                ) : null}
                {why.data.notes.length ? <p className="text-xs text-ink-muted">{why.data.notes.join(" ")}</p> : null}
              </>
            ) : null}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
