"use client";

import { StatusBadge } from "@/components/StatusBadge";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { day, money, STATUS_LABEL } from "@/lib/format";
import { useLeases } from "@/lib/hooks";
import type { LeaseSummary, Status } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnFiltersState,
  type SortingState,
} from "@tanstack/react-table";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

const STATUSES: Status[] = ["exception", "pending_review", "escalated", "balanced"];
const col = createColumnHelper<LeaseSummary>();

const columns = [
  col.accessor("status", {
    header: "Status",
    cell: (c) => <StatusBadge status={c.getValue()} />,
    filterFn: "equalsString",
    sortingFn: (a, b) => STATUSES.indexOf(a.original.status) - STATUSES.indexOf(b.original.status),
  }),
  col.accessor("lease_id", {
    header: "Lease",
    cell: (c) => (
      <Link href={`/leases/${encodeURIComponent(c.getValue())}`} className="font-medium hover:text-accent hover:underline" onClick={(e) => e.stopPropagation()}>
        {c.getValue()}
      </Link>
    ),
  }),
  col.accessor("clinic_id", { header: "Clinic", filterFn: "equalsString" }),
  col.accessor("location", {
    header: "Location",
    cell: (c) => (
      <div className="min-w-0">
        <div className="truncate">{c.getValue()}</div>
        <div className="truncate text-xs text-ink-muted">{c.row.original.lessor}</div>
      </div>
    ),
  }),
  col.accessor("monthly_rent", { header: "Monthly rent", meta: { num: true }, cell: (c) => money(c.getValue()) }),
  col.accessor("liability", { header: "Liability", meta: { num: true }, cell: (c) => money(c.getValue()) }),
  col.accessor("end", { header: "Ends", cell: (c) => day(c.getValue()) }),
];

export default function LeasesPage() {
  const q = useLeases();
  const router = useRouter();
  const [sorting, setSorting] = useState<SortingState>([{ id: "status", desc: false }]);
  const [filters, setFilters] = useState<ColumnFiltersState>([]);
  const [search, setSearch] = useState("");

  const data = useMemo(() => q.data ?? [], [q.data]);
  const table = useReactTable({
    data,
    columns,
    state: { sorting, columnFilters: filters, globalFilter: search },
    onSortingChange: setSorting,
    onColumnFiltersChange: setFilters,
    onGlobalFilterChange: setSearch,
    globalFilterFn: "includesString",
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const statusFilter = (filters.find((f) => f.id === "status")?.value as string | undefined) ?? "";
  const clinicFilter = (filters.find((f) => f.id === "clinic_id")?.value as string | undefined) ?? "";
  const setFilter = (id: string, value: string) =>
    setFilters((prev) => [...prev.filter((f) => f.id !== id), ...(value ? [{ id, value }] : [])]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const l of data) c[l.status] = (c[l.status] ?? 0) + 1;
    return c;
  }, [data]);
  const clinics = useMemo(() => Array.from(new Set(data.map((l) => l.clinic_id))).sort(), [data]);
  const rows = table.getRowModel().rows;

  return (
    <div className="space-y-5">
      <div>
        <div className="eyebrow">Portfolio</div>
        <h1 className="text-2xl font-semibold">Leases</h1>
      </div>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter by status">
        <CountChip label="All" count={data.length} active={!statusFilter} onClick={() => setFilter("status", "")} />
        {STATUSES.map((s) => (
          <CountChip key={s} label={STATUS_LABEL[s]} status={s} count={counts[s] ?? 0} active={statusFilter === s} onClick={() => setFilter("status", statusFilter === s ? "" : s)} />
        ))}
        <div className="ml-auto flex items-center gap-2">
          <select
            aria-label="Filter by clinic"
            className="h-9 rounded-md border border-line-strong bg-surface px-2 text-sm"
            value={clinicFilter}
            onChange={(e) => setFilter("clinic_id", e.target.value)}
          >
            <option value="">All clinics</option>
            {clinics.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <input
            type="search"
            placeholder="Search location, lessor…"
            aria-label="Search leases"
            className="h-9 w-64 rounded-md border border-line-strong bg-surface px-3 text-sm placeholder:text-ink-faint"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <Card>
        {q.isLoading ? (
          <div className="p-5">
            <LoadingBlock rows={5} label="Loading leases" />
          </div>
        ) : q.isError ? (
          <div className="p-5">
            <ErrorState title="Could not load leases" error={q.error} onRetry={() => q.refetch()} />
          </div>
        ) : !data.length ? (
          <div className="p-5">
            <EmptyState title="No leases yet.">Ingest a lease PDF to start a schedule.</EmptyState>
          </div>
        ) : (
          <table className="w-full table-fixed border-collapse text-[0.95rem]">
            <colgroup>
              <col className="w-40" />
              <col className="w-28" />
              <col className="w-28" />
              <col />
              <col className="w-36" />
              <col className="w-40" />
              <col className="w-32" />
            </colgroup>
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id} className="table-head">
                  {hg.headers.map((h, i) => {
                    const num = (h.column.columnDef.meta as { num?: boolean } | undefined)?.num;
                    const sorted = h.column.getIsSorted();
                    return (
                      <th key={h.id} className={cn("px-3 py-2 font-semibold", i === 0 && "pl-5", num && "text-right")} aria-sort={sorted ? (sorted === "asc" ? "ascending" : "descending") : "none"}>
                        <button type="button" className={cn("inline-flex items-center gap-1 uppercase", num && "flex-row-reverse")} onClick={h.column.getToggleSortingHandler()}>
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          <span aria-hidden className="text-ink-faint">{sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : ""}</span>
                        </button>
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {rows.length ? (
                rows.map((r) => (
                  <tr key={r.id} className="cursor-pointer border-b border-line/70 hover:bg-sunken/60" onClick={() => router.push(`/leases/${encodeURIComponent(r.original.lease_id)}`)}>
                    {r.getVisibleCells().map((c, i) => {
                      const num = (c.column.columnDef.meta as { num?: boolean } | undefined)?.num;
                      return (
                        <td key={c.id} className={cn("px-3 py-3 align-middle", i === 0 && "pl-5", num && "num text-right")}>
                          {flexRender(c.column.columnDef.cell, c.getContext())}
                        </td>
                      );
                    })}
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={columns.length} className="p-5">
                    <EmptyState title="No leases match these filters." />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </Card>
      {data.length ? (
        <p className="text-xs text-ink-muted">
          Showing {rows.length} of {data.length} leases.
        </p>
      ) : null}
    </div>
  );
}

function CountChip({ label, count, active, onClick, status }: { label: string; count: number; active: boolean; onClick: () => void; status?: Status }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm font-medium transition-colors",
        active ? "border-accent bg-accent text-white" : "border-line-strong bg-surface text-ink-soft hover:bg-sunken",
        !active && count === 0 && "opacity-60",
      )}
    >
      {label}
      <span className={cn("num rounded px-1.5 text-xs font-semibold", active ? "bg-white/20" : status === "exception" && count ? "bg-bad-soft text-bad" : "bg-sunken")}>{count}</span>
    </button>
  );
}
