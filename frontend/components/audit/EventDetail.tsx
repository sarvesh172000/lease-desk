"use client";

import { EvidencePackButton } from "@/components/money/EvidencePackButton";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/States";
import { afterCrack } from "@/lib/chain";
import { timestamp } from "@/lib/format";
import { useMe } from "@/lib/hooks";
import { actionLabel, actorKind, attemptLabel } from "@/lib/labels";
import type { AuditEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Check, Copy, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { subjectHref } from "./AuditTable";

function CopyButton({ value, label }: { value: string; label: string }) {
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!done) return;
    const t = setTimeout(() => setDone(false), 1500);
    return () => clearTimeout(t);
  }, [done]);
  return (
    <button
      type="button"
      aria-label={done ? `${label} copied` : `Copy ${label}`}
      onClick={() => navigator.clipboard?.writeText(value).then(() => setDone(true))}
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xs border border-line text-ink-muted transition-colors hover:border-line-strong hover:text-ink"
    >
      {done ? <Check aria-hidden className="h-3.5 w-3.5 text-ok" /> : <Copy aria-hidden className="h-3.5 w-3.5" />}
    </button>
  );
}

function HashField({ label, value, note, tone }: { label: string; value: string | null | undefined; note?: string; tone?: "ok" | "bad" }) {
  return (
    <div>
      <div className="eyebrow flex items-center gap-2">
        {label}
        {note ? <span className={cn("normal-case tracking-normal", tone === "bad" ? "text-bad" : tone === "ok" ? "text-ok" : "text-ink-muted")}>· {note}</span> : null}
      </div>
      <div className="mt-1 flex items-start gap-2">
        <code className="min-w-0 flex-1 break-all font-mono text-2xs leading-relaxed text-ink-soft">{value ?? "—"}</code>
        {value ? <CopyButton value={value} label={label} /> : null}
      </div>
    </div>
  );
}

/** The selected event in full: who, what, which subject, when, why, and the two hashes that seal it. */
export function EventDetail({ event, prev, crackSeq }: { event: AuditEvent | null; prev: AuditEvent | null; crackSeq: number | null }) {
  const me = useMe();
  if (!event) {
    return (
      <div className="flex h-full items-center p-4">
        <EmptyState title="Select an event." className="w-full">
          Click a block in the strip or a row in the table to see who did what, when, and the hashes that seal it.
        </EmptyState>
      </div>
    );
  }
  const kind = actorKind(event.actor_id);
  const href = subjectHref(event);
  const cracked = afterCrack(event.seq, crackSeq);
  const linkOk = prev ? event.prev_hash === prev.hash : event.prev_hash === "0".repeat(64);
  const itemId = event.subject_type === "work_item" && /^\d+$/.test(event.subject_id) ? Number(event.subject_id) : null;
  const canPack = me.data?.role === "auditor" || me.data?.role === "controller";

  return (
    <div className={cn("flex h-full flex-col gap-3 overflow-y-auto p-4", !event.allowed && "bg-bad-soft/20")} data-testid="event-detail" data-seq={event.seq}>
      <div className="flex items-center justify-between gap-2">
        <span className="num font-mono text-xs text-ink-muted">
          #{event.seq} · {timestamp(event.at)}
        </span>
        <span className={cn("rounded-xs px-2 py-0.5 text-2xs font-bold uppercase tracking-wide", event.allowed ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad")}>{event.allowed ? "Allowed" : "Refused"}</span>
      </div>
      <div>
        <div className="text-lg font-semibold leading-tight">{event.actor_name ?? event.actor_id}</div>
        <div className="font-mono text-xs text-ink-muted">
          {event.actor_id}
          {kind !== "person" ? ` · ${kind}` : ""}
        </div>
        <p className="mt-2 text-sm text-ink-soft">
          {event.allowed ? actionLabel(event.action) : attemptLabel(event.action)}{" "}
          <span className="text-ink-muted">{event.subject_type.replace(/_/g, " ")}</span>{" "}
          {href ? (
            <Link href={href} className="font-mono text-ink hover:text-accent hover:underline">
              {event.subject_id}
            </Link>
          ) : (
            <span className="font-mono text-ink">{event.subject_id}</span>
          )}
          {event.lease_id && event.subject_type !== "lease" ? (
            <>
              {" · "}
              <Link href={`/leases/${encodeURIComponent(event.lease_id)}`} className="font-mono text-ink-muted hover:text-accent">
                {event.lease_id}
              </Link>
            </>
          ) : null}
        </p>
      </div>
      {event.reason ? (
        <p className={cn("rounded-sm border-l-[3px] px-3 py-2 text-sm leading-snug", event.allowed ? "border-line bg-sunken/60 text-ink-soft" : "border-bad bg-bad-soft/60 text-ink")} data-testid="event-reason">
          {event.reason}
        </p>
      ) : null}
      {event.policy_ref || event.model_ref || event.human_approved ? (
        <div className="flex flex-wrap gap-1.5">
          {event.policy_ref ? <span className="rounded-xs border border-line px-1.5 py-0.5 font-mono text-2xs text-ink-soft">policy · {event.policy_ref}</span> : null}
          {event.model_ref ? <span className="rounded-xs border border-line px-1.5 py-0.5 font-mono text-2xs text-ink-soft">model · {event.model_ref}</span> : null}
          {event.human_approved ? <span className="rounded-xs border border-ok-line bg-ok-soft px-1.5 py-0.5 text-2xs font-semibold text-ok">human approved</span> : null}
        </div>
      ) : null}
      <HashField label="hash" value={event.hash} note={cracked ? "unverifiable after the break" : undefined} tone={cracked ? "bad" : undefined} />
      <HashField
        label="prev_hash"
        value={event.prev_hash}
        note={prev ? (linkOk ? `seals #${prev.seq}` : `does not match #${prev.seq}`) : linkOk ? "64 zeros: the first link" : "unexpected first link"}
        tone={linkOk && !cracked ? "ok" : linkOk ? undefined : "bad"}
      />
      <div className="mt-auto flex flex-wrap items-center gap-2 pt-2">
        {canPack ? <EvidencePackButton itemId={itemId} exceptionId={itemId != null ? `exc_${itemId}` : event.subject_id} /> : null}
        {href ? (
          <Link href={href} className="inline-flex">
            <Button variant="secondary" size="sm" icon={<ExternalLink aria-hidden className="h-3.5 w-3.5" />} tabIndex={-1}>
              Open {event.subject_type === "work_item" ? "item" : event.subject_type.replace(/_/g, " ")}
            </Button>
          </Link>
        ) : null}
      </div>
    </div>
  );
}
