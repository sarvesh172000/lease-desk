"use client";

import { DocumentViewer } from "@/components/DocumentViewer";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { day, humanize, money, pct, timestamp } from "@/lib/format";
import { useConfirmLeaseVersion, useLeaseVersions, useMe } from "@/lib/hooks";
import { extractorLabel, termLabel } from "@/lib/labels";
import type { LeaseTerm, LeaseVersion } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Check, Circle, Sparkles, Wrench } from "lucide-react";
import { useEffect, useState } from "react";

const MONEY_FIELDS = new Set(["base_rent_monthly", "security_deposit", "cam_estimate_psf_annual", "cam_cap", "late_fee"]);

/** A term's value as a person reads it. Formatting only: the value is the server's. */
export function formatTermValue(term: LeaseTerm): string {
  const v = term.value;
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") {
    if (MONEY_FIELDS.has(term.field)) return money(v);
    if (term.field === "escalation_amount") return v < 1 ? `${(v * 100).toFixed(2)}%` : money(v);
    if (term.field === "proportionate_share_pct") return `${v.toFixed(2)}%`;
    if (term.field === "rentable_sf") return `${v.toLocaleString("en-US")} sf`;
    if (term.field === "renewal_notice_days") return `${v.toLocaleString("en-US")} days`;
    if (term.field === "renewal_years") return `${v} year${v === 1 ? "" : "s"}`;
    return v.toLocaleString("en-US");
  }
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)) return day(v);
  if (typeof v === "string") return v.includes("_") ? humanize(v) : v;
  return JSON.stringify(v);
}

/** Which path read a version: the first term that says. */
export function versionExtractor(v: LeaseVersion): string | null {
  return v.terms.find((t) => t.extracted_by?.agent)?.extracted_by?.agent ?? null;
}

export function ExtractorBadge({ agent, size = "md" }: { agent: string | null; size?: "sm" | "md" }) {
  const e = extractorLabel(agent);
  const Icon = e.kind === "llm" ? Sparkles : Wrench;
  return (
    <span
      title={e.long}
      data-testid="extractor-badge"
      data-kind={e.kind}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border font-semibold",
        size === "sm" ? "px-1.5 py-0.5 text-2xs" : "px-2 py-0.5 text-xs",
        e.kind === "llm" ? "border-accent/40 bg-accent-soft text-accent" : e.kind === "generator" ? "border-line bg-sunken text-ink-soft" : "border-line text-ink-muted",
      )}
    >
      <Icon aria-hidden className={size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5"} />
      {e.short}
      {agent ? <span className="font-mono font-normal opacity-70">({agent})</span> : null}
    </span>
  );
}

/**
 * Claude's reading of the lease: every extracted term as a row with its
 * value and confidence, badged with the path that read it; a click opens the
 * page with the box drawn and the quote highlighted. Versions run along the
 * top, v1 → v2, with who confirmed each; a person who may confirm sees the
 * button. Terms on record are never hidden behind "not abstracted yet".
 */
export function TermsPanel({ leaseId }: { leaseId: string }) {
  const versions = useLeaseVersions(leaseId);
  const confirm = useConfirmLeaseVersion(leaseId);
  const me = useMe();
  const list = [...(versions.data ?? [])].sort((a, b) => a.version - b.version);
  const [versionNo, setVersionNo] = useState<number | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  // the newest version opens; a term keeps its selection across versions
  useEffect(() => {
    if (list.length && (versionNo == null || !list.some((v) => v.version === versionNo))) setVersionNo(list[list.length - 1].version);
  }, [list, versionNo]);

  if (versions.isLoading) return <LoadingBlock rows={4} label="Loading the lease terms" />;
  if (versions.isError) return <ErrorState title="Could not load the lease terms" error={versions.error} onRetry={() => versions.refetch()} />;
  if (!list.length) {
    return (
      <Card>
        <CardHeader eyebrow="The lease, as read" title="No version on record yet" />
        <CardBody>
          <EmptyState title="The lease has not been read yet.">The monthly run reads the PDF and drafts version 1 with every term quoted, paged and boxed.</EmptyState>
        </CardBody>
      </Card>
    );
  }
  const v = list.find((x) => x.version === versionNo) ?? list[list.length - 1];
  const agent = versionExtractor(v);
  const term = v.terms.find((t) => t.field === selected) ?? null;
  const canConfirm = !v.confirmed && !!v.work_item && v.work_item.allowed_actions.includes("approve");
  const located = v.terms.filter((t) => t.page && t.bbox && t.document_id).length;

  return (
    <Card data-testid="terms-panel">
      <CardHeader
        eyebrow="The lease, as read"
        title={
          <span className="flex items-center gap-2">
            Version {v.version}
            <ExtractorBadge agent={agent} />
          </span>
        }
        actions={
          <span className="text-sm text-ink-muted">
            {v.terms.length} terms · {located} located on the page
          </span>
        }
      />

      {/* the versions, v1 → v2 */}
      <ol className="flex items-center gap-2 overflow-x-auto border-b border-line px-5 py-3" aria-label="Versions">
        {list.map((x, i) => (
          <li key={x.version} className="flex items-center gap-2">
            {i > 0 ? <span aria-hidden className="h-px w-6 bg-line-strong" /> : null}
            <button
              type="button"
              aria-pressed={x.version === v.version}
              data-testid={`version-${x.version}`}
              onClick={() => setVersionNo(x.version)}
              className={cn(
                "flex items-center gap-2 rounded-sm border px-3 py-1.5 text-left transition-colors",
                x.version === v.version ? "border-accent bg-accent/10" : "border-line hover:border-line-strong",
              )}
            >
              {x.confirmed ? <Check aria-hidden className="h-4 w-4 text-ok" /> : <Circle aria-hidden className="h-4 w-4 text-warn" />}
              <span className="flex flex-col leading-tight">
                <span className="text-sm font-semibold">
                  v{x.version} <span className="font-normal text-ink-muted">from {day(x.effective_from)}</span>
                </span>
                <span className="text-2xs text-ink-muted">
                  {x.confirmed ? `confirmed by ${x.confirmed_by} · ${timestamp(x.confirmed_at)}` : "awaiting confirmation · the checker does not use it yet"}
                </span>
              </span>
              <ExtractorBadge agent={versionExtractor(x)} size="sm" />
            </button>
          </li>
        ))}
        {canConfirm ? (
          <li className="ml-auto flex items-center gap-3">
            {confirm.isError ? (
              <span role="alert" className="text-xs text-bad">
                {confirm.error.message}
              </span>
            ) : null}
            <Button variant="primary" size="sm" loading={confirm.isPending} data-testid="confirm-version" onClick={() => confirm.mutate(v.work_item!.id)}>
              Confirm version {v.version}
            </Button>
          </li>
        ) : !v.confirmed ? (
          <li className="ml-auto text-xs text-ink-muted">
            {me.data?.role === "regional_manager" ? "Not yours to confirm" : "A regional manager confirms this version"}
          </li>
        ) : null}
      </ol>

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-4 p-4">
        <table className="w-full border-collapse self-start text-sm" data-testid="terms-table">
          <thead>
            <tr className="table-head">
              <th className="py-2 pl-3 font-semibold">Term</th>
              <th className="px-3 py-2 font-semibold">Value</th>
              <th className="px-3 py-2 text-right font-semibold">Match</th>
              <th className="px-3 py-2 pr-3 text-right font-semibold">Page</th>
            </tr>
          </thead>
          <tbody>
            {v.terms.map((t) => {
              const locatable = !!(t.page && t.bbox && t.document_id);
              const on = selected === t.field;
              return (
                <tr
                  key={t.field}
                  data-testid="term-row"
                  data-field={t.field}
                  aria-selected={on}
                  onClick={() => locatable && setSelected(t.field)}
                  className={cn("border-b border-line/60 transition-colors", locatable && "cursor-pointer hover:bg-sunken/60", on && "bg-accent/10 shadow-[inset_3px_0_0_rgb(var(--accent))]")}
                >
                  <td className="py-2 pl-3 font-medium">{termLabel(t.field)}</td>
                  <td className="num px-3 py-2">{formatTermValue(t)}</td>
                  <td className="px-3 py-2 text-right">
                    <span className={cn("num font-semibold", (t.confidence ?? 0) >= 0.92 ? "text-ok" : (t.confidence ?? 0) >= 0.7 ? "text-warn" : "text-bad")} title="How exactly the quote was found on the page">
                      {t.confidence == null ? "—" : pct(t.confidence)}
                    </span>
                  </td>
                  <td className="px-3 py-2 pr-3 text-right">
                    {locatable ? (
                      <button type="button" className="font-mono text-xs text-accent hover:underline" onClick={() => setSelected(t.field)}>
                        p.{t.page}
                      </button>
                    ) : (
                      <span className="text-xs text-bad" title="The quote was not found on any page">
                        not located
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {term && term.document_id && term.page ? (
          <DocumentViewer
            key={`${v.version}-${term.field}`}
            eyebrow={`${termLabel(term.field)} · v${v.version}`}
            title={term.quote ?? termLabel(term.field)}
            docId={term.document_id}
            page={term.page}
            box={term.bbox}
            tone="cited"
            label={termLabel(term.field)}
            fallbackText={term.quote}
            height={440}
          />
        ) : (
          <div className="flex h-[489px] items-center justify-center rounded-md border border-dashed border-line-strong p-6 text-center text-sm text-ink-muted">
            Click a term to see where the lease says it: the page opens with the clause boxed and the quote highlighted.
          </div>
        )}
      </div>
      {term?.quote ? (
        <div className="border-t border-line px-5 py-3">
          <div className="eyebrow">Quoted · {termLabel(term.field)} · p.{term.page}</div>
          <blockquote className="mt-1 border-l-[3px] border-warn bg-warn-soft px-3 py-2 text-sm text-ink" data-testid="term-quote">
            “{term.quote}”
          </blockquote>
        </div>
      ) : null}
    </Card>
  );
}
