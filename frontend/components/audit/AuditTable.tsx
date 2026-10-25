"use client";

import { exceptionIdFor } from "@/lib/api";
import { afterCrack } from "@/lib/chain";
import { timestamp } from "@/lib/format";
import { actionLabel, actorKind, attemptLabel } from "@/lib/labels";
import type { AuditEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useRef } from "react";

/** Fixture events name an exception; live events name the work item behind it. */
export function subjectHref(e: AuditEvent): string | null {
  if (e.subject_type === "exception") return `/exceptions/${encodeURIComponent(e.subject_id)}`;
  if (e.subject_type === "work_item" && /^\d+$/.test(e.subject_id)) return `/exceptions/${exceptionIdFor(e.subject_id)}`;
  if (e.subject_type === "lease" || e.lease_id) return `/leases/${encodeURIComponent(e.subject_type === "lease" ? e.subject_id : e.lease_id!)}`;
  return null;
}

const ROW = 52;

const timeFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: "UTC" });
/** "Oct 25, 01:35:49": the full UTC stamp is on the row's title and in the detail. */
function shortTime(at: string): string {
  const t = Date.parse(at);
  return Number.isNaN(t) ? at : timeFmt.format(new Date(t));
}
const COLS = "44px 92px minmax(0,1.25fr) minmax(0,1fr) 78px minmax(0,1.45fr) 80px";

/**
 * The rows, newest first, virtualised so thousands scroll like sixty. A row
 * is a button: click or Enter selects it, which the strip and the detail
 * panel follow. Refused attempts are tinted, never hidden.
 */
export function AuditTable({
  rows,
  selectedSeq,
  onSelect,
  crackSeq,
  height,
}: {
  rows: AuditEvent[];
  selectedSeq: number | null;
  onSelect: (seq: number) => void;
  crackSeq: number | null;
  height: number;
}) {
  const parent = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parent.current,
    estimateSize: () => ROW,
    overscan: 12,
    // The box's own size when layout has measured it; the given height until then (and under jsdom, which never measures).
    observeElementRect: (instance, cb) => {
      const el = instance.scrollElement;
      if (!el) return;
      const measure = () => {
        const r = el.getBoundingClientRect();
        cb(r.height > 0 ? { width: r.width, height: r.height } : { width: 1000, height });
      };
      measure();
      if (typeof ResizeObserver === "undefined") return;
      const ro = new ResizeObserver(measure);
      ro.observe(el);
      return () => ro.disconnect();
    },
  });

  // keep the selected row in view when it was picked from the strip
  useEffect(() => {
    const i = rows.findIndex((r) => r.seq === selectedSeq);
    if (i >= 0) v.scrollToIndex(i, { align: "auto" });
  }, [selectedSeq, rows, v]);

  return (
    <div className="flex min-h-0 flex-col overflow-hidden rounded-md border border-line bg-surface" style={{ height }} data-testid="audit-table">
      <div className="table-head grid shrink-0 items-center gap-2 px-3 py-2" style={{ gridTemplateColumns: COLS }} role="row">
        <span className="text-right">Seq</span>
        <span>When</span>
        <span>Actor</span>
        <span>Action</span>
        <span>Subject</span>
        <span>Outcome</span>
        <span className="text-right">Hash</span>
      </div>
      <div ref={parent} className="min-h-0 flex-1 overflow-y-auto" role="grid" aria-label="Audit events, newest first" aria-rowcount={rows.length}>
        <div style={{ height: v.getTotalSize(), position: "relative" }}>
          {v.getVirtualItems().map((it) => {
            const e = rows[it.index];
            const sel = e.seq === selectedSeq;
            const cracked = afterCrack(e.seq, crackSeq);
            const kind = actorKind(e.actor_id);
            return (
              <button
                type="button"
                key={e.seq}
                role="row"
                aria-selected={sel}
                aria-rowindex={it.index + 1}
                data-testid="audit-row"
                data-seq={e.seq}
                data-allowed={e.allowed ? "true" : "false"}
                onClick={() => onSelect(e.seq)}
                className={cn(
                  "absolute left-0 grid w-full items-center gap-2 border-b border-line/70 px-3 text-left text-xs transition-colors duration-fast",
                  !e.allowed && "bg-bad-soft/40",
                  sel ? "bg-accent/10 shadow-[inset_3px_0_0_rgb(var(--accent))]" : "hover:bg-sunken/60",
                  sel && !e.allowed && "shadow-[inset_3px_0_0_rgb(var(--bad))]",
                  crackSeq != null && e.seq === crackSeq && "border-t-2 border-t-bad",
                )}
                style={{ gridTemplateColumns: COLS, height: ROW, transform: `translateY(${it.start}px)` }}
              >
                <span className={cn("num text-right", !e.allowed ? "font-semibold text-bad" : "text-ink-muted")}>{e.seq}</span>
                <span className="num truncate text-2xs text-ink-soft" title={timestamp(e.at)}>
                  {shortTime(e.at)}
                </span>
                <span className="min-w-0">
                  <span className="block truncate font-medium">{e.actor_name ?? e.actor_id}</span>
                  <span className="block truncate font-mono text-2xs text-ink-muted">
                    {e.actor_id}
                    {kind !== "person" ? ` · ${kind}` : ""}
                  </span>
                </span>
                <span className="truncate">
                  {e.allowed ? actionLabel(e.action) : attemptLabel(e.action)}
                  {e.human_approved ? <span className="ml-2 rounded-xs bg-ok-soft px-1.5 py-px text-2xs font-semibold text-ok">human</span> : null}
                </span>
                <span className="min-w-0">
                  <span className="block truncate font-mono text-xs">{e.subject_id}</span>
                  <span className="block truncate text-2xs text-ink-muted">{e.subject_type.replace(/_/g, " ")}</span>
                </span>
                <span className="min-w-0">
                  <span className={cn("text-2xs font-semibold uppercase tracking-wide", e.allowed ? "text-ok" : "text-bad")}>{e.allowed ? "Allowed" : "Refused"}</span>
                  {e.reason ? <span className="block truncate text-xs text-ink-soft">{e.reason}</span> : null}
                </span>
                <span className={cn("num truncate text-right font-mono text-2xs", cracked ? "text-bad line-through" : "text-ink-muted")} title={e.hash ?? undefined} data-testid="row-hash">
                  {e.hash ? e.hash.slice(0, 8) : "—"}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
