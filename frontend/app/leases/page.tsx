"use client";

import { Runway } from "@/components/leases/Runway";
import { StatusBadge } from "@/components/StatusBadge";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { day, money, STATUS_LABEL } from "@/lib/format";
import { regionOfLocation, REGION_ORDER } from "@/lib/geo";
import { useChargeChecks, useLeases, useObligations, useSummary } from "@/lib/hooks";
import { placeLabel, regionLabel } from "@/lib/labels";
import type { LeaseSummary, Status } from "@/lib/types";
import { cn } from "@/lib/utils";
import { List, Rows3 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

const STATUSES: Status[] = ["exception", "pending_review", "escalated", "balanced"];

export default function LeasesPage() {
  const q = useLeases();
  const summary = useSummary();
  const checks = useChargeChecks();
  const obligations = useObligations({ within_days: 2000 });
  const router = useRouter();
  const [view, setView] = useState<"runway" | "table">("runway");
  const [status, setStatus] = useState<Status | "">("");
  const [region, setRegion] = useState("");
  const [search, setSearch] = useState("");

  const data = useMemo(() => q.data ?? [], [q.data]);
  // the clinic's region from the queue when the API knows it; the city table otherwise
  const regionOfClinic = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of checks.data ?? []) if (c.clinic_id && c.region_id) m.set(c.clinic_id, c.region_id);
    return m;
  }, [checks.data]);
  const regionOf = (l: LeaseSummary) => regionOfClinic.get(l.clinic_id) ?? regionOfLocation(l.location);

  const rows = useMemo(() => {
    const s = search.trim().toLowerCase();
    return data.filter(
      (l) =>
        (!status || l.status === status) &&
        (!region || regionOf(l) === region) &&
        (!s || l.location.toLowerCase().includes(s) || l.lessor.toLowerCase().includes(s) || l.lease_id.toLowerCase().includes(s) || l.clinic_id.toLowerCase().includes(s)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, status, region, search, regionOfClinic]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const l of data) c[l.status] = (c[l.status] ?? 0) + 1;
    return c;
  }, [data]);
  const regions = useMemo(() => {
    const set = new Set(data.map(regionOf));
    return [...REGION_ORDER.filter((r) => set.has(r)), ...Array.from(set).filter((r) => !(REGION_ORDER as string[]).includes(r))];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, regionOfClinic]);
  const totalRent = data.reduce((s, l) => s + l.monthly_rent, 0);
  const totalLiability = data.reduce((s, l) => s + l.liability, 0);

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="eyebrow">Portfolio</div>
          <h1 className="text-2xl font-semibold">
            Leases
            {q.data ? (
              <span className="num ml-2 text-base font-normal text-ink-muted">
                · {data.length} lease{data.length === 1 ? "" : "s"} · {money(totalRent)} a month · {money(totalLiability)} liability
              </span>
            ) : null}
          </h1>
        </div>
        <div className="flex rounded-sm border border-line bg-surface p-0.5" role="group" aria-label="View">
          {(
            [
              ["runway", "Runway", Rows3],
              ["table", "Table", List],
            ] as const
          ).map(([v, l, Icon]) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              data-testid={`view-${v}`}
              onClick={() => setView(v)}
              className={cn("flex h-8 items-center gap-1.5 rounded-[4px] px-3 text-sm font-medium transition-colors", view === v ? "bg-accent text-accent-ink" : "text-ink-soft hover:bg-sunken")}
            >
              <Icon aria-hidden className="h-3.5 w-3.5" />
              {l}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filters">
        <CountChip label="All" count={data.length} active={!status} onClick={() => setStatus("")} />
        {STATUSES.map((s) => (
          <CountChip key={s} label={STATUS_LABEL[s]} status={s} count={counts[s] ?? 0} active={status === s} onClick={() => setStatus(status === s ? "" : s)} />
        ))}
        <span className="mx-1 h-5 w-px bg-line" aria-hidden />
        {regions.length > 1 ? (
          <select aria-label="Filter by region" className="h-9 rounded-sm border border-line-strong bg-surface px-2 text-sm" value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">All regions</option>
            {regions.map((r) => (
              <option key={r} value={r}>
                {regionLabel(r)}
              </option>
            ))}
          </select>
        ) : null}
        <input
          type="search"
          placeholder="Search location, lessor…"
          aria-label="Search leases"
          className="ml-auto h-9 w-64 rounded-sm border border-line-strong bg-surface px-3 text-sm placeholder:text-ink-faint"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {q.isLoading ? (
        <Card className="p-5">
          <LoadingBlock rows={5} label="Loading leases" />
        </Card>
      ) : q.isError ? (
        <Card className="p-5">
          <ErrorState title="Could not load leases" error={q.error} onRetry={() => q.refetch()} />
        </Card>
      ) : !data.length ? (
        <Card className="p-5">
          <EmptyState title="No leases yet.">Ingest a lease PDF to start a schedule.</EmptyState>
        </Card>
      ) : !rows.length ? (
        <Card className="p-5">
          <EmptyState title="Nothing matches these filters.">Clear a filter to see the rest.</EmptyState>
        </Card>
      ) : view === "runway" ? (
        summary.data ? (
          <Runway leases={rows} today={summary.data.as_of} obligations={obligations.data?.obligations ?? []} regionOf={regionOf} />
        ) : summary.isError ? (
          <ErrorState title="The business clock is unavailable" error={summary.error} onRetry={() => summary.refetch()} />
        ) : (
          <LoadingBlock rows={4} label="Loading the business clock" />
        )
      ) : (
        <LeaseTable rows={rows} regionOf={regionOf} onOpen={(id) => router.push(`/leases/${encodeURIComponent(id)}`)} />
      )}
      <p className="text-xs text-ink-muted">
        Showing {rows.length} of {data.length} leases{view === "runway" ? ", by region, soonest end first" : ""}.
      </p>
    </div>
  );
}

/** The accessible fallback: the same leases as a table. */
function LeaseTable({ rows, regionOf, onOpen }: { rows: LeaseSummary[]; regionOf: (l: LeaseSummary) => string; onOpen: (id: string) => void }) {
  return (
    <Card className="overflow-hidden">
      <table className="w-full border-collapse text-[0.95rem]" data-testid="lease-table">
        <thead>
          <tr className="table-head">
            <th className="py-2 pl-5 pr-2 font-semibold">Status</th>
            <th className="px-2 py-2 font-semibold">Store</th>
            <th className="px-2 py-2 font-semibold">Region</th>
            <th className="px-2 py-2 text-right font-semibold">Monthly rent</th>
            <th className="px-2 py-2 text-right font-semibold">Liability</th>
            <th className="px-2 py-2 pr-5 font-semibold">Ends</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((l) => (
            <tr key={l.lease_id} className="cursor-pointer border-b border-line/70 hover:bg-sunken/60" onClick={() => onOpen(l.lease_id)}>
              <td className="py-3 pl-5 pr-2">
                <StatusBadge status={l.status} />
              </td>
              <td className="px-2 py-3">
                <Link href={`/leases/${encodeURIComponent(l.lease_id)}`} className="font-medium hover:text-accent hover:underline" onClick={(e) => e.stopPropagation()}>
                  {placeLabel(l.location) ?? l.location}
                </Link>
                <div className="truncate text-xs text-ink-muted">
                  {l.lessor} <span className="font-mono">· {l.lease_id} · {l.clinic_id}</span>
                </div>
              </td>
              <td className="px-2 py-3 text-ink-soft">{regionLabel(regionOf(l))}</td>
              <td className="num px-2 py-3 text-right">{money(l.monthly_rent)}</td>
              <td className="num px-2 py-3 text-right">{money(l.liability)}</td>
              <td className="px-2 py-3 pr-5 whitespace-nowrap">{day(l.end)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function CountChip({ label, count, active, onClick, status }: { label: string; count: number; active: boolean; onClick: () => void; status?: Status }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      data-status={status}
      className={cn(
        "flex h-9 items-center gap-2 rounded-full border px-3 text-sm transition-colors duration-fast",
        active ? "border-accent bg-accent-soft text-accent" : "border-line bg-surface text-ink-soft hover:border-line-strong hover:text-ink",
        !active && count === 0 && "opacity-60",
      )}
    >
      {label}
      <span className={cn("num rounded-full px-1.5 text-xs font-semibold", active ? "bg-accent text-accent-ink" : "bg-sunken text-ink-muted")}>{count}</span>
    </button>
  );
}
