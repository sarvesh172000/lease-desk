"use client";

import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { day, money, period } from "@/lib/format";
import { useDisputes, useLeases } from "@/lib/hooks";
import { chargeLabel, disputeStatusLabel, placeLabel } from "@/lib/labels";
import type { DisputeStatus, DisputeSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { motion, useReducedMotion } from "framer-motion";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

const STAGES: DisputeStatus[] = ["drafted", "sent", "acknowledged", "credited", "partially_credited", "refused"];
const TONE: Record<DisputeStatus, string> = {
  drafted: "text-warn",
  sent: "text-accent",
  acknowledged: "text-accent",
  credited: "text-ok",
  partially_credited: "text-ok",
  refused: "text-bad",
};
const DOT: Record<DisputeStatus, string> = { drafted: "bg-warn", sent: "bg-accent", acknowledged: "bg-accent", credited: "bg-ok", partially_credited: "bg-ok", refused: "bg-bad" };

export default function DisputesPage() {
  const [status, setStatus] = useState<DisputeStatus | "">("");
  const q = useDisputes(status ? { status } : {});
  const all = useDisputes();
  const leases = useLeases();
  const reduce = useReducedMotion();
  const placeOf = useMemo(() => new Map((leases.data ?? []).map((l) => [l.lease_id, placeLabel(l.location) ?? l.location])), [leases.data]);
  const counts = all.data?.counts;
  const rows = q.data?.disputes ?? [];
  const outstanding = (all.data?.disputes ?? []).reduce((s, d) => s + d.amount - d.credited_amount, 0);

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="eyebrow">Portfolio · letters to landlords</div>
          <h1 className="text-2xl font-semibold">
            Disputes
            {all.data ? (
              <span className="num ml-2 text-base font-normal text-ink-muted">
                · {all.data.total} open · {money(outstanding)} outstanding
              </span>
            ) : null}
          </h1>
        </div>
      </div>

      {/* the pipeline: every stage with its count; click one to filter */}
      <ol className="grid grid-cols-6 gap-2" aria-label="Pipeline">
        {STAGES.map((s, i) => {
          const n = counts?.[s] ?? 0;
          const active = status === s;
          return (
            <li key={s} className="relative">
              <button
                type="button"
                aria-pressed={active}
                data-testid={`stage-${s}`}
                onClick={() => setStatus(active ? "" : s)}
                className={cn(
                  "flex h-full w-full flex-col gap-1 rounded-md border p-3 text-left transition-colors duration-base",
                  active ? "border-accent bg-accent/10" : n ? "border-line bg-surface hover:border-line-strong" : "border-line/60 bg-surface/60 hover:border-line",
                )}
              >
                <span className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-ink-muted">
                  <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", DOT[s])} />
                  {disputeStatusLabel(s)}
                </span>
                <span className={cn("num text-2xl font-semibold leading-none", n ? TONE[s] : "text-ink-faint")}>{n}</span>
              </button>
              {i < STAGES.length - 1 ? <ChevronRight aria-hidden className="absolute -right-2.5 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-ink-faint" /> : null}
            </li>
          );
        })}
      </ol>

      {q.isLoading ? (
        <Card className="p-5">
          <LoadingBlock rows={3} label="Loading disputes" />
        </Card>
      ) : q.isError ? (
        <Card className="p-5">
          <ErrorState title="Could not load disputes" error={q.error} onRetry={() => q.refetch()} />
        </Card>
      ) : !rows.length ? (
        <Card className="p-5">
          <EmptyState title={status ? `Nothing ${disputeStatusLabel(status).toLowerCase()}.` : "No disputes yet."}>
            {status ? "Pick another stage." : "A dispute is drafted when a hold is upheld and money is owed back; the regional manager approves the letter before it goes."}
          </EmptyState>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full border-collapse text-[0.95rem]" data-testid="disputes-table">
            <thead>
              <tr className="table-head">
                <th className="py-2 pl-5 pr-2 font-semibold">Stage</th>
                <th className="px-2 py-2 font-semibold">Dispute</th>
                <th className="px-2 py-2 font-semibold">Landlord</th>
                <th className="px-2 py-2 text-right font-semibold">Disputed</th>
                <th className="px-2 py-2 text-right font-semibold">Credited</th>
                <th className="px-2 py-2 pr-5 font-semibold">Updated</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d: DisputeSummary, i) => (
                <motion.tr
                  key={d.id}
                  initial={reduce ? false : { opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25, delay: reduce ? 0 : i * 0.03 }}
                  className="border-b border-line/70 hover:bg-sunken/60"
                  data-testid="dispute-row"
                >
                  <td className="py-3 pl-5 pr-2">
                    <span className={cn("inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide", TONE[d.status])}>
                      <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", DOT[d.status])} />
                      {disputeStatusLabel(d.status)}
                    </span>
                  </td>
                  <td className="px-2 py-3">
                    <Link href={`/disputes/${encodeURIComponent(d.id)}`} className="font-medium hover:text-accent hover:underline">
                      {chargeLabel(d.charge_type)} · {period(d.period)}
                    </Link>
                    <div className="truncate text-xs text-ink-muted">
                      {placeOf.get(d.lease_id) ?? d.clinic_id} <span className="font-mono">· {d.id} · {d.invoice_id}</span>
                    </div>
                  </td>
                  <td className="px-2 py-3 text-ink-soft">{d.landlord_name}</td>
                  <td className="num px-2 py-3 text-right font-semibold">{money(d.amount)}</td>
                  <td className={cn("num px-2 py-3 text-right", d.credited_amount ? "text-ok" : "text-ink-muted")}>{money(d.credited_amount)}</td>
                  <td className="num px-2 py-3 pr-5 text-xs text-ink-muted">{day(d.updated_at)}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
