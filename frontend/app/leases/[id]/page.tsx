"use client";

import { LeaseVersionPanel } from "@/components/LeaseVersionPanel";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { ApiError } from "@/lib/api";
import { day, humanize, money, period, signedMoney } from "@/lib/format";
import { useExceptions, useLeases, useSchedule } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

export default function LeaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const leaseId = decodeURIComponent(id);
  const [version, setVersion] = useState<number | undefined>(undefined);

  const leases = useLeases();
  const exceptions = useExceptions();
  const schedule = useSchedule(leaseId, version);

  const lease = leases.data?.find((l) => l.lease_id === leaseId);
  const mine = (exceptions.data ?? []).filter((e) => e.lease_id === leaseId);

  if (leases.isLoading) return <LoadingBlock rows={6} label="Loading lease" />;
  if (leases.isError) return <ErrorState title="Could not load the lease" error={leases.error} onRetry={() => leases.refetch()} />;
  if (!lease) return <EmptyState title={`No lease ${leaseId}.`}><Link className="text-accent underline" href="/leases">Back to leases</Link></EmptyState>;

  const notFound = schedule.error instanceof ApiError && schedule.error.status === 404;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/leases" className="text-sm text-ink-muted hover:text-accent">
          ← Leases
        </Link>
        <div className="mt-1 flex items-center gap-3">
          <h1 className="text-2xl font-semibold">{lease.location}</h1>
          <StatusBadge status={lease.status} size="lg" />
        </div>
        <p className="mt-0.5 text-ink-muted">
          {lease.lease_id} · {lease.clinic_id} · {lease.lessor}
        </p>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <Fact label="Monthly rent" value={money(lease.monthly_rent)} />
        <Fact label="Lease liability" value={money(lease.liability)} />
        <Fact label="Term ends" value={day(lease.end)} />
        <Fact label="Open exceptions" value={String(mine.filter((e) => e.status !== "balanced").length)} />
      </div>

      <LeaseVersionPanel leaseId={leaseId} />

      {mine.length ? (
        <Card>
          <CardHeader eyebrow="Exceptions" title="Raised on this lease" />
          <ul className="divide-y divide-line">
            {mine.map((e) => (
              <li key={e.exception_id}>
                <Link href={`/exceptions/${encodeURIComponent(e.exception_id)}`} className="flex items-center gap-4 px-5 py-3 hover:bg-sunken/60">
                  <StatusBadge status={e.status} />
                  <span className="font-medium">{humanize(e.charge_type)}</span>
                  <span className="text-ink-muted">{period(e.period)}</span>
                  <span className={cn("num ml-auto font-semibold", e.delta === 0 ? "text-ink" : "text-bad")}>{signedMoney(e.delta)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Card>
        <CardHeader
          eyebrow="ASC 842 · operating"
          title={schedule.data ? `Schedule v${schedule.data.version}${schedule.data.active ? " (active)" : " (proposed)"} from ${period(schedule.data.effective_from)}` : "Schedule"}
          actions={
            <div className="flex items-center gap-1" role="group" aria-label="Schedule version">
              {[undefined, 1, 2].map((v) => (
                <button
                  key={String(v)}
                  type="button"
                  aria-pressed={version === v}
                  onClick={() => setVersion(v)}
                  className={cn("h-8 rounded border px-2.5 text-sm", version === v ? "border-accent bg-accent-soft text-accent" : "border-line-strong text-ink-soft hover:bg-sunken")}
                >
                  {v === undefined ? "Active" : `v${v}`}
                </button>
              ))}
            </div>
          }
        />
        {schedule.isLoading ? (
          <CardBody>
            <LoadingBlock rows={6} label="Loading schedule" />
          </CardBody>
        ) : notFound ? (
          <CardBody>
            <EmptyState title={`No schedule ${version ? `v${version}` : ""} for ${leaseId}.`}>The engine has not built this version.</EmptyState>
          </CardBody>
        ) : schedule.isError ? (
          <CardBody>
            <ErrorState title="Could not load the schedule" error={schedule.error} onRetry={() => schedule.refetch()} />
          </CardBody>
        ) : schedule.data && schedule.data.rows.length ? (
          <div className="max-h-[560px] overflow-y-auto">
            <table className="w-full border-collapse text-sm">
              <thead className="sticky top-0 z-10">
                <tr className="table-head bg-sunken">
                  <th className="py-2 pl-5 font-semibold">#</th>
                  <th className="px-3 py-2 font-semibold">Period</th>
                  <th className="px-3 py-2 text-right font-semibold">Payment</th>
                  <th className="px-3 py-2 text-right font-semibold">Interest</th>
                  <th className="px-3 py-2 text-right font-semibold">Liability open</th>
                  <th className="px-3 py-2 text-right font-semibold">Liability close</th>
                  <th className="px-3 py-2 text-right font-semibold">ROU amort.</th>
                  <th className="px-3 py-2 text-right font-semibold">ROU close</th>
                  <th className="px-3 py-2 pr-5 text-right font-semibold">Lease cost</th>
                </tr>
              </thead>
              <tbody>
                {schedule.data.rows.map((r) => (
                  <tr key={r.period} className={cn("border-b border-line/60", r.period.startsWith("2026-07") && "bg-warn-soft/60")}>
                    <td className="num py-1.5 pl-5 text-ink-faint">{r.index}</td>
                    <td className="px-3 py-1.5">{period(r.period)}</td>
                    <td className="num px-3 py-1.5 text-right">{money(r.payment)}</td>
                    <td className="num px-3 py-1.5 text-right text-ink-soft">{money(r.interest)}</td>
                    <td className="num px-3 py-1.5 text-right text-ink-soft">{money(r.liability_open)}</td>
                    <td className="num px-3 py-1.5 text-right">{money(r.liability_close)}</td>
                    <td className="num px-3 py-1.5 text-right text-ink-soft">{money(r.rou_amortization)}</td>
                    <td className="num px-3 py-1.5 text-right">{money(r.rou_close)}</td>
                    <td className="num px-3 py-1.5 pr-5 text-right">{money(r.straight_line_cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <CardBody>
            <EmptyState title="This schedule has no rows." />
          </CardBody>
        )}
      </Card>

      <p className="text-sm">
        <Link href={`/audit?lease_id=${encodeURIComponent(leaseId)}`} className="text-accent hover:underline">
          Audit trail for {leaseId} →
        </Link>
      </p>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-surface px-4 py-3 shadow-card">
      <div className="eyebrow">{label}</div>
      <div className="num mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}
