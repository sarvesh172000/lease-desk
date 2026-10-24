"use client";

import { DocumentViewer } from "@/components/DocumentViewer";
import { ConfidenceMeter, EvidenceCard } from "@/components/EvidenceCard";
import { InvestigationTimeline } from "@/components/InvestigationTimeline";
import { JournalEntryTable } from "@/components/JournalEntryTable";
import { ScheduleDiff } from "@/components/ScheduleDiff";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock, Skeleton } from "@/components/ui/States";
import { ApiError, approveException, getAllowedActions, getException, getSchedule, holdException } from "@/lib/api";
import { day, humanize, money, period, signedMoney, STATUS_LABEL } from "@/lib/format";
import type { Box, ExceptionDetail, InvestigationEvent, ItemAction } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

export default function ExceptionPage() {
  const { id } = useParams<{ id: string }>();
  const exceptionId = decodeURIComponent(id);
  const q = useQuery({ queryKey: ["exception", exceptionId], queryFn: () => getException(exceptionId) });

  if (q.isLoading) return <MoneyScreenSkeleton />;
  if (q.isError) {
    const nf = q.error instanceof ApiError && q.error.status === 404;
    return (
      <div className="space-y-4">
        <BackLink />
        {nf ? (
          <EmptyState title={`Exception ${exceptionId} was not found.`}>It may have been resolved or the link is stale.</EmptyState>
        ) : (
          <ErrorState title="Could not load this exception" error={q.error} onRetry={() => q.refetch()} />
        )}
      </div>
    );
  }
  return <MoneyScreen ex={q.data!} />;
}

function BackLink() {
  return (
    <Link href="/" className="text-sm text-ink-muted hover:text-accent">
      ← Exceptions
    </Link>
  );
}

function MoneyScreen({ ex }: { ex: ExceptionDetail }) {
  const inv = ex.investigation;
  const [remeasured, setRemeasured] = useState<Extract<InvestigationEvent, { stage: "remeasured" }> | null>(null);
  const hasEntries = !!inv?.entries.length;

  const before = useQuery({ queryKey: ["schedule", ex.lease_id, 1], queryFn: () => getSchedule(ex.lease_id, 1), enabled: hasEntries, retry: false });
  const after = useQuery({ queryKey: ["schedule", ex.lease_id, 2], queryFn: () => getSchedule(ex.lease_id, 2), enabled: hasEntries, retry: false });

  // right-hand pane: each evidence document, then the lease clause
  type Source = { key: string; tab: string; eyebrow: string; title: string; docId: string; page: number; box: Box; text: string };
  const sources: Source[] = [
    ...(inv?.evidence ?? []).map((e, i) => ({
      key: `ev${i}`,
      tab: `Evidence ${inv!.evidence.length > 1 ? i + 1 : ""}`.trim(),
      eyebrow: `Cited source · trust rank ${e.trust_rank}`,
      title: `${e.source} · ${day(e.date)}`,
      docId: e.doc_id,
      page: e.page,
      box: e.box,
      text: e.quote,
    })),
    ...(ex.lease_citation
      ? [{
          key: "lease",
          tab: "Lease clause",
          eyebrow: "Lease · what the schedule expects",
          title: ex.lease_citation.label,
          docId: ex.lease_citation.doc_id,
          page: ex.lease_citation.page,
          box: ex.lease_citation.box,
          text: ex.lease_citation.quote,
        }]
      : []),
  ];
  const [sourceKey, setSourceKey] = useState<string | null>(null);
  const source = sources.find((s) => s.key === sourceKey) ?? sources[0];

  return (
    <div className="space-y-5">
      {/* title row */}
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          <BackLink />
          <div className="mt-1 flex items-center gap-3">
            <h1 className="truncate text-2xl font-semibold">
              {ex.charge_type ? humanize(ex.charge_type) : "Variance"} · {period(ex.period)}
            </h1>
            <StatusBadge status={ex.status} size="lg" />
          </div>
          <p className="mt-0.5 text-ink-muted">
            <Link href={`/leases/${encodeURIComponent(ex.lease_id)}`} className="hover:text-accent hover:underline">
              {ex.lease_id}
            </Link>
            {ex.clinic_id ? ` · ${ex.clinic_id}` : ""} · <span className="font-mono text-sm">{ex.exception_id}</span>
          </p>
        </div>
        <Actions ex={ex} />
      </div>

      {/* the calculation */}
      <div className="grid grid-cols-[1fr_1fr_1fr_1.4fr] overflow-hidden rounded-md border border-line bg-surface shadow-card">
        <Figure label="Expected · schedule" value={money(ex.expected)} />
        <Figure label="Actual · received" value={money(ex.actual)} />
        <Figure label="Variance" value={signedMoney(ex.delta)} tone={ex.delta === 0 ? undefined : "bad"} />
        <div className="border-l border-line px-5 py-3.5">
          <div className="eyebrow">Explanation</div>
          {inv ? (
            <div className="mt-1.5 flex items-center justify-between gap-3">
              <div>
                <div className="font-semibold">{humanize(inv.root_cause)}</div>
                <div className={cn("text-sm", inv.explains_variance ? "text-ok" : "text-bad")}>
                  {inv.explains_variance ? "Explains the variance" : "Does not explain the variance"}
                </div>
              </div>
              <ConfidenceMeter value={inv.confidence} />
            </div>
          ) : (
            <div className="mt-1.5 text-ink-muted">No investigation on record yet.</div>
          )}
        </div>
      </div>

      {/* the two documents */}
      <div className="grid grid-cols-2 gap-4">
        <DocumentViewer
          eyebrow="Billed · landlord invoice"
          title={ex.invoice_line ? `${ex.invoice_line.description} · ${money(ex.invoice_line.amount)}` : "Invoice"}
          docId={ex.invoice_line?.doc_id}
          page={ex.invoice_line?.page}
          box={ex.invoice_line?.box}
          tone="billed"
          label={ex.invoice_line ? `Billed ${money(ex.invoice_line.amount)}` : undefined}
          fallbackText={ex.invoice_line ? `${ex.invoice_line.description} — ${money(ex.invoice_line.amount)}` : undefined}
          height={500}
        />
        {source ? (
          <DocumentViewer
            key={source.key}
            eyebrow={source.eyebrow}
            title={source.title}
            docId={source.docId}
            page={source.page}
            box={source.box}
            tone="cited"
            label={source.key === "lease" ? "Lease says" : "Quoted"}
            fallbackText={`“${source.text}”`}
            height={500}
            toolbar={
              sources.length > 1 ? (
                <div className="flex rounded border border-line-strong p-0.5" role="tablist" aria-label="Cited document">
                  {sources.map((s) => (
                    <button
                      key={s.key}
                      role="tab"
                      type="button"
                      aria-selected={s.key === source.key}
                      onClick={() => setSourceKey(s.key)}
                      className={cn("rounded-sm px-2 py-0.5 text-xs font-medium", s.key === source.key ? "bg-accent text-white" : "text-ink-soft hover:bg-sunken")}
                    >
                      {s.tab}
                    </button>
                  ))}
                </div>
              ) : null
            }
          />
        ) : (
          <DocumentViewer eyebrow="Cited source" title="Nothing cited yet" tone="cited" height={500} />
        )}
      </div>

      {/* evidence + entries */}
      <div className="grid grid-cols-[400px_minmax(0,1fr)] gap-5">
        <div className="space-y-5">
          {inv?.evidence.length ? (
            inv.evidence.map((e, i) => (
              <EvidenceCard
                key={i}
                evidence={e}
                confidence={inv.confidence}
                rootCause={inv.root_cause}
                selected={source?.key === `ev${i}`}
                onSelect={() => setSourceKey(`ev${i}`)}
              />
            ))
          ) : (
            <EmptyState title="No evidence attached.">
              {inv ? "The investigation found nothing that explains this variance." : "Run the investigation to search the document corpus."}
            </EmptyState>
          )}
          <Card>
            <CardHeader eyebrow="Live" title="Investigation timeline" />
            <CardBody>
              <InvestigationTimeline exceptionId={ex.exception_id} onEvent={(e) => e.stage === "remeasured" && setRemeasured(e)} />
            </CardBody>
          </Card>
        </div>

        <div className="space-y-5">
          <Card>
            <CardHeader
              eyebrow="Proposed · not posted"
              title="Journal entries"
              actions={inv ? <span className="text-sm text-ink-muted">{inv.entries.length} lines</span> : null}
            />
            <CardBody>
              <JournalEntryTable entries={inv?.entries ?? []} balanced={inv?.balanced} />
            </CardBody>
          </Card>
          <Card>
            <CardHeader eyebrow="Remeasurement" title="Before and after" />
            <CardBody>
              {inv && inv.liability_before != null ? (
                <>
                  <ScheduleDiff
                    diff={{
                      ...inv,
                      liability_delta: inv.liability_delta ?? remeasured?.liability_delta,
                      rou_delta: inv.rou_delta ?? remeasured?.rou_delta,
                    }}
                    before={before.data}
                    after={after.data}
                    fromPeriod={ex.period}
                  />
                  {before.isError || after.isError ? (
                    <p className="mt-3 text-xs text-ink-muted">Schedule rows unavailable; balances shown from the investigation.</p>
                  ) : null}
                </>
              ) : (
                <EmptyState title="No remeasurement.">Balances change only when an investigation proposes revised terms.</EmptyState>
              )}
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Figure({ label, value, tone }: { label: string; value: string; tone?: "bad" | "esc" }) {
  return (
    <div className="border-l border-line px-5 py-3.5 first:border-l-0">
      <div className="eyebrow">{label}</div>
      <div className={cn("num mt-1 text-[1.65rem] font-semibold leading-tight", tone === "bad" && "text-bad", tone === "esc" && "text-esc")}>{value}</div>
    </div>
  );
}

const ACTION_LABEL: Record<string, string> = { approve: "Approve", hold: "Hold" };

function Actions({ ex }: { ex: ExceptionDetail }) {
  const qc = useQueryClient();
  const allowed = useQuery({ queryKey: ["allowed-actions", ex.exception_id], queryFn: () => getAllowedActions(ex.exception_id) });
  const [done, setDone] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: (action: ItemAction) => (action === "approve" ? approveException(ex.exception_id) : holdException(ex.exception_id)),
    onSuccess: (res, action) => {
      setDone(`${action === "approve" ? "Approved" : "Held"} · now ${STATUS_LABEL[res.status] ?? res.status}`);
    },
    onSettled: () => {
      for (const k of ["exception", "exceptions", "leases", "audit", "allowed-actions"]) void qc.invalidateQueries({ queryKey: [k] });
    },
  });
  const blockApprove = !!ex.investigation && (!ex.investigation.balanced || !ex.investigation.explains_variance);

  return (
    <div className="flex shrink-0 flex-col items-end gap-1.5 pt-5">
      <div className="flex items-center gap-2">
        {allowed.isLoading ? (
          <Skeleton className="h-11 w-56" />
        ) : allowed.isError ? (
          <span className="text-sm text-bad">Actions unavailable: {(allowed.error as Error).message}</span>
        ) : allowed.data?.actions.length ? (
          allowed.data.actions.map((a) => (
            <Button
              key={a}
              size="lg"
              variant={a === "approve" ? "primary" : "secondary"}
              disabled={m.isPending || (a === "approve" && blockApprove)}
              onClick={() => m.mutate(a)}
              title={a === "approve" && blockApprove ? "Entries must balance and explain the variance before approval" : undefined}
            >
              {m.isPending && m.variables === a ? "Working…" : ACTION_LABEL[a] ?? humanize(a)}
            </Button>
          ))
        ) : (
          <span className="rounded-md border border-line bg-sunken px-3 py-2 text-sm text-ink-muted">
            {ex.status === "balanced" ? "Approved — nothing to do" : "No actions available to your role"}
          </span>
        )}
      </div>
      {m.isError ? (
        <span role="alert" className="text-sm text-bad">
          {(m.error as Error).message}
        </span>
      ) : done ? (
        <span role="status" className="text-sm font-medium text-ok">
          {done}
        </span>
      ) : (
        <span className="text-xs text-ink-muted">Approval is recorded in the audit trail.</span>
      )}
    </div>
  );
}

function MoneyScreenSkeleton() {
  return (
    <div className="space-y-5" role="status" aria-label="Loading exception">
      <Skeleton className="h-8 w-96" />
      <Skeleton className="h-20 w-full" />
      <div className="grid grid-cols-2 gap-4">
        <Skeleton className="h-[500px]" />
        <Skeleton className="h-[500px]" />
      </div>
      <LoadingBlock rows={4} />
    </div>
  );
}
