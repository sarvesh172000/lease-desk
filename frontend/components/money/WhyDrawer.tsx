"use client";

import { Button } from "@/components/ui/Button";
import { ErrorState, LoadingBlock } from "@/components/ui/States";
import { ApiError } from "@/lib/api";
import { humanize, money, timestamp } from "@/lib/format";
import { useAskWhy } from "@/lib/hooks";
import type { WhyRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import * as Dialog from "@radix-ui/react-dialog";
import { ChevronRight, HelpCircle, X } from "lucide-react";
import { useEffect, useState } from "react";

const TOOL_LABEL: Record<WhyRow["tool"], string> = {
  timeline_for: "Timeline",
  decisions_by_policy: "Decisions under a policy",
  sources_for: "Sources",
  denied_attempts: "Refused attempts",
  as_known_on: "As known on a date",
};

/** The keys every row kind is read by name; everything else is a detail. */
const NAMED = new Set([
  "tool", "kind", "at", "actor_id", "actor_name", "actor_role", "action", "allowed", "reason", "seq",
  "source", "rank", "rank_name", "claims", "claim", "claim_label", "label", "value", "note",
]);

const str = (v: unknown) => (v == null ? "" : typeof v === "object" ? JSON.stringify(v) : String(v));

/** What one row says, in the fields a reader looks for: when, who, what, allowed or refused, why. */
function headline(row: WhyRow): { when: string | null; who: string | null; what: string; verdict: "allowed" | "refused" | null; why: string | null } {
  const r = row as Record<string, unknown>;
  if (row.tool === "sources_for" || "rank" in r) {
    const claim = typeof r.claims === "string" && /^-?\d+(\.\d+)?$/.test(r.claims) ? money(Number(r.claims)) : str(r.claim ?? r.claims);
    const what = [r.label ?? humanize(str(r.source ?? r.kind)), claim ? `claims ${claim}` : null, r.claim_label ? `(${str(r.claim_label)})` : null]
      .filter(Boolean)
      .join(" ");
    return { when: null, who: r.rank != null ? `Rank ${str(r.rank)} · ${str(r.rank_name)}` : null, what, verdict: null, why: r.note ? str(r.note) : null };
  }
  const who = str(r.actor_name || r.actor_id) || null;
  const verdict = typeof r.allowed === "boolean" ? (r.allowed ? "allowed" : "refused") : null;
  const what = [humanize(str(r.action)), r.subject_type ? `${humanize(str(r.subject_type))} ${str(r.subject_id)}` : null].filter(Boolean).join(" · ");
  return { when: r.at ? timestamp(str(r.at)) : null, who, what: what || humanize(str(r.kind)), verdict, why: r.reason ? str(r.reason) : null };
}

function Row({ row }: { row: WhyRow }) {
  const [open, setOpen] = useState(false);
  const h = headline(row);
  const details = Object.entries(row).filter(([k, v]) => !NAMED.has(k) && v != null && v !== "");
  return (
    <li className="rounded-xs border border-line px-3 py-2 text-sm">
      <div className="flex items-baseline justify-between gap-3">
        <span className="min-w-0 truncate font-medium text-ink">{h.who ?? TOOL_LABEL[row.tool] ?? humanize(row.tool)}</span>
        {h.when ? <span className="num shrink-0 text-xs text-ink-muted">{h.when}</span> : null}
      </div>
      <div className="mt-0.5 flex items-center gap-2 text-ink-soft">
        <span className="min-w-0 truncate">{h.what}</span>
        {h.verdict ? (
          <span className={cn("shrink-0 rounded-xs px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide", h.verdict === "allowed" ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad")}>
            {h.verdict}
          </span>
        ) : null}
      </div>
      {h.why ? <p className="mt-1 text-xs text-ink-muted">{h.why}</p> : null}
      {details.length ? (
        <>
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            className="mt-1.5 flex items-center gap-1 text-xs text-ink-muted transition-colors hover:text-ink"
          >
            <ChevronRight aria-hidden className={cn("h-3 w-3 transition-transform", open && "rotate-90")} />
            Details ({details.length})
          </button>
          {open ? (
            <dl className="mt-1.5 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 border-l border-line pl-3 text-xs">
              {details.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-ink-muted">{humanize(k)}</dt>
                  <dd className="break-all font-mono text-ink-soft">{str(v)}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </>
      ) : null}
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
  const rows = why.data?.rows ?? [];
  const groups = Array.from(new Set(rows.map((r) => r.tool)));

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button variant="secondary" size="sm" icon={<HelpCircle aria-hidden className="h-3.5 w-3.5" />} disabled={itemId == null} disabledReason={itemId == null ? "No work item behind this exception" : undefined}>
          Why?
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40 motion-safe:animate-in motion-safe:fade-in" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-50 flex w-[min(30rem,100vw)] flex-col border-l border-line bg-surface shadow-float motion-safe:animate-in motion-safe:slide-in-from-right">
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
                {groups.map((tool) => (
                  <div key={tool}>
                    <div className="eyebrow mb-2">{TOOL_LABEL[tool] ?? humanize(tool)}</div>
                    <ul className="space-y-2">
                      {rows.map((r, i) => (r.tool === tool ? <Row key={i} row={r} /> : null))}
                    </ul>
                  </div>
                ))}
                {why.data.notes.length ? <p className="text-xs text-ink-muted">{why.data.notes.join(" ")}</p> : null}
              </>
            ) : null}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
