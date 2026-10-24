"use client";

import { DocumentViewer } from "@/components/DocumentViewer";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { day, humanize, money, timestamp } from "@/lib/format";
import { useConfirmLeaseVersion, useLeaseVersions } from "@/lib/hooks";
import type { LeaseTerm, LeaseVersion } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useState } from "react";

const MONEY_FIELDS = new Set(["base_rent_monthly", "security_deposit", "cam_estimate_psf_annual"]);

/** A term's value as a person reads it. Formatting only: the value is the server's. */
export function formatTermValue(term: LeaseTerm): string {
  const v = term.value;
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") {
    if (MONEY_FIELDS.has(term.field)) return money(v);
    if (term.field === "escalation_amount") return v < 1 ? `${(v * 100).toFixed(2)}%` : money(v);
    if (term.field === "proportionate_share_pct") return `${v.toFixed(2)}%`;
    return v.toLocaleString("en-US");
  }
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)) return day(v);
  if (typeof v === "string") return v.includes("_") ? humanize(v) : v;
  return JSON.stringify(v);
}

function Confidence({ value }: { value: number | null }) {
  const v = value ?? 0;
  const tone = v >= 0.92 ? "text-ok" : v >= 0.7 ? "text-warn" : "text-bad";
  return <span className={cn("num font-semibold", tone)}>{Math.round(v * 100)}%</span>;
}

/**
 * The lease as abstracted: each version's fields with their confidence, a
 * click that opens the cited page with the box drawn, and Confirm when the
 * signed-in person may confirm (from can() on the server).
 */
export function LeaseVersionPanel({ leaseId }: { leaseId: string }) {
  const versions = useLeaseVersions(leaseId);
  const confirm = useConfirmLeaseVersion(leaseId);
  const [selected, setSelected] = useState<string | null>(null);

  if (versions.isLoading) return <LoadingBlock rows={4} label="Loading abstraction" />;
  if (versions.isError) return <ErrorState title="Could not load the abstraction" error={versions.error} onRetry={() => versions.refetch()} />;
  const list = versions.data ?? [];
  if (!list.length) {
    return (
      <Card>
        <CardHeader eyebrow="Abstraction" title="Lease terms" />
        <CardBody>
          <EmptyState title="Not abstracted yet.">The monthly run drafts version 1 from the lease PDF.</EmptyState>
        </CardBody>
      </Card>
    );
  }
  const v: LeaseVersion = list[list.length - 1];
  const term = v.terms.find((t) => t.field === selected) ?? null;
  const canConfirm = !!v.work_item && v.work_item.allowed_actions.includes("approve");
  const path = v.terms.find((t) => t.extracted_by?.agent)?.extracted_by?.agent ?? null;

  return (
    <Card>
      <CardHeader
        eyebrow={`Abstraction · ${path === "abstraction:llm" ? "read by the abstraction agent" : path === "abstraction:generator" ? "from the generated lease terms" : "source unknown"}`}
        title={
          v.confirmed
            ? `v${v.version} confirmed by ${v.confirmed_by} on ${timestamp(v.confirmed_at)}`
            : `v${v.version} awaiting confirmation — the checker does not use it yet`
        }
        actions={
          canConfirm ? (
            <Button variant="primary" size="sm" disabled={confirm.isPending} onClick={() => confirm.mutate(v.work_item!.id)}>
              {confirm.isPending ? "Confirming…" : "Confirm lease terms"}
            </Button>
          ) : null
        }
      />
      {confirm.isError ? <p className="px-5 pt-3 text-sm text-bad">{confirm.error.message}</p> : null}
      <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-2">
        <table className="w-full border-collapse self-start text-sm">
          <thead>
            <tr className="table-head bg-sunken">
              <th className="py-2 pl-3 font-semibold">Field</th>
              <th className="px-3 py-2 font-semibold">Value</th>
              <th className="px-3 py-2 text-right font-semibold">Confidence</th>
              <th className="px-3 py-2 pr-3 text-right font-semibold">Cited</th>
            </tr>
          </thead>
          <tbody>
            {v.terms.map((t) => (
              <tr key={t.field} className={cn("border-b border-line/60", selected === t.field && "bg-accent-soft/60")}>
                <td className="py-1.5 pl-3">{humanize(t.field)}</td>
                <td className="num px-3 py-1.5">{formatTermValue(t)}</td>
                <td className="px-3 py-1.5 text-right">
                  <Confidence value={t.confidence} />
                </td>
                <td className="px-3 py-1.5 pr-3 text-right">
                  {t.page && t.bbox && t.document_id ? (
                    <button type="button" className="text-accent hover:underline" onClick={() => setSelected(t.field)}>
                      p.{t.page}
                    </button>
                  ) : (
                    <span className="text-bad" title="The quote was not found on any page">not located</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {term && term.document_id && term.page ? (
          <DocumentViewer
            eyebrow={`${leaseId} · ${humanize(term.field)}`}
            title={term.quote ?? humanize(term.field)}
            docId={term.document_id}
            page={term.page}
            box={term.bbox}
            tone="cited"
            label={humanize(term.field)}
            fallbackText={term.quote}
            height={480}
          />
        ) : (
          <div className="flex items-center justify-center rounded-md border border-dashed border-line p-6 text-sm text-ink-muted">
            Pick a cited page to see the clause boxed on the lease.
          </div>
        )}
      </div>
    </Card>
  );
}
