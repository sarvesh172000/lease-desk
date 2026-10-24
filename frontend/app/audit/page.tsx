"use client";

import { ChainLink, ChainVerdict } from "@/components/data/HashChain";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { exceptionIdFor } from "@/lib/api";
import { humanize, timestamp } from "@/lib/format";
import { useAudit } from "@/lib/hooks";
import type { AuditEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

export default function AuditPage() {
  return (
    <Suspense fallback={<LoadingBlock rows={6} label="Loading audit trail" />}>
      <AuditTrail />
    </Suspense>
  );
}

/** Fixture events name an exception; live events name the work item behind it. */
function subjectLink(e: AuditEvent): string | null {
  if (e.subject_type === "exception") return `/exceptions/${encodeURIComponent(e.subject_id)}`;
  if (e.subject_type === "work_item" && /^\d+$/.test(e.subject_id)) return `/exceptions/${exceptionIdFor(e.subject_id)}`;
  return null;
}

function AuditTrail() {
  const params = useSearchParams();
  const router = useRouter();
  const leaseId = params.get("lease_id") || undefined;
  const [onlyDenied, setOnlyDenied] = useState(false);
  const q = useAudit(leaseId);
  const events = (q.data?.events ?? []).filter((e) => !onlyDenied || !e.allowed).slice().sort((a, b) => b.seq - a.seq);

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="eyebrow">Append-only · hash-chained</div>
          <h1 className="text-2xl font-semibold">Audit trail{leaseId ? ` · ${leaseId}` : ""}</h1>
        </div>
        {q.data ? (
          <ChainVerdict
            verified={q.data.chain_verified}
            brokenAt={q.data.broken_at ?? q.data.broken_seq}
            count={q.data.events?.length ?? 0}
          />
        ) : null}
      </div>

      <div className="flex items-center gap-3 text-sm">
        {leaseId ? (
          <button type="button" className="rounded border border-line-strong bg-surface px-2.5 py-1 hover:bg-sunken" onClick={() => router.push("/audit")}>
            {leaseId} ✕
          </button>
        ) : null}
        <label className="inline-flex items-center gap-2 text-ink-soft">
          <input type="checkbox" checked={onlyDenied} onChange={(e) => setOnlyDenied(e.target.checked)} className="h-4 w-4 accent-[#0f5c5a]" />
          Denied attempts only
        </label>
        {q.data ? <span className="ml-auto text-ink-muted">{q.data.events.length} events</span> : null}
      </div>

      <Card>
        {q.isLoading ? (
          <div className="p-5">
            <LoadingBlock rows={6} label="Loading audit trail" />
          </div>
        ) : q.isError ? (
          <div className="p-5">
            <ErrorState title="Could not load the audit trail" error={q.error} onRetry={() => q.refetch()} />
          </div>
        ) : !events.length ? (
          <div className="p-5">
            <EmptyState title={onlyDenied ? "No denied attempts." : "No events yet."} />
          </div>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="table-head">
                <th className="w-14 py-2 pl-5 text-right font-semibold">Seq</th>
                <th className="w-56 px-3 py-2 font-semibold">When</th>
                <th className="px-3 py-2 font-semibold">Actor</th>
                <th className="px-3 py-2 font-semibold">Action</th>
                <th className="px-3 py-2 font-semibold">Subject</th>
                <th className="px-3 py-2 font-semibold">Outcome</th>
                <th className="w-36 px-3 py-2 pr-5 font-semibold">Hash</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e, i) => (
                <tr key={e.seq} className={cn("border-b border-line/70 align-top", !e.allowed && "bg-bad-soft/40")}>
                  <td className="num py-2.5 pl-5 text-right text-ink-muted">{e.seq}</td>
                  <td className="num px-3 py-2.5 text-ink-soft">{timestamp(e.at)}</td>
                  <td className="px-3 py-2.5">
                    <div className="font-medium">{e.actor_name ?? e.actor_id}</div>
                    <div className="font-mono text-2xs text-ink-muted">{e.actor_id}</div>
                  </td>
                  <td className="px-3 py-2.5">
                    {humanize(e.action)}
                    {e.human_approved ? <span className="ml-2 rounded bg-ok-soft px-1.5 py-px text-2xs font-semibold text-ok">human approved</span> : null}
                  </td>
                  <td className="px-3 py-2.5">
                    {subjectLink(e) ? (
                      <Link className="font-mono text-xs hover:text-accent hover:underline" href={subjectLink(e)!}>
                        {e.subject_id}
                      </Link>
                    ) : (
                      <span className="font-mono text-xs">{e.subject_id}</span>
                    )}
                    <div className="text-2xs text-ink-muted">{e.subject_type}</div>
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={cn("text-xs font-semibold uppercase tracking-wide", e.allowed ? "text-ok" : "text-bad")}>{e.allowed ? "Allowed" : "Denied"}</span>
                    {e.reason ? <div className="text-xs text-ink-soft">{e.reason}</div> : null}
                  </td>
                  <td className="px-3 py-2.5 pr-5">
                    <ChainLink
                      seq={e.seq}
                      hash={e.hash}
                      prevHash={e.prev_hash}
                      allowed={e.allowed}
                      index={i}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
