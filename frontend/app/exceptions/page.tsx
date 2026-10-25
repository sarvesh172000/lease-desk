"use client";

import { QueueTable, toQueueRows, type QueueRow } from "@/components/today/QueueTable";
import { WorkStateBadge } from "@/components/WorkStateBadge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { money, period as fmtPeriod, signedMoney, STATUS_LABEL } from "@/lib/format";
import { useAllowedActions, useChargeChecks, useExceptionAction, useExceptions, useLeases } from "@/lib/hooks";
import { monthLong } from "@/lib/labels";
import type { ChargeCheck, ItemAction, Status } from "@/lib/types";
import { useListKeys } from "@/lib/useListKeys";
import { cn } from "@/lib/utils";
import * as Tabs from "@radix-ui/react-tabs";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

const STATUSES: Status[] = ["exception", "pending_review", "escalated"];
const RESOLVED_STATES = new Set(["APPROVED", "POSTED", "CLOSED", "REJECTED"]);

export default function ExceptionsPage() {
  const exceptions = useExceptions();
  const leases = useLeases();
  const checks = useChargeChecks();
  const router = useRouter();
  const [tab, setTab] = useState("open");
  const [status, setStatus] = useState<Status | "">("");
  const [clinic, setClinic] = useState("");
  const [region, setRegion] = useState("");
  const [period, setPeriod] = useState("");

  const all = useMemo(() => toQueueRows(exceptions.data ?? [], leases.data), [exceptions.data, leases.data]);
  const regionOf = useMemo(() => new Map((checks.data ?? []).map((c) => [c.exception_id, c.region_id ?? null])), [checks.data]);
  const open = useMemo(() => all.filter((r) => r.status !== "balanced"), [all]);

  const rows = useMemo(
    () =>
      open.filter(
        (r) =>
          (!status || r.status === status) &&
          (!clinic || r.clinic_id === clinic) &&
          (!region || regionOf.get(r.exception_id) === region) &&
          (!period || r.period.slice(0, 7) === period),
      ),
    [open, status, clinic, region, period, regionOf],
  );
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of open) c[r.status] = (c[r.status] ?? 0) + 1;
    return c;
  }, [open]);
  const clinics = useMemo(() => Array.from(new Set(open.map((r) => r.clinic_id))).sort(), [open]);
  const regions = useMemo(() => Array.from(new Set(Array.from(regionOf.values()).filter((x): x is string => !!x))).sort(), [regionOf]);
  const periods = useMemo(() => Array.from(new Set(open.map((r) => r.period.slice(0, 7)))).sort().reverse(), [open]);

  // keyboard: J/K move, Enter opens, A/H act when the server allows
  const [pending, setPending] = useState<{ row: QueueRow; action: ItemAction } | null>(null);
  const keys = useListKeys({
    count: tab === "open" ? rows.length : 0,
    onOpen: (i) => router.push(`/exceptions/${encodeURIComponent(rows[i].exception_id)}`),
    onApprove: (i) => setPending({ row: rows[i], action: "approve" }),
    onHold: (i) => setPending({ row: rows[i], action: "hold" }),
  });
  const current = keys.index >= 0 ? rows[keys.index] : null;
  const allowed = useAllowedActions(current?.exception_id ?? "");

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="eyebrow">Work</div>
          <h1 className="text-2xl font-semibold">Exceptions</h1>
        </div>
        <p className="text-sm text-ink-muted">
          <kbd className="rounded-xs border border-line px-1 font-mono text-2xs">J</kbd>/<kbd className="rounded-xs border border-line px-1 font-mono text-2xs">K</kbd> move ·{" "}
          <kbd className="rounded-xs border border-line px-1 font-mono text-2xs">Enter</kbd> open ·{" "}
          <kbd className="rounded-xs border border-line px-1 font-mono text-2xs">A</kbd> approve · <kbd className="rounded-xs border border-line px-1 font-mono text-2xs">H</kbd> hold
          {current ? (
            <span className="text-ink-soft">
              {" "}
              · on {current.lease_id}
              {allowed.data ? ` (${allowed.data.actions.length ? allowed.data.actions.join(", ") : "no actions"})` : ""}
            </span>
          ) : null}
        </p>
      </div>

      <Tabs.Root value={tab} onValueChange={setTab}>
        <Tabs.List aria-label="Open or resolved" className="flex gap-1 border-b border-line">
          {[
            ["open", `Open · ${open.length}`],
            ["resolved", "Resolved"],
          ].map(([v, l]) => (
            <Tabs.Trigger
              key={v}
              value={v}
              className="relative px-3 pb-2 pt-1 text-sm font-medium text-ink-muted transition-colors hover:text-ink data-[state=active]:text-ink data-[state=active]:shadow-[inset_0_-2px_0_rgb(var(--accent))]"
            >
              {l}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        <Tabs.Content value="open" className="mt-4 space-y-4 outline-none">
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filters">
            <Chip label="All" count={open.length} active={!status} onClick={() => setStatus("")} />
            {STATUSES.map((s) => (
              <Chip key={s} label={STATUS_LABEL[s]} count={counts[s] ?? 0} active={status === s} onClick={() => setStatus(status === s ? "" : s)} status={s} />
            ))}
            <span className="mx-1 h-5 w-px bg-line" aria-hidden />
            {periods.map((p) => (
              <Chip key={p} label={monthLong(p)} active={period === p} onClick={() => setPeriod(period === p ? "" : p)} />
            ))}
            <div className="ml-auto flex items-center gap-2">
              {regions.length ? (
                <select aria-label="Filter by region" className="h-9 rounded-sm border border-line-strong bg-surface px-2 text-sm" value={region} onChange={(e) => setRegion(e.target.value)}>
                  <option value="">All regions</option>
                  {regions.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              ) : null}
              <select aria-label="Filter by clinic" className="h-9 rounded-sm border border-line-strong bg-surface px-2 text-sm" value={clinic} onChange={(e) => setClinic(e.target.value)}>
                <option value="">All clinics</option>
                {clinics.map((c) => (
                  <option key={c} value={c}>
                    {all.find((r) => r.clinic_id === c)?.place ?? c}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <Card>
            {exceptions.isLoading ? (
              <CardBody>
                <LoadingBlock rows={5} label="Loading exceptions" />
              </CardBody>
            ) : exceptions.isError ? (
              <CardBody>
                <ErrorState title="Could not load exceptions" error={exceptions.error} onRetry={() => exceptions.refetch()} />
              </CardBody>
            ) : !rows.length ? (
              <CardBody>
                <EmptyState title={open.length ? "Nothing matches these filters." : "No open exceptions."}>
                  {open.length ? "Clear a filter to see the rest." : "Every charge matched its lease, or has been decided."}
                </EmptyState>
              </CardBody>
            ) : (
              <QueueTable rows={rows} highlight={keys.index} onHighlight={keys.setIndex} />
            )}
          </Card>
          <p className="text-xs text-ink-muted">Showing {rows.length} of {open.length} open. Columns that read the same on every row are hidden.</p>
        </Tabs.Content>

        <Tabs.Content value="resolved" className="mt-4 outline-none">
          <ResolvedList checks={checks.data} loading={checks.isLoading} error={checks.isError ? checks.error : null} retry={() => checks.refetch()} balanced={all.filter((r) => r.status === "balanced")} />
        </Tabs.Content>
      </Tabs.Root>

      {pending ? <ActDialog pending={pending} allowed={allowed.data?.actions ?? []} onClose={() => setPending(null)} /> : null}
    </div>
  );
}

function Chip({ label, count, active, onClick, status }: { label: string; count?: number; active: boolean; onClick: () => void; status?: Status }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex h-9 items-center gap-2 rounded-full border px-3 text-sm transition-colors duration-fast",
        active ? "border-accent bg-accent-soft text-accent" : "border-line bg-surface text-ink-soft hover:border-line-strong hover:text-ink",
      )}
      data-status={status}
    >
      {label}
      {count != null ? <span className={cn("num rounded-full px-1.5 text-xs font-semibold", active ? "bg-accent text-accent-ink" : "bg-sunken text-ink-muted")}>{count}</span> : null}
    </button>
  );
}

/** A from the keyboard: confirm with the money restated, and act only if the server allows. */
function ActDialog({ pending, allowed, onClose }: { pending: { row: QueueRow; action: ItemAction }; allowed: ItemAction[]; onClose: () => void }) {
  const { row, action } = pending;
  const m = useExceptionAction(row.exception_id);
  const ok = allowed.includes(action);
  const label = action === "approve" ? "Approve" : "Hold";
  return (
    <ConfirmDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={ok ? `${label} this charge?` : `${label} is not allowed`}
      confirmLabel={ok ? label : "Close"}
      tone="primary"
      loading={m.isPending}
      confirmDisabled={false}
      onConfirm={() => (ok ? m.mutate(action, { onSettled: onClose }) : onClose())}
    >
      {ok ? (
        <p>
          {row.lease_id} · billed <span className="num font-semibold text-ink">{money(row.actual)}</span> against{" "}
          <span className="num font-semibold text-ink">{money(row.expected)}</span> ({signedMoney(row.delta)}).{" "}
          {action === "approve" ? "Approving posts through the gateway and is recorded under your name." : "Holding parks it until someone decides; nothing posts."}
          <span className="mt-2 block">
            <Link href={`/exceptions/${encodeURIComponent(row.exception_id)}`} className="text-accent hover:underline">
              Open the money screen first →
            </Link>
          </span>
        </p>
      ) : (
        <p>The server does not allow {label.toLowerCase()} on this item for your role. {allowed.length ? `Allowed: ${allowed.join(", ")}.` : "No actions are allowed."}</p>
      )}
      {m.isError ? <p className="mt-2 text-bad">{m.error.message}</p> : null}
    </ConfirmDialog>
  );
}

/** What was decided: charge checks past review, from the queue's work states. */
function ResolvedList({ checks, loading, error, retry, balanced }: { checks?: ChargeCheck[]; loading: boolean; error: Error | null; retry: () => void; balanced: QueueRow[] }) {
  const done = (checks ?? []).filter((c) => RESOLVED_STATES.has(c.state));
  if (loading) return <LoadingBlock rows={4} label="Loading history" />;
  if (error) return <ErrorState title="Could not load the history" error={error} onRetry={retry} />;
  if (!done.length && !balanced.length) return <EmptyState title="Nothing decided yet.">Approved, upheld, paid and rejected items appear here.</EmptyState>;
  return (
    <Card>
      <CardHeader eyebrow="History" title="Resolved" actions={<span className="num text-sm text-ink-muted">{done.length + balanced.length}</span>} />
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="table-head">
            <th className="py-2 pl-5 pr-2 font-semibold">Outcome</th>
            <th className="px-2 py-2 font-semibold">Charge</th>
            <th className="px-2 py-2 font-semibold">Period</th>
            <th className="px-2 py-2 pr-5 text-right font-semibold">Billed</th>
          </tr>
        </thead>
        <tbody>
          {done.map((c) => (
            <tr key={c.exception_id} className="border-b border-line/70">
              <td className="py-2.5 pl-5 pr-2">
                <WorkStateBadge state={c.state} />
              </td>
              <td className="px-2 py-2.5">
                <Link href={`/exceptions/${encodeURIComponent(c.exception_id)}`} className="hover:text-accent hover:underline">
                  {c.title}
                </Link>
              </td>
              <td className="px-2 py-2.5 whitespace-nowrap">{fmtPeriod(c.period)}</td>
              <td className="num px-2 py-2.5 pr-5 text-right">{money(c.amount)}</td>
            </tr>
          ))}
          {balanced.map((r) => (
            <tr key={r.exception_id} className="border-b border-line/70">
              <td className="py-2.5 pl-5 pr-2">
                <WorkStateBadge state="APPROVED" />
              </td>
              <td className="px-2 py-2.5">
                <Link href={`/exceptions/${encodeURIComponent(r.exception_id)}`} className="hover:text-accent hover:underline">
                  {r.place ?? r.clinic_id} · {r.lease_id}
                </Link>
              </td>
              <td className="px-2 py-2.5 whitespace-nowrap">{fmtPeriod(r.period)}</td>
              <td className="num px-2 py-2.5 pr-5 text-right">{money(r.actual)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
