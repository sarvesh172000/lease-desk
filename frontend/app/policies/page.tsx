"use client";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { ApiError } from "@/lib/api";
import { day, money } from "@/lib/format";
import { useMe, useOnboardPolicies, usePolicies } from "@/lib/hooks";
import { chargeLabel, policyActionLabel, policyStatusLabel, policyTitle } from "@/lib/labels";
import { scopeLabel } from "@/components/policies/words";
import type { PolicyStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { History } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

const STATUSES: PolicyStatus[] = ["proposed", "approved", "rejected", "retired"];
const TONE: Record<PolicyStatus, string> = { proposed: "border-warn-line bg-warn-soft text-warn", approved: "border-ok-line bg-ok-soft text-ok", rejected: "border-bad-line bg-bad-soft text-bad", retired: "border-line bg-sunken text-ink-muted" };

export default function PoliciesPage() {
  const q = usePolicies();
  const me = useMe();
  const onboard = useOnboardPolicies();
  const [status, setStatus] = useState<PolicyStatus | "">("");
  const [confirm, setConfirm] = useState(false);
  const all = q.data?.policies ?? [];
  const rows = all.filter((p) => !status || p.status === status);
  const isController = me.data?.role === "controller";
  const notLive = onboard.error instanceof ApiError && (onboard.error.status === 409 || onboard.error.status === 501);

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="eyebrow">Portfolio · the house rules</div>
          <h1 className="text-2xl font-semibold">
            Policies {q.data ? <span className="num ml-2 text-base font-normal text-ink-muted">· {all.length}</span> : null}
          </h1>
        </div>
        {isController ? (
          <div className="flex flex-col items-end gap-1">
            <Button variant="secondary" icon={<History aria-hidden className="h-4 w-4" />} loading={onboard.isPending} onClick={() => setConfirm(true)} data-testid="onboard">
              Onboard from history
            </Button>
            {onboard.isSuccess ? (
              <span role="status" className="text-xs text-ok">
                Queued job #{onboard.data.job_id} over {onboard.data.year}; proposals appear as it runs.
              </span>
            ) : onboard.isError ? (
              <span role="alert" className="text-xs text-bad">
                {notLive ? "Onboarding needs the live API." : onboard.error.message}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter by status">
        <Chip label="All" count={all.length} active={!status} onClick={() => setStatus("")} />
        {STATUSES.map((s) => (
          <Chip key={s} label={policyStatusLabel(s)} count={q.data?.counts[s] ?? 0} active={status === s} onClick={() => setStatus(status === s ? "" : s)} tone={TONE[s]} />
        ))}
      </div>

      {q.isLoading ? (
        <Card className="p-5">
          <LoadingBlock rows={4} label="Loading policies" />
        </Card>
      ) : q.isError ? (
        <Card className="p-5">
          <ErrorState title="Could not load policies" error={q.error} onRetry={() => q.refetch()} />
        </Card>
      ) : !all.length ? (
        <Card className="p-5">
          <EmptyState title="No policies yet.">
            {isController ? "Onboard from history to propose rules from a year of decisions; each comes with its precedents and a backtest." : "The controller onboards rules from a year of decisions."}
          </EmptyState>
        </Card>
      ) : !rows.length ? (
        <Card className="p-5">
          <EmptyState title={`Nothing ${policyStatusLabel(status).toLowerCase()}.`}>Pick another status.</EmptyState>
        </Card>
      ) : (
        <ul className="grid grid-cols-2 gap-3" data-testid="policy-list">
          {rows.map((p) => (
            <li key={p.id}>
              <Link href={`/policies/${p.id}`} className="block h-full rounded-md border border-line bg-surface p-4 shadow-raised transition-colors hover:border-line-strong" data-testid="policy-card">
                <div className="flex items-start justify-between gap-3">
                  <h2 className="text-[0.98rem] font-semibold leading-snug">{policyTitle(p)}</h2>
                  <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-2xs font-semibold uppercase tracking-wide", TONE[p.status])}>{policyStatusLabel(p.status)}</span>
                </div>
                <div className="mt-1 font-mono text-2xs text-ink-muted">
                  {p.ref} · {p.name}
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <span className="rounded-xs border border-accent/40 bg-accent-soft px-1.5 py-0.5 text-2xs font-semibold text-accent">{policyActionLabel(p.action)}</span>
                  {p.charge_types.map((c) => (
                    <span key={c} className="rounded-xs border border-line px-1.5 py-0.5 text-2xs text-ink-soft">
                      {chargeLabel(c)}
                    </span>
                  ))}
                  <span className="rounded-xs border border-line px-1.5 py-0.5 text-2xs text-ink-soft">{scopeLabel(p.scope)}</span>
                </div>
                <dl className="num mt-3 grid grid-cols-3 gap-2 border-t border-line pt-3 text-sm">
                  <div>
                    <dt className="text-2xs uppercase tracking-wide text-ink-muted">Precedents</dt>
                    <dd className="font-semibold">{p.precedent_count ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-2xs uppercase tracking-wide text-ink-muted">Backtest</dt>
                    <dd className="font-semibold">{p.backtest ? `${p.backtest.matched} matched · ${p.backtest.changed} changed` : "not run"}</dd>
                  </div>
                  <div>
                    <dt className="text-2xs uppercase tracking-wide text-ink-muted">Would move</dt>
                    <dd className={cn("font-semibold", p.backtest?.dollars ? "text-warn" : "")}>{p.backtest ? money(p.backtest.dollars) : "—"}</dd>
                  </div>
                </dl>
                <div className="mt-2 text-2xs text-ink-muted">
                  v{p.version} · {day(p.created_at)}
                  {p.backtest?.conflicts ? <span className="text-warn"> · {p.backtest.conflicts} conflict{p.backtest.conflicts === 1 ? "" : "s"}</span> : null}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog open={confirm} onOpenChange={setConfirm} title="Onboard policies from history?" confirmLabel="Onboard" loading={onboard.isPending} onConfirm={() => onboard.mutate({ entityId: "ENT-CA" }, { onSettled: () => setConfirm(false) })}>
        <p>A job scans a year of decided charges for ENT-CA and proposes a rule wherever the same decision was made often enough, each with its precedents and a backtest. Nothing is approved by this; you decide each rule.</p>
      </ConfirmDialog>
    </div>
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
