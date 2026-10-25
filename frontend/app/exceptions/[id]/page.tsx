"use client";

import { CheckerFindingCard } from "@/components/CheckerFindingCard";
import { DocumentViewer } from "@/components/DocumentViewer";
import { EvidenceCard } from "@/components/EvidenceCard";
import { InvestigationTimeline } from "@/components/InvestigationTimeline";
import { JournalEntryTable } from "@/components/JournalEntryTable";
import { BoxConnector } from "@/components/money/BoxConnector";
import { ConfidenceRing } from "@/components/money/ConfidenceRing";
import { DecisionActions } from "@/components/money/DecisionActions";
import { DocumentStack, totalFromMessage } from "@/components/money/DocumentStack";
import { EmailEvidence } from "@/components/money/EmailEvidence";
import { EvidencePackButton } from "@/components/money/EvidencePackButton";
import { LiabilityBar } from "@/components/money/LiabilityBar";
import { SourcesPanel } from "@/components/money/SourcesPanel";
import { phaseOf, reached, useInvestigationRun, type InvestigationRun, type Phase } from "@/components/money/useInvestigationRun";
import { WhyDrawer } from "@/components/money/WhyDrawer";
import { ScheduleDiff } from "@/components/ScheduleDiff";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { WorkStateBadge } from "@/components/WorkStateBadge";
import { ApiError, itemIdFor } from "@/lib/api";
import { day, money, signedMoney } from "@/lib/format";
import { useException, useLeases, useSchedule } from "@/lib/hooks";
import { chargeLabel, clinicLabel, monthLong, rootCauseLabel } from "@/lib/labels";
import type { Box, Evidence, ExceptionDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import * as Tabs from "@radix-ui/react-tabs";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

const DOC_HEIGHT = 470;
const EASE = [0.2, 0.8, 0.2, 1] as const;

export default function ExceptionPage() {
  const { id } = useParams<{ id: string }>();
  const exceptionId = decodeURIComponent(id);
  const q = useException(exceptionId);

  if (q.isLoading) return <MoneyScreenSkeleton />;
  if (q.isError) {
    const nf = q.error instanceof ApiError && q.error.status === 404;
    return (
      <div className="space-y-4">
        <BackLink />
        {nf ? (
          <EmptyState title="This exception was not found.">It may have been resolved, or the link is stale.</EmptyState>
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
    <Link href="/" className="text-sm text-ink-muted transition-colors hover:text-accent">
      ← Today&apos;s queue
    </Link>
  );
}

/** The evidence on screen: what the API recorded, or, mid-run, what the stream just said. */
function evidenceOf(ex: ExceptionDetail, run: InvestigationRun): Evidence | null {
  const recorded = ex.investigation?.evidence[0];
  if (recorded) return recorded;
  const f = run.get("found");
  if (!f?.doc_id) return null;
  return {
    doc_id: f.doc_id,
    date: "",
    source: f.source ?? f.doc_id,
    trust_rank: f.trust_rank ?? 0,
    quote: f.quote,
    page: f.page as number,
    box: (f.box ?? null) as Box,
  };
}

function MoneyScreen({ ex }: { ex: ExceptionDetail }) {
  const reduce = useReducedMotion();
  const run = useInvestigationRun(ex.exception_id);
  const inv = ex.investigation;
  const phase = phaseOf(run, !!inv);
  const leases = useLeases();
  const lease = leases.data?.find((l) => l.lease_id === ex.lease_id);
  const itemId = ex.item_id ?? (/^\d+$/.test(itemIdFor(ex.exception_id)) ? Number(itemIdFor(ex.exception_id)) : null);

  // The found document lands in the viewer once its card has flown out of the stack.
  const [landed, setLanded] = useState(false);
  useEffect(() => {
    if (run.state === "running" && !run.get("found")) setLanded(false);
  }, [run, run.state]);
  const onLanded = useCallback(() => setLanded(true), []);

  const evidence = evidenceOf(ex, run);
  const showStack = phase === "searching" || (phase === "found" && !landed);
  const [tab, setTab] = useState<string>("investigation");
  useEffect(() => {
    if (run.state === "running") setTab("investigation");
  }, [run.state]);

  // right-hand document: the evidence once there is some, else the lease clause
  type Source = { key: string; tab: string; eyebrow: string; title: string; docId: string; page: number; box: Box | null; text: string; email?: Evidence };
  const sources: Source[] = [
    ...(evidence && reached(phase, "found") && (phase !== "found" || landed)
      ? [{
          key: "evidence",
          tab: "Evidence",
          eyebrow: `Evidence · trust rank ${evidence.trust_rank || "—"}`,
          title: evidence.date ? `${evidence.source} · ${day(evidence.date)}` : evidence.source,
          docId: evidence.doc_id,
          page: evidence.page,
          box: evidence.box,
          text: evidence.quote,
          // a message kept as text has no page to render
          email: evidence.page == null ? evidence : undefined,
        }]
      : []),
    ...(ex.lease_citation
      ? [{
          key: "lease",
          tab: "Lease clause",
          eyebrow: "Lease · what it supports",
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
  const docsRef = useRef<HTMLDivElement>(null);

  const title = `${chargeLabel(ex.charge_type)} · ${monthLong(ex.period)}`;
  const place = lease ? clinicLabel(lease.location, ex.clinic_id) : null;

  return (
    <div className="space-y-4">
      {/* header: what, where, the decision */}
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          <BackLink />
          <h1 className="mt-1 text-2xl font-semibold leading-tight">
            {title}
            {place ? <span className="font-normal text-ink-soft"> · {place}</span> : null}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge status={ex.status} />
            {ex.state ? <WorkStateBadge state={ex.state} /> : null}
            <Link
              href={`/leases/${encodeURIComponent(ex.lease_id)}`}
              className="rounded-xs border border-line px-1.5 py-0.5 font-mono text-2xs text-ink-muted transition-colors hover:border-line-strong hover:text-accent"
            >
              {ex.lease_id}
            </Link>
            {ex.clinic_id ? <span className="rounded-xs border border-line px-1.5 py-0.5 font-mono text-2xs text-ink-muted">{ex.clinic_id}</span> : null}
          </div>
        </div>
        <DecisionActions ex={ex} />
      </div>

      {/* the calculation */}
      <div className="grid grid-cols-[1fr_1fr_1fr_1.5fr] overflow-hidden rounded-md border border-line bg-surface shadow-raised">
        <Figure label="Lease supports" value={money(ex.expected)} />
        <Figure label="Billed" value={money(ex.actual)} />
        <Figure label="Variance" value={signedMoney(ex.delta)} tone={ex.delta === 0 ? undefined : "bad"} />
        <div className="flex items-center justify-between gap-3 border-l border-line px-5 py-3">
          <div className="min-w-0">
            <div className="eyebrow">Explanation</div>
            {inv && reached(phase, "found") ? (
              <>
                <div className="font-semibold">{rootCauseLabel(inv.root_cause)}</div>
                <div className={cn("text-sm", inv.explains_variance ? "text-ok" : "text-bad")}>
                  {inv.explains_variance ? "Explains the variance" : "Does not explain the variance"}
                </div>
              </>
            ) : ex.reason ? (
              <>
                <div className="font-semibold">
                  Checker proposes <span className={ex.proposal === "hold" ? "text-bad" : "text-ok"}>{ex.proposal ?? "—"}</span>
                </div>
                <div className="line-clamp-2 text-sm text-ink-soft" title={ex.reason}>
                  {ex.reason}
                </div>
              </>
            ) : (
              <div className="mt-0.5 text-sm text-ink-muted">No investigation on record yet.</div>
            )}
          </div>
          <ConfidenceRing value={inv && reached(phase, "found") ? inv.confidence : run.get("found")?.confidence ?? ex.confidence ?? null} />
        </div>
      </div>

      {/* the two documents and the story */}
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_340px] gap-4">
        <div ref={docsRef} className="relative col-span-2 grid grid-cols-2 gap-4">
          <DocumentViewer
            eyebrow="Billed · landlord invoice"
            title={ex.invoice_line ? `${ex.invoice_line.description} · ${money(ex.invoice_line.amount)}` : "Invoice"}
            docId={ex.invoice_line?.doc_id}
            page={ex.invoice_line?.page}
            box={ex.invoice_line?.box}
            tone="billed"
            label={ex.invoice_line ? `Billed ${money(ex.invoice_line.amount)}` : undefined}
            fallbackText={ex.invoice_line ? `${ex.invoice_line.description} — ${money(ex.invoice_line.amount)}` : undefined}
            height={DOC_HEIGHT}
          />
          {source || showStack ? (
            <DocumentViewer
              key={showStack ? "stack" : source?.key}
              eyebrow={showStack ? "Investigation · mailbox" : source!.eyebrow}
              title={showStack ? "Searching for what explains the variance" : source!.title}
              docId={showStack ? null : source!.docId}
              page={source?.page}
              box={source?.box}
              tone="cited"
              label={source?.key === "lease" ? "Lease says" : "Quoted"}
              fallbackText={source ? `“${source.text}”` : undefined}
              height={DOC_HEIGHT}
              overlay={
                !showStack && source?.email ? (
                  <EmailEvidence evidence={source.email} highlight={run.state !== "idle"} />
                ) : showStack ? (
                  <DocumentStack
                    mode={phase === "found" ? "found" : "searching"}
                    total={totalFromMessage(run.get("searching")?.message)}
                    foundLabel={run.get("found")?.source ?? run.get("found")?.doc_id}
                    onLanded={onLanded}
                  />
                ) : undefined
              }
              toolbar={
                !showStack && sources.length > 1 ? (
                  <div className="flex rounded-xs border border-line-strong p-0.5" role="tablist" aria-label="Cited document">
                    {sources.map((s) => (
                      <button
                        key={s.key}
                        role="tab"
                        type="button"
                        aria-selected={s.key === source!.key}
                        onClick={() => setSourceKey(s.key)}
                        className={cn(
                          "rounded-[4px] px-2 py-0.5 text-xs font-medium transition-colors",
                          s.key === source!.key ? "bg-accent text-accent-ink" : "text-ink-soft hover:bg-sunken",
                        )}
                      >
                        {s.tab}
                      </button>
                    ))}
                  </div>
                ) : null
              }
            />
          ) : (
            <DocumentViewer eyebrow="Cited source" title="Nothing cited yet" tone="cited" height={DOC_HEIGHT} />
          )}
          {!showStack ? <BoxConnector root={docsRef} /> : null}
        </div>

        {/* the story: investigation, evidence, sources */}
        <section className="flex min-w-0 flex-col overflow-hidden rounded-md border border-line bg-surface shadow-raised" style={{ height: DOC_HEIGHT + 49 }}>
          <Tabs.Root value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
            <div className="flex items-center justify-between gap-2 border-b border-line px-3 pt-2">
              <Tabs.List aria-label="Investigation, evidence and sources" className="flex gap-1">
                {[
                  ["investigation", "Investigation"],
                  ["evidence", "Evidence"],
                  ["sources", "Sources"],
                ].map(([v, l]) => (
                  <Tabs.Trigger
                    key={v}
                    value={v}
                    className="relative px-2 pb-2 pt-1 text-sm font-medium text-ink-muted transition-colors hover:text-ink data-[state=active]:text-ink"
                  >
                    {l}
                    {tab === v ? (
                      <motion.span layoutId="money-tab" className="absolute inset-x-1 -bottom-px h-0.5 rounded-full bg-accent" transition={{ duration: 0.2, ease: EASE }} />
                    ) : null}
                  </Tabs.Trigger>
                ))}
              </Tabs.List>
              <WhyDrawer itemId={itemId} />
            </div>
            <Tabs.Content value="investigation" className="min-h-0 flex-1 overflow-y-auto p-4 outline-none">
              <Story ex={ex} run={run} phase={phase} evidence={evidence} landed={landed || phase !== "found"} reduce={!!reduce} />
            </Tabs.Content>
            <Tabs.Content value="evidence" className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 outline-none">
              {inv?.evidence.length ? (
                inv.evidence.map((e, i) => (
                  <EvidenceCard key={i} evidence={e} confidence={inv.confidence} rootCause={inv.root_cause} selected={source?.key === "evidence"} onSelect={() => setSourceKey("evidence")} />
                ))
              ) : null}
              {ex.reason || ex.lease_citation ? (
                <CheckerFindingCard ex={ex} selected={source?.key === "lease"} onSelect={() => setSourceKey("lease")} />
              ) : !inv?.evidence.length ? (
                <EmptyState title="No evidence attached.">Run the investigation to search the mailbox.</EmptyState>
              ) : null}
            </Tabs.Content>
            <Tabs.Content value="sources" className="min-h-0 flex-1 overflow-y-auto p-4 outline-none">
              {itemId != null ? <SourcesPanel itemId={itemId} /> : <EmptyState title="No resolver record.">This exception has no work item to resolve.</EmptyState>}
            </Tabs.Content>
            <div className="border-t border-line px-3 py-2">
              <EvidencePackButton itemId={itemId} exceptionId={ex.exception_id} />
            </div>
          </Tabs.Root>
        </section>
      </div>

      {/* below the fold: the remeasurement in full, and what approving does */}
      <div className="grid grid-cols-2 gap-4 pt-2">
        <RemeasurementDetail ex={ex} show={reached(phase, "remeasured")} />
        <Card>
          <CardHeader eyebrow="On approval" title="What posts, and what stays held" />
          <CardBody className="text-sm leading-relaxed text-ink-soft">
            {inv && reached(phase, "complete") ? (
              <>
                {inv.entries.length} proposed entries, {inv.balanced ? "balanced" : "not balanced"}. Nothing posts until a person approves; the decision is
                recorded in the audit trail.
              </>
            ) : ex.resolution === "pay_as_billed" ? (
              <>Paid as billed by {ex.resolved_by ?? "the controller"} over the hold: {ex.override_reason ?? "reason on record"}.</>
            ) : ex.resolution === "upheld" ? (
              <>
                Hold upheld by {ex.resolved_by ?? "a reviewer"}. {(ex.payable ?? 0) > 0 ? `Only the undisputed ${money(ex.payable)} posts` : "Nothing is paid"}; the
                disputed {money(ex.disputed)} never reaches the ledger.
              </>
            ) : ex.proposal === "hold" ? (
              <>
                A charge check proposes no adjusting entries. Upholding the hold posts only the undisputed amount through the gateway (Dr expense, Cr accounts
                payable); the disputed amount stays out of the ledger.
              </>
            ) : (
              <>A charge check proposes no adjusting entries. Approving it posts the billed charge through the gateway (Dr lease cost, Cr accounts payable).</>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

/** The investigation as it unfolds: the steps, then each result where it lands. */
function Story({
  ex,
  run,
  phase,
  evidence,
  landed,
  reduce,
}: {
  ex: ExceptionDetail;
  run: InvestigationRun;
  phase: Phase;
  evidence: Evidence | null;
  landed: boolean;
  reduce: boolean;
}) {
  const inv = ex.investigation;
  const live = run.state !== "idle";
  const endRef = useRef<HTMLDivElement>(null);
  // follow the newest beat inside the panel while a run plays
  useEffect(() => {
    if (live) endRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "end" });
  }, [live, phase, landed, inv, reduce]);

  const delta = run.get("remeasured")?.liability_delta ?? inv?.liability_delta ?? null;
  const enter = (k: string, children: ReactNode) => (
    <motion.div
      key={k}
      initial={live ? (reduce ? { opacity: 0 } : { opacity: 0, y: 12 }) : false}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: EASE }}
    >
      {children}
    </motion.div>
  );

  return (
    <div className="space-y-4">
      <InvestigationTimeline run={run} recorded={inv} />
      <AnimatePresence>
        {evidence && reached(phase, "found") && landed
          ? enter(
              "evidence",
              <EvidenceCard evidence={evidence} confidence={inv?.confidence ?? run.get("found")?.confidence ?? undefined} rootCause={inv?.root_cause} highlight={live} />,
            )
          : null}
        {reached(phase, "remeasured") && (inv?.liability_before != null || delta != null)
          ? enter(
              "remeasured",
              <div className="rounded-md border border-line p-3">
                <div className="eyebrow mb-2">Remeasured under ASC 842</div>
                {inv?.liability_before != null && inv.liability_after != null ? (
                  <LiabilityBar before={inv.liability_before} after={inv.liability_after} delta={delta} animate={live} />
                ) : (
                  <div className="space-y-2" role="status" aria-label="Fetching the remeasured balances">
                    <Skeleton className="h-3 w-full" />
                    <Skeleton className="h-3 w-4/5" />
                    <div className="num text-sm text-ink-soft">Liability {signedMoney(delta)}</div>
                  </div>
                )}
              </div>,
            )
          : null}
        {inv && reached(phase, "complete") && inv.entries.length
          ? enter(
              "entries",
              <div className="rounded-md border border-line p-3">
                <div className="eyebrow mb-2">Proposed entries · not posted</div>
                <JournalEntryTable entries={inv.entries} balanced={inv.balanced} reveal={live} dense />
              </div>,
            )
          : null}
      </AnimatePresence>
      <div ref={endRef} />
    </div>
  );
}

function RemeasurementDetail({ ex, show }: { ex: ExceptionDetail; show: boolean }) {
  const inv = ex.investigation;
  const has = !!inv && inv.liability_before != null && show;
  const before = useSchedule(ex.lease_id, 1, has);
  const after = useSchedule(ex.lease_id, 2, has);
  return (
    <Card>
      <CardHeader eyebrow="Remeasurement" title="Schedule before and after" />
      <CardBody>
        {has ? (
          <>
            <ScheduleDiff diff={inv!} before={before.data} after={after.data} fromPeriod={ex.period} />
            {before.isError || after.isError ? <p className="mt-3 text-xs text-ink-muted">Schedule rows unavailable; balances shown from the investigation.</p> : null}
          </>
        ) : (
          <EmptyState title="No remeasurement.">Balances change only when an investigation finds revised terms.</EmptyState>
        )}
      </CardBody>
    </Card>
  );
}

function Figure({ label, value, tone }: { label: string; value: string; tone?: "bad" }) {
  return (
    <div className="border-l border-line px-5 py-3 first:border-l-0">
      <div className="eyebrow">{label}</div>
      <div className={cn("num mt-1 text-[1.6rem] font-semibold leading-tight", tone === "bad" && "text-bad")}>{value}</div>
    </div>
  );
}

function MoneyScreenSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading exception">
      <Skeleton className="h-4 w-28" />
      <Skeleton className="h-8 w-[28rem]" />
      <Skeleton className="h-20 w-full" />
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_340px] gap-4">
        <Skeleton className="h-[519px]" />
        <Skeleton className="h-[519px]" />
        <Skeleton className="h-[519px]" />
      </div>
    </div>
  );
}
