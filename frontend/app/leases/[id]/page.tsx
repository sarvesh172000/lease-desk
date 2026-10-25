"use client";

import { ObligationsTimeline } from "@/components/leases/ObligationsTimeline";
import { ScheduleChart } from "@/components/leases/ScheduleChart";
import { TermsPanel } from "@/components/leases/TermsPanel";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { day, money, period, signedMoney } from "@/lib/format";
import { useExceptions, useLeases, useLeaseVersions, useSchedule } from "@/lib/hooks";
import { chargeLabel, clinicLabel } from "@/lib/labels";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

export default function LeaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const leaseId = decodeURIComponent(id);
  const leases = useLeases();
  const exceptions = useExceptions();
  const lease = leases.data?.find((l) => l.lease_id === leaseId);
  const mine = (exceptions.data ?? []).filter((e) => e.lease_id === leaseId);
  const open = mine.filter((e) => e.status !== "balanced");

  if (leases.isLoading) return <LoadingBlock rows={6} label="Loading lease" />;
  if (leases.isError) return <ErrorState title="Could not load the lease" error={leases.error} onRetry={() => leases.refetch()} />;
  if (!lease)
    return (
      <EmptyState title="No such lease.">
        <Link className="text-accent underline" href="/leases">
          Back to leases
        </Link>
      </EmptyState>
    );

  return (
    <div className="space-y-5">
      <div>
        <Link href="/leases" className="text-sm text-ink-muted hover:text-accent">
          ← Leases
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{clinicLabel(lease.location, lease.clinic_id)}</h1>
          <StatusBadge status={lease.status} size="lg" />
        </div>
        <p className="mt-0.5 text-ink-muted">
          {lease.lessor} <span className="font-mono text-sm">· {lease.lease_id} · {lease.clinic_id}</span>
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Fact label="Monthly rent" value={money(lease.monthly_rent)} />
        <Fact label="Lease liability" value={money(lease.liability)} />
        <Fact label="Term ends" value={day(lease.end)} />
        <Link href={open.length ? `/exceptions/${encodeURIComponent(open[0].exception_id)}` : "/exceptions"} className="block rounded-md border border-line bg-surface px-4 py-3 shadow-raised transition-colors hover:border-line-strong">
          <div className="eyebrow">Open exceptions</div>
          <div className={cn("num mt-1 text-xl font-semibold", open.length ? "text-warn" : "text-ink")}>{open.length}</div>
          <div className="text-xs text-ink-muted">{open.length ? `${chargeLabel(open[0].charge_type)} · ${period(open[0].period)} →` : "Nothing open"}</div>
        </Link>
      </div>

      <TermsPanel leaseId={leaseId} />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <ScheduleCard leaseId={leaseId} />
        <div className="space-y-5">
          <Card>
            <CardHeader eyebrow="Deadlines" title="Obligations" />
            <CardBody>
              <ObligationsTimeline leaseId={leaseId} />
            </CardBody>
          </Card>
          {mine.length ? (
            <Card>
              <CardHeader eyebrow="Exceptions" title="Raised on this lease" />
              <ul className="divide-y divide-line">
                {mine.map((e) => (
                  <li key={e.exception_id}>
                    <Link href={`/exceptions/${encodeURIComponent(e.exception_id)}`} className="flex items-center gap-3 px-5 py-2.5 text-sm hover:bg-sunken/60">
                      <StatusBadge status={e.status} />
                      <span className="min-w-0 flex-1 truncate">
                        {chargeLabel(e.charge_type)} <span className="text-ink-muted">· {period(e.period)}</span>
                      </span>
                      <span className={cn("num font-semibold", e.delta === 0 ? "text-ink" : "text-bad")}>{signedMoney(e.delta)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
          <p className="text-sm">
            <Link href={`/audit?lease_id=${encodeURIComponent(leaseId)}`} className="text-accent hover:underline">
              Audit trail for {leaseId} →
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

/** The schedule as a chart and a table, for the versions the lease has; two versions overlay. */
function ScheduleCard({ leaseId }: { leaseId: string }) {
  const versions = useLeaseVersions(leaseId);
  const nums = [...(versions.data ?? [])].map((v) => v.version).sort((a, b) => a - b);
  const first = nums[0];
  const last = nums.length > 1 ? nums[nums.length - 1] : undefined;
  // the active schedule when the lease lists no versions (fixtures); otherwise only versions on record
  const askActive = versions.isSuccess && nums.length === 0;
  const before = useSchedule(leaseId, first, versions.isSuccess && first != null);
  const active = useSchedule(leaseId, undefined, askActive);
  const afterQ = useSchedule(leaseId, last, last != null);
  // only a second version on record counts as "after"; a disabled query must not borrow the active schedule's cache
  const after = last != null ? afterQ.data : undefined;
  const [shown, setShown] = useState<"chart" | "table">("chart");
  const base = before.data ?? active.data;
  const loading = versions.isLoading || before.isLoading || active.isLoading;
  const rowsOf = shown === "table" ? (after ?? base) : null;

  return (
    <Card>
      <CardHeader
        eyebrow="ASC 842 · operating"
        title={base ? `Schedule${after ? ` v${base.version} → v${after.version}` : ` v${base.version}${base.active ? " (active)" : ""}`} from ${period(base.effective_from)}` : "Schedule"}
        actions={
          <div className="flex rounded-sm border border-line p-0.5" role="group" aria-label="Chart or table">
            {(["chart", "table"] as const).map((v) => (
              <button key={v} type="button" aria-pressed={shown === v} onClick={() => setShown(v)} className={cn("h-7 rounded-[4px] px-2.5 text-xs font-medium capitalize transition-colors", shown === v ? "bg-accent text-accent-ink" : "text-ink-soft hover:bg-sunken")}>
                {v}
              </button>
            ))}
          </div>
        }
      />
      {loading ? (
        <CardBody>
          <LoadingBlock rows={5} label="Loading schedule" />
        </CardBody>
      ) : before.isError || active.isError ? (
        <CardBody>
          <ErrorState title="Could not load the schedule" error={before.error ?? active.error} onRetry={() => (before.isError ? before.refetch() : active.refetch())} />
        </CardBody>
      ) : !base || !base.rows.length ? (
        <CardBody>
          <EmptyState title="No schedule yet.">The engine builds the schedule once the lease terms are confirmed.</EmptyState>
        </CardBody>
      ) : shown === "chart" ? (
        <CardBody>
          <ScheduleChart before={base} after={after} />
          <p className="mt-2 text-xs text-ink-muted">
            {base.rows.length} months · opening liability <span className="num">{money(base.opening_liability)}</span> · opening ROU <span className="num">{money(base.opening_rou)}</span>
            {after ? ` · v${after.version} dashed` : nums.length === 1 ? " · the remeasured schedule overlays here once revised terms are approved" : ""}
          </p>
        </CardBody>
      ) : (
        <div className="max-h-[420px] overflow-y-auto">
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 z-10">
              <tr className="table-head bg-sunken">
                <th className="py-2 pl-5 font-semibold">#</th>
                <th className="px-3 py-2 font-semibold">Period</th>
                <th className="px-3 py-2 text-right font-semibold">Payment</th>
                <th className="px-3 py-2 text-right font-semibold">Interest</th>
                <th className="px-3 py-2 text-right font-semibold">Liability close</th>
                <th className="px-3 py-2 text-right font-semibold">ROU close</th>
                <th className="px-3 py-2 pr-5 text-right font-semibold">Lease cost</th>
              </tr>
            </thead>
            <tbody>
              {rowsOf!.rows.map((r) => (
                <tr key={r.period} className="border-b border-line/60">
                  <td className="num py-1.5 pl-5 text-ink-faint">{r.index}</td>
                  <td className="px-3 py-1.5">{period(r.period)}</td>
                  <td className="num px-3 py-1.5 text-right">{money(r.payment)}</td>
                  <td className="num px-3 py-1.5 text-right text-ink-soft">{money(r.interest)}</td>
                  <td className="num px-3 py-1.5 text-right">{money(r.liability_close)}</td>
                  <td className="num px-3 py-1.5 text-right">{money(r.rou_close)}</td>
                  <td className="num px-3 py-1.5 pr-5 text-right">{money(r.straight_line_cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-surface px-4 py-3 shadow-raised">
      <div className="eyebrow">{label}</div>
      <div className="num mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}
