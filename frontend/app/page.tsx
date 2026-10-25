"use client";

import { AgentActivityFeed } from "@/components/AgentActivityFeed";
import { MetricTile } from "@/components/MetricTile";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { WorkStateBadge } from "@/components/WorkStateBadge";
import { humanize, money, pct, period, signedMoney } from "@/lib/format";
import { useChargeChecks, useExceptions, useLeases, useSummary } from "@/lib/hooks";
import type { ExceptionSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { useRouter } from "next/navigation";

const isOpen = (e: ExceptionSummary) => e.status !== "balanced";

export default function DashboardPage() {
  const leases = useLeases();
  const exceptions = useExceptions();
  const summary = useSummary();
  const router = useRouter();

  const open = (exceptions.data ?? []).filter(isOpen);
  const leasesWithIssues = (leases.data ?? []).filter((l) => l.status !== "balanced").length;
  const s = summary.data;

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
          loading={summary.isLoading}
          value={summary.isError ? "—" : s?.active_leases}
          sub={leases.isError ? "Leases unavailable" : `${leasesWithIssues} need attention`}
        />
        <MetricTile
          label="Open exceptions"
          tone={s?.open_exceptions ? "warn" : "ok"}
          loading={summary.isLoading}
          value={summary.isError ? "—" : s?.open_exceptions}
          sub={summary.isError ? "Summary unavailable" : `${s?.pending_review ?? 0} pending your review`}
        />
        <MetricTile
          label="Dollars held"
          tone={s?.held_total ? "bad" : "ok"}
          loading={summary.isLoading}
          value={summary.isError ? "—" : money(s?.held_total)}
          sub={s ? `${s.held_count} over-bill${s.held_count === 1 ? "" : "s"} held back` : "Over-bills held back"}
        />
        <MetricTile
          label="Portfolio liability"
          loading={summary.isLoading}
          value={summary.isError ? "—" : money(s?.portfolio_liability, { whole: true })}
          sub={s ? `ASC 842, as of ${period(s.as_of)}` : "ASC 842"}
        />
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_280px] gap-6">
        <div className="min-w-0 space-y-6">
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
                      data-testid="exception-row"
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
                      <td className="num whitespace-nowrap px-2 py-3 text-right text-ink-soft">{money(e.expected)}</td>
                      <td className="num whitespace-nowrap px-2 py-3 text-right">{money(e.actual)}</td>
                      <td className={cn("num whitespace-nowrap px-2 py-3 text-right font-semibold", e.delta === 0 ? "text-ink" : "text-bad")}>{signedMoney(e.delta)}</td>
                      <td className="num px-2 py-3 pr-5 text-right text-ink-soft">{pct(e.confidence)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <ChargeChecks />
        </div>

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

/** Every charge the checker read this month: the holds above and the ones it found correct. */
function ChargeChecks() {
  const q = useChargeChecks();
  const router = useRouter();
  const rows = q.data ?? [];
  const posted = rows.filter((r) => r.state === "POSTED").length;
  return (
    <Card>
      <CardHeader
        eyebrow="Checked by the agent"
        title="All charges this month"
        actions={q.data ? <span className="text-sm text-ink-muted">{`${rows.length} checked · ${rows.filter((r) => r.proposal === "hold").length} held · ${posted} posted`}</span> : null}
      />
      {q.isLoading ? (
        <CardBody>
          <LoadingBlock rows={4} label="Loading charge checks" />
        </CardBody>
      ) : q.isError ? (
        <CardBody>
          <ErrorState title="Could not load the charge checks" error={q.error} onRetry={() => q.refetch()} />
        </CardBody>
      ) : !rows.length ? (
        <CardBody>
          <EmptyState title="No charges checked yet.">Run the month to check every landlord charge.</EmptyState>
        </CardBody>
      ) : (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="table-head">
              <th className="py-2 pl-5 pr-2 font-semibold">State</th>
              <th className="px-2 py-2 font-semibold">Proposal</th>
              <th className="px-2 py-2 font-semibold">Charge</th>
              <th className="px-2 py-2 pr-5 text-right font-semibold">Billed</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.exception_id}
                data-testid="charge-row"
                data-proposal={r.proposal ?? ""}
                data-state={r.state}
                className="cursor-pointer border-b border-line/70 hover:bg-sunken/60"
                onClick={() => router.push(`/exceptions/${encodeURIComponent(r.exception_id)}`)}
              >
                <td className="py-2.5 pl-5 pr-2">
                  <WorkStateBadge state={r.state} />
                </td>
                <td className="px-2 py-2.5">
                  <span className={cn("text-xs font-semibold uppercase tracking-wide", r.proposal === "hold" ? "text-bad" : "text-ok")}>{r.proposal ?? "—"}</span>
                </td>
                <td className="px-2 py-2.5">
                  <Link
                    href={`/exceptions/${encodeURIComponent(r.exception_id)}`}
                    className="text-ink hover:text-accent hover:underline"
                    onClick={(ev) => ev.stopPropagation()}
                  >
                    {r.title}
                  </Link>
                </td>
                <td className="num px-2 py-2.5 pr-5 text-right">{money(r.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
