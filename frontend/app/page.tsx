"use client";

import { AgentActivityFeed } from "@/components/AgentActivityFeed";
import { MetricTile } from "@/components/MetricTile";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { getExceptions, getLeases } from "@/lib/api";
import { humanize, money, pct, period, signedMoney } from "@/lib/format";
import type { ExceptionSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

const isOpen = (e: ExceptionSummary) => e.status !== "balanced";

export default function DashboardPage() {
  const leases = useQuery({ queryKey: ["leases"], queryFn: getLeases });
  const exceptions = useQuery({ queryKey: ["exceptions"], queryFn: getExceptions });
  const router = useRouter();

  const open = (exceptions.data ?? []).filter(isOpen);
  // Display aggregate only: total of the variances the API reports (in cents).
  const heldCents = open.reduce((s, e) => s + Math.abs(Math.round(e.delta * 100)), 0);
  const leaseCount = leases.data?.length ?? 0;
  const leasesWithIssues = (leases.data ?? []).filter((l) => l.status !== "balanced").length;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="eyebrow">Controller review</div>
          <h1 className="text-2xl font-semibold">Today</h1>
        </div>
        <p className="max-w-md text-right text-sm text-ink-muted">
          The model reads, the code calculates. Every figure below comes from the deterministic engine.
        </p>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <MetricTile
          label="Active leases"
          loading={leases.isLoading}
          value={leases.isError ? "—" : leaseCount}
          sub={leases.isError ? "Leases unavailable" : `${leasesWithIssues} need attention`}
        />
        <MetricTile
          label="Open exceptions"
          tone={open.length ? "warn" : "ok"}
          loading={exceptions.isLoading}
          value={exceptions.isError ? "—" : open.length}
          sub={exceptions.isError ? "Exceptions unavailable" : `${open.filter((e) => e.status === "pending_review").length} pending your review`}
        />
        <MetricTile
          label="Dollars held"
          tone={heldCents ? "bad" : "ok"}
          loading={exceptions.isLoading}
          value={exceptions.isError ? "—" : money(heldCents / 100)}
          sub="Sum of open variances"
        />
        <MetricTile
          label="Portfolio liability"
          loading={leases.isLoading}
          value={leases.isError ? "—" : money(sumCents(leases.data?.map((l) => l.liability) ?? []) / 100, { whole: true })}
          sub="As reported per lease"
        />
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_320px] gap-6">
        <Card>
          <CardHeader
            eyebrow="Queue"
            title="Exceptions"
            actions={<span className="text-sm text-ink-muted">{exceptions.data ? `${open.length} open of ${exceptions.data.length}` : ""}</span>}
          />
          {exceptions.isLoading ? (
            <CardBody>
              <LoadingBlock rows={3} label="Loading exceptions" />
            </CardBody>
          ) : exceptions.isError ? (
            <CardBody>
              <ErrorState title="Could not load exceptions" error={exceptions.error} onRetry={() => exceptions.refetch()} />
            </CardBody>
          ) : !exceptions.data?.length ? (
            <CardBody>
              <EmptyState title="No exceptions.">Every payment matched its schedule.</EmptyState>
            </CardBody>
          ) : (
            <table className="w-full border-collapse text-[0.95rem]">
              <thead>
                <tr className="table-head">
                  <th className="py-2 pl-5 pr-2 font-semibold">Status</th>
                  <th className="px-2 py-2 font-semibold">Exception</th>
                  <th className="px-2 py-2 font-semibold">Period</th>
                  <th className="px-2 py-2 text-right font-semibold">Expected</th>
                  <th className="px-2 py-2 text-right font-semibold">Actual</th>
                  <th className="px-2 py-2 text-right font-semibold">Variance</th>
                  <th className="px-2 py-2 pr-5 text-right font-semibold">Conf.</th>
                </tr>
              </thead>
              <tbody>
                {exceptions.data.map((e) => (
                  <tr
                    key={e.exception_id}
                    className="cursor-pointer border-b border-line/70 hover:bg-sunken/60"
                    onClick={() => router.push(`/exceptions/${encodeURIComponent(e.exception_id)}`)}
                  >
                    <td className="py-3 pl-5 pr-2">
                      <StatusBadge status={e.status} />
                    </td>
                    <td className="px-2 py-3">
                      <Link
                        href={`/exceptions/${encodeURIComponent(e.exception_id)}`}
                        className="font-medium text-ink hover:text-accent hover:underline"
                        onClick={(ev) => ev.stopPropagation()}
                      >
                        {humanize(e.charge_type)}
                      </Link>
                      <div className="text-xs text-ink-muted">
                        {e.lease_id} · {e.clinic_id} · <span className="font-mono">{e.exception_id}</span>
                      </div>
                    </td>
                    <td className="px-2 py-3 whitespace-nowrap">{period(e.period)}</td>
                    <td className="num px-2 py-3 text-right text-ink-soft">{money(e.expected)}</td>
                    <td className="num px-2 py-3 text-right">{money(e.actual)}</td>
                    <td className={cn("num px-2 py-3 text-right font-semibold", e.delta === 0 ? "text-ink" : "text-bad")}>{signedMoney(e.delta)}</td>
                    <td className="num px-2 py-3 pr-5 text-right text-ink-soft">{pct(e.confidence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card>
          <CardHeader eyebrow="Agents" title="Latest activity" />
          <CardBody>
            <AgentActivityFeed />
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function sumCents(values: number[]) {
  return values.reduce((s, v) => s + Math.round(v * 100), 0);
}
