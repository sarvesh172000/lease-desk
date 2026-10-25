"use client";

import { BatchPanel } from "@/components/month/BatchPanel";
import { WorkStateBadge } from "@/components/WorkStateBadge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { ApiError } from "@/lib/api";
import { day, money, signedMoney } from "@/lib/format";
import { useExceptions, useLeases, useMonthSummary, useMonthSummaryItems, useSummary } from "@/lib/hooks";
import { chargeLabel, monthLong, placeLabel } from "@/lib/labels";
import type { MonthMetricName, MonthSummary, MonthSummaryRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Check, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

/** The run as a pipeline: every stage is one of the API's own metrics, in the order the month happens. */
const STAGES: { metric: MonthMetricName; title: string; what: string }[] = [
  { metric: "clinics", title: "Ingest", what: "clinics billed" },
  { metric: "checked", title: "Check", what: "charges checked" },
  { metric: "approved", title: "Approve", what: "approved by a person" },
  { metric: "held", title: "Hold", what: "held for review" },
  { metric: "disputes", title: "Dispute", what: "letters drafted" },
  { metric: "questions", title: "Ask", what: "questions out" },
  { metric: "batch", title: "Batch", what: "ready for AP" },
];

/** The stage a person is holding up, if any: holds first, then questions, then an unreleased batch. */
function waitingOn(s: MonthSummary): MonthMetricName | null {
  if (Number(s.metrics.held.value) > 0) return "held";
  if (Number(s.metrics.questions.value) > 0) return "questions";
  if (s.batch.ready && !s.batch.released) return "batch";
  return null;
}

export default function MonthPage() {
  return (
    <Suspense fallback={<LoadingBlock rows={6} label="Loading the month" />}>
      <MonthRun />
    </Suspense>
  );
}

function MonthRun() {
  const params = useSearchParams();
  const router = useRouter();
  const summary = useSummary();
  const exceptions = useExceptions();
  const asOf = summary.data?.as_of?.slice(0, 7);
  const period = params.get("period") ?? asOf ?? "";
  const months = useMemo(() => {
    const set = new Set<string>();
    if (asOf) set.add(asOf);
    for (const e of exceptions.data ?? []) set.add(e.period.slice(0, 7));
    return Array.from(set).sort().reverse();
  }, [asOf, exceptions.data]);

  const month = useMonthSummary(period);
  const notLive = month.error instanceof ApiError && month.error.status === 501;
  const [metric, setMetric] = useState<MonthMetricName | null>(null);
  const items = useMonthSummaryItems(period, metric);
  const reduce = useReducedMotion();
  const s = month.data;
  const waiting = s ? waitingOn(s) : null;

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="eyebrow">Work · {s?.entity_name ?? "Northbay Physical Therapy"}</div>
          <h1 className="text-2xl font-semibold">Month run{period ? ` · ${monthLong(period)}` : ""}</h1>
        </div>
        {months.length > 1 ? (
          <div className="flex gap-1 rounded-sm border border-line p-0.5" role="group" aria-label="Period">
            {months.map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={m === period}
                onClick={() => router.push(`/month?period=${m}`)}
                className={cn("num rounded-[4px] px-2.5 py-1 text-sm transition-colors", m === period ? "bg-accent text-accent-ink" : "text-ink-soft hover:bg-sunken")}
              >
                {monthLong(m)}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {!period || month.isLoading ? (
        <LoadingBlock rows={4} label="Loading the month run" />
      ) : notLive ? (
        <EmptyState title="The month run needs the live API.">
          The offline demo keeps only the exception fixtures; the run&apos;s counts, drill-downs and batch come from <span className="font-mono">GET /api/summary/month</span>.
        </EmptyState>
      ) : month.isError ? (
        <ErrorState title="Could not load the month run" error={month.error} onRetry={() => month.refetch()} />
      ) : s ? (
        <>
          <p className="text-sm text-ink-soft">{s.headline}</p>

          {/* the pipeline */}
          <ol className="grid grid-cols-7 gap-2" aria-label="Pipeline">
            {STAGES.map((st, i) => {
              const m = s.metrics[st.metric];
              const value = typeof m.value === "boolean" ? (m.value ? "Yes" : "No") : m.value;
              const done = typeof m.value === "boolean" ? m.value : m.value > 0;
              const glow = waiting === st.metric;
              const active = metric === st.metric;
              return (
                <li key={st.metric} className="relative">
                  <button
                    type="button"
                    aria-pressed={active}
                    data-testid={`stage-${st.metric}`}
                    data-waiting={glow ? "true" : undefined}
                    onClick={() => setMetric(active ? null : st.metric)}
                    className={cn(
                      "flex h-full w-full flex-col gap-1 rounded-md border p-3 text-left transition-colors duration-base",
                      active ? "border-accent bg-accent/10" : glow ? "border-warn-line bg-warn-soft/60 shadow-[0_0_0_1px_rgb(var(--warn)/0.4),0_0_24px_-6px_rgb(var(--warn)/0.6)]" : "border-line bg-surface hover:border-line-strong",
                      glow && !reduce && "animate-pulse-dot [animation-duration:2.6s]",
                    )}
                  >
                    <span className="flex items-center justify-between text-2xs font-semibold uppercase tracking-wide text-ink-muted">
                      {i + 1} · {st.title}
                      {done && !glow ? <Check aria-hidden className="h-3.5 w-3.5 text-ok" /> : null}
                    </span>
                    <span className={cn("num text-2xl font-semibold leading-none", glow ? "text-warn" : "text-ink")}>{value}</span>
                    <span className="text-xs text-ink-muted">
                      {st.metric === "held" && m.amount ? `${money(m.amount)} ` : ""}
                      {st.what}
                    </span>
                    {glow ? <span className="mt-1 text-2xs font-semibold text-warn">Waiting on a person</span> : null}
                  </button>
                  {i < STAGES.length - 1 ? <ChevronRight aria-hidden className="absolute -right-2.5 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-ink-faint" /> : null}
                </li>
              );
            })}
          </ol>

          <div className="grid grid-cols-[minmax(0,1fr)_360px] gap-5">
            <Card>
              <CardHeader
                eyebrow="Drill-down"
                title={metric ? `${STAGES.find((st) => st.metric === metric)?.title}: ${s.metrics[metric].label}` : "Pick a stage"}
                actions={metric ? <span className="num text-sm text-ink-muted">{items.data ? `${items.data.length} rows` : ""}</span> : null}
              />
              <CardBody className="p-0">
                <AnimatePresence mode="wait" initial={false}>
                  <motion.div key={metric ?? "none"} initial={reduce ? false : { opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
                    {!metric ? (
                      <div className="p-5">
                        <EmptyState title="Every number has rows behind it.">Click a stage to see the charges, clinics, questions or payables it counts.</EmptyState>
                      </div>
                    ) : items.isLoading ? (
                      <div className="p-5">
                        <LoadingBlock rows={4} label="Loading rows" />
                      </div>
                    ) : items.isError ? (
                      <div className="p-5">
                        <ErrorState title="Could not load the rows" error={items.error} onRetry={() => items.refetch()} />
                      </div>
                    ) : !items.data?.length ? (
                      <div className="p-5">
                        <EmptyState title="Nothing here this month.">{`The ${s.metrics[metric].label} count is ${String(s.metrics[metric].value)}.`}</EmptyState>
                      </div>
                    ) : (
                      <DrillRows rows={items.data} />
                    )}
                  </motion.div>
                </AnimatePresence>
              </CardBody>
            </Card>
            <Card>
              <CardHeader eyebrow="AP" title="Payment batch" />
              <CardBody>
                <BatchPanel summary={s} />
              </CardBody>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
}

/** One table per row type; the API says which with `type`. Charge checks are named from the exception they are. */
function DrillRows({ rows }: { rows: MonthSummaryRow[] }) {
  const exceptions = useExceptions();
  const leases = useLeases();
  const byId = useMemo(() => new Map((exceptions.data ?? []).map((e) => [e.exception_id, e])), [exceptions.data]);
  const placeOf = useMemo(() => new Map((leases.data ?? []).map((l) => [l.lease_id, placeLabel(l.location)])), [leases.data]);
  const type = rows[0].type;
  if (type === "clinic") {
    return (
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="table-head">
            <th className="py-2 pl-5 pr-2 font-semibold">Clinic</th>
            <th className="px-2 py-2 pr-5 text-right font-semibold">Charges</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (r.type === "clinic" ? (
            <tr key={r.clinic_id} className="border-b border-line/70">
              <td className="py-2.5 pl-5 pr-2">
                {placeLabel(r.name) ?? r.name} <span className="font-mono text-xs text-ink-muted">· {r.clinic_id}</span>
              </td>
              <td className="num px-2 py-2.5 pr-5 text-right">{r.charges}</td>
            </tr>
          ) : null))}
        </tbody>
      </table>
    );
  }
  if (type === "question") {
    return (
      <ul className="divide-y divide-line px-5">
        {rows.map((r) => (r.type === "question" ? (
          <li key={r.question_id} className="py-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-sm font-medium">Asked {r.asked_to}</span>
              <span className="text-xs text-ink-muted">{r.due_at ? `due ${day(r.due_at)}` : day(r.asked_at)}</span>
            </div>
            <p className="text-sm text-ink-soft">{r.body}</p>
            {r.exception_id ? (
              <Link href={`/exceptions/${encodeURIComponent(r.exception_id)}`} className="font-mono text-xs text-ink-muted hover:text-accent">
                {r.exception_id}
              </Link>
            ) : null}
          </li>
        ) : null))}
      </ul>
    );
  }
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="table-head">
          <th className="py-2 pl-5 pr-2 font-semibold">State</th>
          <th className="px-2 py-2 font-semibold">Item</th>
          <th className="px-2 py-2 text-right font-semibold">Amount</th>
          <th className="px-2 py-2 pr-5 text-right font-semibold">Variance</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          if (r.type === "clinic" || r.type === "question") return null;
          const href = "exception_id" in r && r.exception_id ? `/exceptions/${encodeURIComponent(r.exception_id)}` : null;
          const ex = r.type === "charge_check" ? byId.get(r.exception_id) : undefined;
          const label =
            r.type === "payable"
              ? `${chargeLabel(r.charge_type)} · ${r.landlord_name}`
              : ex
                ? `${chargeLabel(ex.charge_type)} · ${monthLong(ex.period)} · ${placeOf.get(ex.lease_id) ?? ex.clinic_id}`
                : r.title;
          const amount = r.type === "payable" ? r.amount : r.amount;
          const variance = r.type === "charge_check" ? r.variance : null;
          return (
            <tr key={r.item_id} className="border-b border-line/70">
              <td className="py-2.5 pl-5 pr-2">
                <WorkStateBadge state={r.type === "payable" ? "APPROVED" : r.state} />
              </td>
              <td className="px-2 py-2.5">
                {href ? (
                  <Link href={href} className="hover:text-accent hover:underline">
                    {label}
                  </Link>
                ) : (
                  label
                )}
                <span className="font-mono text-xs text-ink-muted"> · {r.clinic_id}</span>
              </td>
              <td className="num px-2 py-2.5 text-right">{money(amount)}</td>
              <td className={cn("num px-2 py-2.5 pr-5 text-right", variance ? "font-semibold text-bad" : "text-ink-muted")}>{variance != null ? signedMoney(variance) : "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
