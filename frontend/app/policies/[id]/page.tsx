"use client";

import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { ApiError, exceptionIdFor } from "@/lib/api";
import { day, money, period, timestamp } from "@/lib/format";
import { useBacktestPolicy, useDecidePolicy, useMe, usePolicy } from "@/lib/hooks";
import { actionLabel, chargeLabel, policyActionLabel, policyStatusLabel, policyTitle } from "@/lib/labels";
import { ruleInWords } from "@/components/policies/words";
import type { Backtest, PolicyDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { motion, useReducedMotion } from "framer-motion";
import { Check, FlaskConical, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

export default function PolicyPage() {
  const { id } = useParams<{ id: string }>();
  const policyId = Number(id);
  const q = usePolicy(Number.isFinite(policyId) ? policyId : null);
  if (q.isLoading) return <LoadingBlock rows={8} label="Loading the policy" />;
  if (q.isError) {
    const nf = q.error instanceof ApiError && q.error.status === 404;
    return (
      <div className="space-y-4">
        <Back />
        {nf ? <EmptyState title="This policy was not found." /> : <ErrorState title="Could not load the policy" error={q.error} onRetry={() => q.refetch()} />}
      </div>
    );
  }
  return <Policy d={q.data!} />;
}

function Back() {
  return (
    <Link href="/policies" className="text-sm text-ink-muted hover:text-accent">
      ← Policies
    </Link>
  );
}

function Policy({ d }: { d: PolicyDetail }) {
  const p = d.policy;
  const me = useMe();
  const backtest = useBacktestPolicy(p.id);
  const decide = useDecidePolicy();
  const reduce = useReducedMotion();
  const [confirming, setConfirming] = useState<"approve" | "reject" | null>(null);
  const [reason, setReason] = useState("");
  const isController = me.data?.role === "controller";
  const canDecide = isController && p.status === "proposed" && p.work_item_id != null;
  const bt: Backtest | null = backtest.data?.backtest ?? d.backtest;
  const notLive = backtest.error instanceof ApiError && backtest.error.status === 501;
  const evidence = d.evidence as { precedents?: unknown[]; counter_examples?: unknown[]; learned_from?: unknown; not_covered?: unknown[]; paid_anyway?: unknown[] };
  const count = (v: unknown) => (Array.isArray(v) ? v.length : typeof v === "number" ? v : null);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          <Back />
          <h1 className="mt-1 text-2xl font-semibold leading-tight" data-testid="policy-title">
            {policyTitle(p)}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className={cn("rounded-full border px-2.5 py-0.5 text-xs font-semibold", p.status === "approved" ? "border-ok-line bg-ok-soft text-ok" : p.status === "rejected" ? "border-bad-line bg-bad-soft text-bad" : p.status === "proposed" ? "border-warn-line bg-warn-soft text-warn" : "border-line bg-sunken text-ink-muted")}>
              {policyStatusLabel(p.status)}
            </span>
            <span className="font-mono text-2xs text-ink-muted">
              {p.ref} · {p.name} · {p.origin ?? "manual"}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <div className="flex flex-wrap items-center justify-end gap-2" data-testid="policy-actions">
            <Button variant="secondary" icon={<FlaskConical aria-hidden className="h-4 w-4" />} loading={backtest.isPending} onClick={() => backtest.mutate()} data-testid="run-backtest">
              Run backtest
            </Button>
            {canDecide ? (
              <>
                <Button variant="danger" icon={<X aria-hidden className="h-4 w-4" />} loading={decide.isPending && decide.variables?.action === "reject"} onClick={() => setConfirming("reject")} data-testid="reject-policy">
                  Reject
                </Button>
                <Button variant="primary" icon={<Check aria-hidden className="h-4 w-4" />} loading={decide.isPending && decide.variables?.action === "approve"} onClick={() => setConfirming("approve")} data-testid="approve-policy">
                  Approve
                </Button>
              </>
            ) : p.status === "proposed" ? (
              <span className="rounded-sm border border-line bg-sunken px-3 py-2 text-sm text-ink-muted">The controller decides this rule</span>
            ) : null}
          </div>
          {backtest.isError ? (
            <span role="alert" className="text-xs text-bad">
              {notLive ? "Backtests need the live API." : backtest.error.message}
            </span>
          ) : decide.isError ? (
            <span role="alert" className="text-xs text-bad">
              {decide.error.message}
            </span>
          ) : decide.isSuccess ? (
            <span role="status" className="text-xs text-ok">
              {decide.variables?.action === "approve" ? "Approved" : "Rejected"} · now {decide.data.state}
            </span>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] gap-4">
        <div className="space-y-4">
          <Card>
            <CardHeader eyebrow="The rule" title="In plain words" />
            <CardBody>
              <p className="text-[1.02rem] leading-relaxed text-ink" data-testid="rule-words">
                {ruleInWords(d.rule).join(" ")}
              </p>
              {p.description ? <p className="mt-3 text-sm text-ink-soft">{p.description}</p> : null}
              <dl className="mt-4 grid grid-cols-3 gap-3 border-t border-line pt-3 text-sm">
                <div>
                  <dt className="text-2xs uppercase tracking-wide text-ink-muted">Action</dt>
                  <dd className="font-semibold">{policyActionLabel(p.action)}</dd>
                </div>
                <div>
                  <dt className="text-2xs uppercase tracking-wide text-ink-muted">Charges</dt>
                  <dd>{p.charge_types.map(chargeLabel).join(", ") || "any"}</dd>
                </div>
                <div>
                  <dt className="text-2xs uppercase tracking-wide text-ink-muted">Effective</dt>
                  <dd className="num">{p.effective_from ? `${day(p.effective_from)} → ${p.effective_to ? day(p.effective_to) : "open"}` : "always"}</dd>
                </div>
              </dl>
            </CardBody>
          </Card>

          <Card>
            <CardHeader eyebrow="Evidence" title="Where it came from" actions={<span className="num text-sm text-ink-muted">{p.precedent_count ?? 0} precedents</span>} />
            <CardBody>
              <dl className="num grid grid-cols-4 gap-3 text-sm">
                {(
                  [
                    ["Precedents", count(evidence.precedents) ?? p.precedent_count, "text-ok"],
                    ["Counter-examples", count(evidence.counter_examples), "text-bad"],
                    ["Paid anyway", count(evidence.paid_anyway), "text-warn"],
                    ["Not covered", count(evidence.not_covered), "text-ink-soft"],
                  ] as const
                ).map(([l, v, tone]) => (
                  <div key={l}>
                    <dt className="text-2xs uppercase tracking-wide text-ink-muted">{l}</dt>
                    <dd className={cn("text-xl font-semibold", v ? tone : "text-ink-faint")}>{v ?? "—"}</dd>
                  </div>
                ))}
              </dl>
              {evidence.learned_from ? <p className="mt-3 text-xs text-ink-muted">Learned from: {typeof evidence.learned_from === "string" ? evidence.learned_from : JSON.stringify(evidence.learned_from)}</p> : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader eyebrow="Versions" title="History of this rule" />
            <CardBody>
              <ol className="flex flex-wrap items-center gap-2">
                {d.versions.map((v, i) => (
                  <li key={v.id} className="flex items-center gap-2">
                    {i > 0 ? <span aria-hidden className="h-px w-5 bg-line-strong" /> : null}
                    <span className={cn("rounded-sm border px-3 py-1.5 text-sm", v.version === p.version ? "border-accent bg-accent/10" : "border-line")}>
                      <span className="font-semibold">v{v.version}</span> <span className="text-ink-muted">· {policyStatusLabel(v.status)} · {day(v.created_at)}</span>
                    </span>
                  </li>
                ))}
              </ol>
              {d.rejection ? (
                <p className="mt-3 rounded-sm border-l-[3px] border-bad bg-bad-soft/60 px-3 py-2 text-sm">
                  Rejected by {d.rejection.by} on {timestamp(d.rejection.at)}
                  {d.rejection.reason ? `: ${d.rejection.reason}` : ""}
                </p>
              ) : null}
            </CardBody>
          </Card>
        </div>

        <div className="space-y-4">
          <Card data-testid="backtest">
            <CardHeader eyebrow="Backtest" title={bt ? `${bt.periods.count} periods · ${bt.periods.first ? period(bt.periods.first) : ""} → ${bt.periods.last ? period(bt.periods.last) : ""}` : "Not run yet"} actions={bt ? <span className="font-mono text-2xs text-ink-muted">{bt.digest}</span> : null} />
            <CardBody>
              {!bt ? (
                <EmptyState title="No backtest on record.">Run one to see what this rule would have changed across the decided charges.</EmptyState>
              ) : (
                <>
                  {/* what would have changed: a bar of the scanned charges */}
                  <div className="flex h-4 w-full overflow-hidden rounded-full bg-sunken" role="img" aria-label={`${bt.charges_scanned} charges scanned: ${bt.unchanged} unchanged, ${bt.changed} changed, ${bt.unknown} unknown`}>
                    {(
                      [
                        ["unchanged", bt.unchanged, "bg-ok"],
                        ["changed", bt.changed, "bg-warn"],
                        ["new", bt.new_decisions, "bg-accent"],
                        ["unknown", bt.unknown, "bg-ink-faint"],
                      ] as const
                    ).map(([k, n, c]) =>
                      n ? (
                        <motion.span
                          key={k}
                          className={c}
                          initial={reduce ? false : { width: 0 }}
                          animate={{ width: `${(n / Math.max(1, bt.charges_scanned)) * 100}%` }}
                          transition={{ duration: 0.6, ease: [0.2, 0.8, 0.2, 1] }}
                          title={`${n} ${k}`}
                        />
                      ) : null,
                    )}
                  </div>
                  <dl className="num mt-3 grid grid-cols-4 gap-2 text-sm">
                    <div>
                      <dt className="text-2xs uppercase tracking-wide text-ink-muted">Matched</dt>
                      <dd className="font-semibold">{bt.matched}</dd>
                    </div>
                    <div>
                      <dt className="text-2xs uppercase tracking-wide text-ink-muted">Unchanged</dt>
                      <dd className="font-semibold text-ok">{bt.unchanged}</dd>
                    </div>
                    <div>
                      <dt className="text-2xs uppercase tracking-wide text-ink-muted">Changed</dt>
                      <dd className={cn("font-semibold", bt.changed ? "text-warn" : "")}>{bt.changed}</dd>
                    </div>
                    <div>
                      <dt className="text-2xs uppercase tracking-wide text-ink-muted">Unknown</dt>
                      <dd className="font-semibold text-ink-soft">{bt.unknown}</dd>
                    </div>
                  </dl>
                  <dl className="num mt-3 grid grid-cols-3 gap-2 rounded-sm border border-line px-3 py-2 text-sm">
                    <div>
                      <dt className="text-2xs uppercase tracking-wide text-ink-muted">Would move</dt>
                      <dd className="font-semibold">{money(bt.dollars)}</dd>
                    </div>
                    <div>
                      <dt className="text-2xs uppercase tracking-wide text-ink-muted">Released</dt>
                      <dd className="font-semibold text-ok">{money(bt.released)}</dd>
                    </div>
                    <div>
                      <dt className="text-2xs uppercase tracking-wide text-ink-muted">Withheld</dt>
                      <dd className="font-semibold text-warn">{money(bt.withheld)}</dd>
                    </div>
                  </dl>
                  {bt.changes.length ? (
                    <div className="mt-3">
                      <div className="eyebrow mb-1">What would have changed</div>
                      <ul className="max-h-48 divide-y divide-line overflow-y-auto text-sm">
                        {bt.changes.map((c) => (
                          <li key={c.charge_id} className="flex items-center justify-between gap-3 py-1.5">
                            <span className="min-w-0 truncate">
                              {chargeLabel(c.charge_type)} · {period(c.period)} <span className="text-ink-muted">· {c.clinic_id ?? c.lease_id}</span>
                              <span className="block text-xs text-ink-muted">
                                {c.current}{c.decided_by ? ` by ${c.decided_by}` : ""} → {policyActionLabel(c.policy).toLowerCase()}
                              </span>
                            </span>
                            <span className={cn("num shrink-0 font-semibold", c.direction === "released" ? "text-ok" : c.direction === "withheld" ? "text-warn" : "text-ink-muted")}>{money(c.dollars)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <p className="mt-3 text-sm text-ink-muted">Every matched charge would have been decided the same way. Nothing moves.</p>
                  )}
                  {bt.conflicts.length ? (
                    <div className="mt-3 rounded-sm border border-warn-line bg-warn-soft/60 px-3 py-2 text-sm">
                      <div className="font-semibold text-warn">
                        {bt.conflicts.length} conflict{bt.conflicts.length === 1 ? "" : "s"} with other rules
                      </div>
                      <ul className="mt-1 space-y-0.5 text-xs text-ink-soft">
                        {bt.conflicts.map((c) => (
                          <li key={`${c.policy_id}-${c.version}`}>
                            {policyTitle({ name: c.name })} (v{c.version}, {policyActionLabel(c.action).toLowerCase()}) on {c.charges} charge{c.charges === 1 ? "" : "s"}: {c.winner === "this" ? "this rule wins" : "the existing rule wins"}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {bt.effective_dates_ignored ? <p className="mt-2 text-2xs text-ink-muted">Effective dates ignored: the backtest asks what the rule would do across the whole history.</p> : null}
                </>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader eyebrow="Cited by" title="Decisions that relied on it" actions={<span className="num text-sm text-ink-muted">{d.cited_by.length}</span>} />
            <CardBody>
              {d.cited_by.length ? (
                <ul className="divide-y divide-line text-sm">
                  {d.cited_by.map((c) => (
                    <li key={c.seq} className="flex items-center justify-between gap-3 py-2">
                      <span className="min-w-0 truncate">
                        {actionLabel(c.action)} <span className="text-ink-muted">· {c.actor_id}</span>
                        {c.subject_type === "work_item" ? (
                          <Link href={`/exceptions/${exceptionIdFor(c.subject_id)}`} className="ml-1.5 font-mono text-xs text-accent hover:underline">
                            item {c.subject_id}
                          </Link>
                        ) : null}
                        {c.reason ? <span className="block truncate text-xs text-ink-muted">{c.reason}</span> : null}
                      </span>
                      <span className="num shrink-0 text-xs text-ink-muted">
                        #{c.seq} · {day(c.at)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title="Not cited yet.">Decisions that cite this rule appear here with their audit sequence.</EmptyState>
              )}
            </CardBody>
          </Card>
        </div>
      </div>

      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(o) => {
          if (!o) {
            setConfirming(null);
            setReason("");
          }
        }}
        title={confirming === "approve" ? "Approve this rule?" : "Reject this rule?"}
        confirmLabel={confirming === "approve" ? "Approve" : "Reject"}
        tone={confirming === "approve" ? "primary" : "danger"}
        loading={decide.isPending}
        confirmDisabled={confirming === "reject" && !reason.trim()}
        onConfirm={() => {
          if (!confirming || p.work_item_id == null) return;
          decide.mutate({ workItemId: p.work_item_id, action: confirming, reason: reason.trim() || undefined }, { onSettled: () => setConfirming(null) });
        }}
      >
        <p>{confirming === "approve" ? `From now on, ${ruleInWords(d.rule).join(" ").replace(/^When/, "when")}` : "The rule is rejected and never applied."}</p>
        <label htmlFor="policy-reason" className="mt-3 block text-sm font-medium text-ink">
          Reason {confirming === "reject" ? <span className="text-ink-muted">(required)</span> : <span className="text-ink-muted">(optional)</span>}
        </label>
        <textarea id="policy-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} className="mt-1 w-full rounded-xs border border-line-strong bg-surface px-2 py-1.5 text-sm text-ink" />
        <p className="mt-2 text-ink-muted">Recorded in the audit trail under your name.</p>
      </ConfirmDialog>
    </div>
  );
}
