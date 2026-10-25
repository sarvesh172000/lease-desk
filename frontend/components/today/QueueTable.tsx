"use client";

import { StatusBadge } from "@/components/StatusBadge";
import { money, pct, period, signedMoney } from "@/lib/format";
import { visibleColumns, type ColumnSpec } from "@/lib/columns";
import { chargeLabel, placeLabel } from "@/lib/labels";
import type { ExceptionSummary, LeaseSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, type ReactNode } from "react";

/** Cell padding: the first and last columns line up with the card edge. */
function edgePad(i: number, count: number): string {
  if (i === 0) return "pl-5 pr-2";
  if (i === count - 1) return "pl-2 pr-5";
  return "px-2";
}

export interface QueueRow extends ExceptionSummary {
  /** The clinic in words, from the lease's location. */
  place: string | null;
}

/** Exceptions joined to their leases, so the queue can say "Daly City, Suite 210". */
export function toQueueRows(exceptions: ExceptionSummary[], leases: LeaseSummary[] | undefined): QueueRow[] {
  const byLease = new Map((leases ?? []).map((l) => [l.lease_id, l]));
  return exceptions.map((e) => ({ ...e, place: placeLabel(byLease.get(e.lease_id)?.location) }));
}

type Col = ColumnSpec<QueueRow> & { header: string; num?: boolean; cell: (r: QueueRow) => ReactNode };

/** Every column the queue can show; the ones that say the same thing on every row are dropped at render. */
const COLUMNS: Col[] = [
  { key: "status", header: "Status", always: true, get: (r) => r.status, cell: (r) => <StatusBadge status={r.status} /> },
  {
    key: "charge",
    header: "Charge",
    always: true,
    get: (r) => r.charge_type,
    cell: (r) => (
      <div className="min-w-0">
        <Link
          href={`/exceptions/${encodeURIComponent(r.exception_id)}`}
          className="font-medium text-ink hover:text-accent hover:underline"
          onClick={(ev) => ev.stopPropagation()}
        >
          {chargeLabel(r.charge_type)}
        </Link>
        <div className="truncate text-xs text-ink-muted">
          {r.place ?? r.clinic_id}
          <span className="font-mono"> · {r.lease_id}</span>
        </div>
      </div>
    ),
  },
  { key: "period", header: "Period", get: (r) => r.period?.slice(0, 7), cell: (r) => <span className="whitespace-nowrap">{period(r.period)}</span> },
  { key: "expected", header: "Lease supports", num: true, get: (r) => r.expected, cell: (r) => <span className="text-ink-soft">{money(r.expected)}</span> },
  { key: "actual", header: "Billed", num: true, get: (r) => r.actual, cell: (r) => money(r.actual) },
  // compact mode only: the two figures stacked in one column, so the queue fits beside a side panel
  {
    key: "billed_vs",
    header: "Billed · supports",
    num: true,
    always: true,
    get: (r) => [r.actual, r.expected],
    cell: (r) => (
      <span className="flex flex-col leading-tight">
        <span>{money(r.actual)}</span>
        <span className="text-xs text-ink-muted">{money(r.expected)}</span>
      </span>
    ),
  },
  {
    key: "variance",
    header: "Variance",
    num: true,
    always: true,
    get: (r) => r.delta,
    cell: (r) => <span className={cn("font-semibold", r.delta === 0 ? "text-ink" : "text-bad")}>{signedMoney(r.delta)}</span>,
  },
  { key: "confidence", header: "Conf.", num: true, get: (r) => r.confidence, cell: (r) => <span className="text-ink-soft">{pct(r.confidence)}</span> },
];

/**
 * The queue as a dense table: readable names first, ids second, money
 * tabular and right-aligned. Columns that would read the same on every row
 * are hidden; a highlighted row follows the keyboard.
 */
const WIDE = new Set(["billed_vs"]);
const COMPACT = new Set(["expected", "actual", "confidence"]);

export function QueueTable({
  rows,
  highlight = -1,
  onHighlight,
  dense,
  compact,
  testId = "exception-row",
}: {
  rows: QueueRow[];
  highlight?: number;
  onHighlight?: (i: number) => void;
  dense?: boolean;
  /** Beside a side panel: billed and supported stack in one column, confidence goes. */
  compact?: boolean;
  testId?: string;
}) {
  const router = useRouter();
  const cols = useMemo(() => {
    const pool = COLUMNS.filter((c) => (compact ? !COMPACT.has(c.key) : !WIDE.has(c.key)));
    return visibleColumns(rows, pool) as Col[];
  }, [rows, compact]);
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);
  useEffect(() => {
    if (highlight >= 0) rowRefs.current[highlight]?.scrollIntoView({ block: "nearest" });
  }, [highlight]);

  return (
    // on a phone the table scrolls inside its card, not the page
    <div className="overflow-x-auto">
      <table className={cn("w-full border-collapse", dense ? "text-sm" : "text-[0.95rem]")} data-testid="queue-table">
        <thead>
          <tr className="table-head">
            {cols.map((c, i) => (
              <th key={c.key} className={cn("py-2 font-semibold", edgePad(i, cols.length), c.num && "text-right")} data-col={c.key}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, idx) => (
            <tr
              key={r.exception_id}
              ref={(el) => {
                rowRefs.current[idx] = el;
              }}
              data-testid={testId}
              data-highlighted={highlight === idx ? "true" : undefined}
              aria-selected={highlight === idx ? true : undefined}
              className={cn(
                "cursor-pointer border-b border-line/70 transition-colors duration-fast",
                highlight === idx ? "bg-accent/10 shadow-[inset_2px_0_0_rgb(var(--accent))]" : "hover:bg-sunken/60",
              )}
              onClick={() => router.push(`/exceptions/${encodeURIComponent(r.exception_id)}`)}
              onMouseEnter={() => onHighlight?.(idx)}
            >
              {cols.map((c, i) => (
                <td
                  key={c.key}
                  className={cn(dense ? "py-2" : "py-3", edgePad(i, cols.length), c.num && "num whitespace-nowrap text-right")}
                >
                  {c.cell(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
