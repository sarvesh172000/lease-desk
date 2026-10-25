"use client";

import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { day } from "@/lib/format";
import { useLeases, useObligations } from "@/lib/hooks";
import { obligationLabel, placeLabel } from "@/lib/labels";
import { countByUrgency, groupByMonth, URGENCY_LABEL, URGENCY_ORDER, urgencyOf, type Urgency } from "@/lib/obligations";
import type { Obligation } from "@/lib/types";
import { cn } from "@/lib/utils";
import { motion, useReducedMotion } from "framer-motion";
import Link from "next/link";
import { useMemo, useState } from "react";

const WINDOWS = [
  [90, "90 days"],
  [180, "6 months"],
  [365, "A year"],
  [2000, "Everything"],
] as const;

const URGENCY_TONE: Record<Urgency, string> = {
  overdue: "border-bad-line bg-bad-soft text-bad",
  soon: "border-warn-line bg-warn-soft text-warn",
  quarter: "border-accent/40 bg-accent-soft text-accent",
  later: "border-line bg-sunken text-ink-soft",
};
const URGENCY_DOT: Record<Urgency, string> = { overdue: "bg-bad", soon: "bg-warn", quarter: "bg-accent", later: "bg-ink-faint" };

const monthFmt = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" });

export default function ObligationsPage() {
  const [within, setWithin] = useState<number>(365);
  const [kind, setKind] = useState("");
  const [urgency, setUrgency] = useState<Urgency | "">("");
  const q = useObligations({ within_days: within });
  const leases = useLeases();
  const reduce = useReducedMotion();
  const placeOf = useMemo(() => new Map((leases.data ?? []).map((l) => [l.lease_id, placeLabel(l.location) ?? l.location])), [leases.data]);

  const all = useMemo(() => q.data?.obligations ?? [], [q.data]);
  const kinds = useMemo(() => Array.from(new Set(all.map((o) => o.kind))).sort(), [all]);
  const counts = useMemo(() => countByUrgency(all), [all]);
  const rows = useMemo(() => all.filter((o) => (!kind || o.kind === kind) && (!urgency || urgencyOf(o.days_left) === urgency)), [all, kind, urgency]);
  const groups = useMemo(() => groupByMonth(rows), [rows]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow">Portfolio · deadlines the leases set</div>
          <h1 className="text-2xl font-semibold">
            Obligations
            {q.data ? (
              <span className="ml-2 text-base font-normal text-ink-muted">
                · {q.data.total} within {WINDOWS.find(([d]) => d === within)?.[1].toLowerCase()} of {day(q.data.today)}
              </span>
            ) : null}
          </h1>
        </div>
        <div className="flex rounded-sm border border-line bg-surface p-0.5" role="group" aria-label="Window">
          {WINDOWS.map(([d, l]) => (
            <button key={d} type="button" aria-pressed={within === d} onClick={() => setWithin(d)} className={cn("h-8 rounded-[4px] px-3 text-sm transition-colors", within === d ? "bg-accent text-accent-ink" : "text-ink-soft hover:bg-sunken")}>
              {l}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filters">
        <Chip label="All" count={all.length} active={!urgency} onClick={() => setUrgency("")} />
        {URGENCY_ORDER.map((u) => (
          <Chip key={u} label={URGENCY_LABEL[u]} count={counts[u]} active={urgency === u} onClick={() => setUrgency(urgency === u ? "" : u)} tone={URGENCY_TONE[u]} />
        ))}
        <span className="mx-1 h-5 w-px bg-line" aria-hidden />
        <select aria-label="Filter by kind" className="h-9 rounded-sm border border-line-strong bg-surface px-2 text-sm" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">All kinds</option>
          {kinds.map((k) => (
            <option key={k} value={k}>
              {obligationLabel(k)}
            </option>
          ))}
        </select>
      </div>

      {q.isLoading ? (
        <Card className="p-5">
          <LoadingBlock rows={5} label="Loading obligations" />
        </Card>
      ) : q.isError ? (
        <Card className="p-5">
          <ErrorState title="Could not load obligations" error={q.error} onRetry={() => q.refetch()} />
        </Card>
      ) : !all.length ? (
        <Card className="p-5">
          <EmptyState title="No deadlines in this window.">Renewal notices, CAM audit windows, deposit returns and expirations appear here as the leases set them. Try a wider window.</EmptyState>
        </Card>
      ) : !rows.length ? (
        <Card className="p-5">
          <EmptyState title="Nothing matches these filters.">Clear a filter to see the rest.</EmptyState>
        </Card>
      ) : (
        <Card className="overflow-hidden" data-testid="obligations-river">
          <ol className="relative">
            {groups.map((g, gi) => (
              <li key={g.month} className="grid border-b border-line/70 last:border-b-0" style={{ gridTemplateColumns: "150px minmax(0,1fr)" }}>
                <div className="relative border-r border-line px-5 py-4">
                  <div className="sticky top-16">
                    <div className="text-sm font-semibold">{monthFmt.format(new Date(`${g.month}-01T00:00:00Z`))}</div>
                    <div className="text-xs text-ink-muted">
                      {g.obligations.length} deadline{g.obligations.length === 1 ? "" : "s"}
                    </div>
                  </div>
                </div>
                <ol className="divide-y divide-line/60">
                  {g.obligations.map((o, i) => (
                    <ObligationRow key={o.id} o={o} place={placeOf.get(o.lease_id) ?? o.lease_id} index={gi * 4 + i} reduce={!!reduce} />
                  ))}
                </ol>
              </li>
            ))}
          </ol>
        </Card>
      )}
      <p className="text-xs text-ink-muted">Days left are counted from the business clock, not today&apos;s date. A citation opens the lease with that clause boxed on the page.</p>
    </div>
  );
}

function ObligationRow({ o, place, index, reduce }: { o: Obligation; place: string; index: number; reduce: boolean }) {
  const u = urgencyOf(o.days_left);
  const cite = o.citation;
  const href = `/leases/${encodeURIComponent(o.lease_id)}${cite.field ? `?term=${encodeURIComponent(cite.field)}` : ""}`;
  return (
    <motion.li
      initial={reduce ? false : { opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.25, delay: reduce ? 0 : Math.min(index, 12) * 0.03 }}
      className="grid items-center gap-4 px-5 py-3"
      style={{ gridTemplateColumns: "minmax(0,1.2fr) minmax(0,1.6fr) 130px 110px" }}
      data-testid="obligation-row"
      data-urgency={u}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-medium">
          <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-full", URGENCY_DOT[u])} />
          <span className="truncate">{obligationLabel(o.kind)}</span>
        </div>
        <Link href={`/leases/${encodeURIComponent(o.lease_id)}`} className="block truncate text-xs text-ink-muted hover:text-accent">
          {place} <span className="font-mono">· {o.lease_id}</span>
        </Link>
      </div>
      <div className="min-w-0 text-sm text-ink-soft">
        <div className="truncate" title={o.action}>
          {o.action}
        </div>
        {cite.section || cite.page ? (
          <Link href={href} className="text-xs text-ink-muted hover:text-accent">
            {cite.section ?? "Lease"}
            {cite.page ? ` · p.${cite.page}` : ""}
            {cite.quote ? ` · “${cite.quote.length > 70 ? `${cite.quote.slice(0, 69)}…` : cite.quote}”` : ""} →
          </Link>
        ) : o.source === "generator" ? (
          <span className="text-xs text-ink-muted">From the generated terms, no clause cited</span>
        ) : null}
      </div>
      <div className="num text-sm">{day(o.due_date)}</div>
      <div className={cn("num justify-self-end rounded-full border px-2 py-0.5 text-xs font-semibold", URGENCY_TONE[u])}>
        {o.days_left < 0 ? `${-o.days_left} days over` : o.days_left === 0 ? "Today" : `${o.days_left} days`}
      </div>
    </motion.li>
  );
}

function Chip({ label, count, active, onClick, tone }: { label: string; count: number; active: boolean; onClick: () => void; tone?: string }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex h-9 items-center gap-2 rounded-full border px-3 text-sm transition-colors duration-fast",
        active ? (tone ?? "border-accent bg-accent-soft text-accent") : "border-line bg-surface text-ink-soft hover:border-line-strong hover:text-ink",
        !active && count === 0 && "opacity-60",
      )}
    >
      {label}
      <span className={cn("num rounded-full px-1.5 text-xs font-semibold", active ? "bg-surface/60" : "bg-sunken text-ink-muted")}>{count}</span>
    </button>
  );
}
