"use client";

import { AuditTable } from "./AuditTable";
import { ChainBanner } from "./ChainBanner";
import { ChainStrip } from "./ChainStrip";
import { EventDetail } from "./EventDetail";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { applyFilters, ascending, chainState, filterOptions, NO_FILTERS, type AuditFilters, type Outcome } from "@/lib/chain";
import { actionLabel } from "@/lib/labels";
import type { AuditResponse } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Search } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

const TABLE_HEIGHT = 440;

/** The trail itself, given its data: tests render this with a fixture. */
export function AuditView({
  data,
  loading,
  error,
  refetch,
  fetching,
  updatedAt,
  leaseId,
  onClearLease,
  fixture,
}: {
  data: AuditResponse | undefined;
  loading: boolean;
  error: unknown;
  refetch: () => void;
  fetching: boolean;
  updatedAt: number;
  leaseId?: string;
  onClearLease?: () => void;
  fixture?: boolean;
}) {
  const [filters, setFilters] = useState<AuditFilters>(NO_FILTERS);
  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);
  const [simulate, setSimulate] = useState(false);
  const set = <K extends keyof AuditFilters>(k: K, v: AuditFilters[K]) => setFilters((f) => ({ ...f, [k]: v }));

  const all = useMemo(() => ascending(data?.events ?? []), [data]);
  const newestFirst = useMemo(() => [...all].reverse(), [all]);
  const rows = useMemo(() => applyFilters(newestFirst, filters), [newestFirst, filters]);
  const visible = useMemo(() => (rows.length === newestFirst.length ? null : new Set(rows.map((e) => e.seq))), [rows, newestFirst]);
  const options = useMemo(() => filterOptions(all), [all]);
  // a simulation cracks the chain from the selected block onward (the newest when none is selected)
  const simulatedSeq = simulate ? (selectedSeq ?? all[all.length - 1]?.seq ?? null) : null;
  const state = chainState(data, simulatedSeq);
  const selected = all.find((e) => e.seq === selectedSeq) ?? null;
  const prev = selected ? (all[all.findIndex((e) => e.seq === selected.seq) - 1] ?? null) : null;
  const refused = all.filter((e) => !e.allowed).length;

  // the selected row must stay one the reader can see
  useEffect(() => {
    if (selectedSeq != null && !rows.some((e) => e.seq === selectedSeq)) setSelectedSeq(rows[0]?.seq ?? null);
  }, [rows, selectedSeq]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="shrink-0">
          <div className="eyebrow">Append-only · hash-chained</div>
          <h1 className="text-2xl font-semibold">Audit trail{leaseId ? ` · ${leaseId}` : ""}</h1>
          {leaseId && onClearLease ? (
            <button type="button" className="mt-1 text-xs text-ink-muted hover:text-accent" onClick={onClearLease}>
              Show every lease ✕
            </button>
          ) : null}
          {fixture ? <div className="mt-1 rounded-xs border border-warn-line bg-warn-soft px-2 py-0.5 text-2xs font-semibold uppercase tracking-wide text-warn">Fixture · a broken chain, for the demo</div> : null}
        </div>
        {data ? (
          <div className="min-w-0 flex-1 basis-72">
            <ChainBanner state={state} loading={fetching} onVerify={refetch} verifiedAt={updatedAt || null} />
          </div>
        ) : null}
      </div>

      {loading ? (
        <LoadingBlock rows={6} label="Loading audit trail" />
      ) : error ? (
        <ErrorState title="Could not load the audit trail" error={error} onRetry={refetch} />
      ) : !all.length ? (
        <EmptyState title="No events yet.">Every action, allowed or refused, will be sealed here as it happens.</EmptyState>
      ) : (
        <>
          <ChainStrip events={all} selectedSeq={selectedSeq} onSelect={setSelectedSeq} crackSeq={state.crackSeq} simulated={state.simulatedSeq != null} visible={visible} />

          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filters">
            <span className="flex rounded-full border border-line bg-surface p-0.5">
              {(
                [
                  ["all", `All · ${all.length}`],
                  ["allowed", "Allowed"],
                  ["refused", `Refused · ${refused}`],
                ] as [Outcome, string][]
              ).map(([v, l]) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={filters.outcome === v}
                  data-testid={`outcome-${v}`}
                  onClick={() => set("outcome", v)}
                  className={cn(
                    "h-7 rounded-full px-3 text-xs font-semibold transition-colors",
                    filters.outcome === v ? (v === "refused" ? "bg-bad-soft text-bad" : "bg-raised text-ink") : v === "refused" ? "text-bad/80 hover:text-bad" : "text-ink-muted hover:text-ink",
                  )}
                >
                  {l}
                </button>
              ))}
            </span>
            <Select label="Actor" value={filters.actor} onChange={(v) => set("actor", v)}>
              <option value="">All actors</option>
              <optgroup label="Kind">
                <option value="person">People</option>
                <option value="agent">Agents</option>
                <option value="system">System</option>
              </optgroup>
              <optgroup label="Who">
                {options.actors.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </optgroup>
            </Select>
            <Select label="Action" value={filters.action} onChange={(v) => set("action", v)}>
              <option value="">All actions</option>
              {options.actions.map((a) => (
                <option key={a} value={a}>
                  {actionLabel(a)}
                </option>
              ))}
            </Select>
            <Select label="Subject" value={filters.subject} onChange={(v) => set("subject", v)}>
              <option value="">All subjects</option>
              {options.subjects.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, " ")}
                </option>
              ))}
            </Select>
            <label className="flex h-9 items-center gap-2 rounded-sm border border-line-strong bg-surface px-2.5 text-sm">
              <Search aria-hidden className="h-3.5 w-3.5 text-ink-muted" />
              <input
                type="search"
                aria-label="Search by sequence number or hash prefix"
                placeholder="#seq or hash prefix"
                value={filters.query}
                onChange={(e) => set("query", e.target.value)}
                className="w-40 bg-transparent font-mono text-xs outline-none placeholder:text-ink-faint"
              />
            </label>
            <label className="ml-auto flex items-center gap-2 text-xs text-ink-soft" title="A client-side what-if: shows how the chain would crack from the selected block onward. Nothing is changed; the verdict above is the API's.">
              <input type="checkbox" checked={simulate} onChange={(e) => setSimulate(e.target.checked)} className="h-4 w-4 accent-[rgb(var(--warn))]" data-testid="simulate-toggle" />
              Simulate tampering
              <span className="text-2xs text-ink-muted">(simulation: nothing is changed)</span>
            </label>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
            {rows.length ? (
              <AuditTable rows={rows} selectedSeq={selectedSeq} onSelect={setSelectedSeq} crackSeq={state.crackSeq} height={TABLE_HEIGHT} />
            ) : (
              <div className="flex items-center rounded-md border border-line bg-surface p-5" style={{ height: TABLE_HEIGHT }}>
                <EmptyState title="Nothing matches." className="w-full">
                  {filters.query ? "No sequence number or hash starts with that." : "Clear a filter to see the rest."}
                </EmptyState>
              </div>
            )}
            <div className="overflow-hidden rounded-md border border-line bg-surface" style={{ height: TABLE_HEIGHT }}>
              <EventDetail event={selected} prev={prev} crackSeq={state.crackSeq} />
            </div>
          </div>
          <p className="text-xs text-ink-muted">
            Showing {rows.length.toLocaleString("en-US")} of {all.length.toLocaleString("en-US")} events, newest first. Refused attempts stay in the chain; they are never filtered out of the strip.
          </p>
        </>
      )}
    </div>
  );
}

function Select({ label, value, onChange, children }: { label: string; value: string; onChange: (v: string) => void; children: ReactNode }) {
  return (
    <select aria-label={`Filter by ${label.toLowerCase()}`} value={value} onChange={(e) => onChange(e.target.value)} className={cn("h-9 rounded-sm border border-line-strong bg-surface px-2 text-sm", value && "border-accent text-accent")}>
      {children}
    </select>
  );
}
