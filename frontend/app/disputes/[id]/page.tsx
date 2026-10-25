"use client";

import { ReplyForm } from "@/components/disputes/ReplyForm";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { ApiError, exceptionIdFor } from "@/lib/api";
import { day, humanize, money, period, timestamp } from "@/lib/format";
import { useApproveDisputeLetter, useApproveDisputeReceivable, useDispute, useLeases, useMe, useRecordDisputeReply } from "@/lib/hooks";
import { actionLabel, chargeLabel, disputeStatusLabel, placeLabel } from "@/lib/labels";
import type { DisputeDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Check, Mail, Send, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

export default function DisputePage() {
  const { id } = useParams<{ id: string }>();
  const disputeId = decodeURIComponent(id);
  const q = useDispute(disputeId);
  if (q.isLoading) return <LoadingBlock rows={8} label="Loading the dispute" />;
  if (q.isError) {
    const nf = q.error instanceof ApiError && q.error.status === 404;
    return (
      <div className="space-y-4">
        <Back />
        {nf ? <EmptyState title="This dispute was not found." /> : <ErrorState title="Could not load the dispute" error={q.error} onRetry={() => q.refetch()} />}
      </div>
    );
  }
  return <Dispute d={q.data!} />;
}

function Back() {
  return (
    <Link href="/disputes" className="text-sm text-ink-muted hover:text-accent">
      ← Disputes
    </Link>
  );
}

function Dispute({ d }: { d: DisputeDetail }) {
  const s = d.dispute;
  const me = useMe();
  const leases = useLeases();
  const lease = leases.data?.find((l) => l.lease_id === s.lease_id);
  const letter = useApproveDisputeLetter(s.id);
  const receivable = useApproveDisputeReceivable(s.id);
  const reply = useRecordDisputeReply(s.id);
  const [confirming, setConfirming] = useState<"letter" | "receivable" | null>(null);
  // only what the server allows: the letter's and the receivable's work items carry their own allowed actions
  const canLetter = d.items.letter?.state === "PROPOSED" && me.data?.role === "regional_manager";
  const canReceivable = d.items.receivable?.state === "PROPOSED" && me.data?.role === "controller";
  const canReply = s.status === "sent" || s.status === "acknowledged" || s.status === "partially_credited";
  const open = s.amount - s.credited_amount;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          <Back />
          <h1 className="mt-1 text-2xl font-semibold leading-tight">
            {chargeLabel(s.charge_type)} · {period(s.period)}
            <span className="font-normal text-ink-soft"> · {lease ? (placeLabel(lease.location) ?? lease.location) : s.clinic_id}</span>
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <span className={cn("rounded-full border px-2.5 py-0.5 text-xs font-semibold", s.status === "refused" ? "border-bad-line bg-bad-soft text-bad" : s.status === "credited" || s.status === "partially_credited" ? "border-ok-line bg-ok-soft text-ok" : s.status === "drafted" ? "border-warn-line bg-warn-soft text-warn" : "border-accent/40 bg-accent-soft text-accent")}>
              {disputeStatusLabel(s.status)}
            </span>
            <span className="font-mono text-2xs text-ink-muted">
              {s.id} · {s.invoice_id} · {s.lease_id}
            </span>
            <Link href={`/exceptions/${exceptionIdFor(s.work_item_id)}`} className="text-xs text-accent hover:underline" data-testid="held-charge-link">
              The held charge →
            </Link>
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <div className="flex flex-wrap items-center justify-end gap-2" data-testid="dispute-actions">
            {canLetter ? (
              <Button variant="primary" icon={<Send aria-hidden className="h-4 w-4" />} loading={letter.isPending} onClick={() => setConfirming("letter")} data-testid="approve-letter">
                Approve and send the letter
              </Button>
            ) : null}
            {canReceivable ? (
              <Button variant="primary" icon={<Check aria-hidden className="h-4 w-4" />} loading={receivable.isPending} onClick={() => setConfirming("receivable")} data-testid="approve-receivable">
                Approve the receivable
              </Button>
            ) : null}
            {!canLetter && !canReceivable ? (
              <span className="rounded-sm border border-line bg-sunken px-3 py-2 text-sm text-ink-muted">
                {d.items.letter?.state === "PROPOSED" ? "The regional manager approves the letter" : d.items.receivable?.state === "PROPOSED" ? "The controller approves the receivable" : "No action waits on you"}
              </span>
            ) : null}
          </div>
          {letter.isError || receivable.isError ? (
            <span role="alert" className="text-xs text-bad">
              {(letter.error ?? receivable.error)?.message}
            </span>
          ) : d.gateway_error ? (
            <span role="alert" className="text-xs text-bad">
              Gateway: {d.gateway_error}
            </span>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-4 overflow-hidden rounded-md border border-line bg-surface shadow-raised">
        <Figure label="Billed" value={money(s.billed)} />
        <Figure label="Lease supports" value={money(s.supported)} />
        <Figure label="Disputed" value={money(s.amount)} tone="bad" />
        <Figure label={s.credited_amount ? "Credited · open" : "Credited"} value={s.credited_amount ? `${money(s.credited_amount)} · ${money(open)}` : money(0)} tone={s.credited_amount ? "ok" : undefined} />
      </div>

      <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] gap-4">
        {/* the letter, as correspondence */}
        <Card className="overflow-hidden">
          <CardHeader
            eyebrow={`To ${d.notice_to.name}`}
            title={`Attn ${d.notice_to.attn} · ${d.notice_to.email}`}
            actions={
              <span className="flex items-center gap-1 text-xs text-ink-muted">
                <Mail aria-hidden className="h-3.5 w-3.5" /> {d.notice_to.address}
              </span>
            }
          />
          <CardBody className="bg-sunken/40 p-5">
            <article className="mx-auto max-w-[640px] rounded-xs border border-line bg-surface px-10 py-9 shadow-raised" data-testid="letter">
              <pre className="whitespace-pre-wrap font-sans text-[0.9rem] leading-relaxed text-ink">{d.letter}</pre>
            </article>
          </CardBody>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader eyebrow="History" title="What has happened" />
            <CardBody>
              <ol className="relative ml-2 border-l border-line pl-5">
                {[...d.history].sort((a, b) => a.seq - b.seq).map((h) => (
                  <li key={h.seq} className="relative pb-3 last:pb-0">
                    <span aria-hidden className={cn("absolute -left-[26px] top-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-surface", h.allowed ? "bg-accent" : "bg-bad")} />
                    <div className="flex items-baseline justify-between gap-3 text-sm">
                      <span className="font-medium">
                        {actionLabel(h.action)}
                        {h.to_status ? <span className="text-ink-muted"> · {disputeStatusLabel(h.to_status)}</span> : null}
                        {!h.allowed ? <span className="ml-1.5 rounded-xs bg-bad-soft px-1 text-2xs font-semibold uppercase text-bad">refused</span> : null}
                      </span>
                      <span className="num shrink-0 text-xs text-ink-muted">{timestamp(h.at)}</span>
                    </div>
                    <div className="font-mono text-2xs text-ink-muted">{h.actor_id}</div>
                    {h.reason ? <p className="text-xs text-ink-soft">{h.reason}</p> : null}
                  </li>
                ))}
              </ol>
              {d.outbox.length ? (
                <div className="mt-4 border-t border-line pt-3">
                  <div className="eyebrow mb-1">Outbox</div>
                  <ul className="space-y-1 text-xs">
                    {d.outbox.map((m) => (
                      <li key={m.id} className="flex items-center justify-between gap-2">
                        <span className="truncate">
                          {m.subject ?? m.key} <span className="text-ink-muted">→ {m.to}</span>
                        </span>
                        <span className={cn("shrink-0 font-semibold uppercase", m.status === "sent" ? "text-ok" : m.status === "failed" ? "text-bad" : "text-warn")}>
                          {m.status}
                          {m.sent_at ? ` · ${day(m.sent_at)}` : ""}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader eyebrow="Money" title="Credits and the receivable" />
            <CardBody className="space-y-3 text-sm">
              {d.credits.length ? (
                <ul className="divide-y divide-line">
                  {d.credits.map((c) => (
                    <li key={c.credit_memo_ref} className="flex items-center justify-between py-1.5">
                      <span>
                        Credit memo <span className="font-mono">{c.credit_memo_ref}</span> <span className="text-ink-muted">· {day(c.received_on)}</span>
                      </span>
                      <span className="num font-semibold text-ok">{money(Number(c.amount))}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-ink-muted">No credits received yet.</p>
              )}
              {d.refusal_reason ? <p className="rounded-sm border-l-[3px] border-bad bg-bad-soft/60 px-3 py-2 text-ink">Refused: {d.refusal_reason}</p> : null}
              <dl className="num grid grid-cols-3 gap-2 rounded-sm border border-line px-3 py-2">
                <div>
                  <dt className="text-2xs uppercase tracking-wide text-ink-muted">Recognised</dt>
                  <dd className="font-semibold">{money(d.receivable.recognized)}</dd>
                </div>
                <div>
                  <dt className="text-2xs uppercase tracking-wide text-ink-muted">Cleared</dt>
                  <dd className="font-semibold">{money(d.receivable.cleared)}</dd>
                </div>
                <div>
                  <dt className="text-2xs uppercase tracking-wide text-ink-muted">Open</dt>
                  <dd className={cn("font-semibold", d.receivable.open ? "text-warn" : "")}>{money(d.receivable.open)}</dd>
                </div>
              </dl>
              {d.receivable.entries.length ? (
                <ul className="text-xs text-ink-muted">
                  {d.receivable.entries.map((e) => (
                    <li key={e.journal_entry_id}>
                      JE #{e.journal_entry_id} · {e.key} · {day(e.date)} · Dr {money(e.debit)} / Cr {money(e.credit)}
                    </li>
                  ))}
                </ul>
              ) : null}
            </CardBody>
          </Card>

          {canReply ? (
            <Card>
              <CardHeader eyebrow="The landlord replied" title="Record the reply" />
              <CardBody>
                <ReplyForm disputed={open > 0 ? open : s.amount} outcomes={d.reply_outcomes} onSubmit={(r) => reply.mutate(r)} pending={reply.isPending} error={reply.error} />
                {reply.isSuccess ? (
                  <p role="status" className="mt-2 text-sm text-ok">
                    Recorded · now {disputeStatusLabel(reply.data.dispute.status)}
                  </p>
                ) : null}
              </CardBody>
            </Card>
          ) : s.status === "drafted" ? (
            <p className="text-xs text-ink-muted">A reply can be recorded once the letter has been sent.</p>
          ) : null}
        </div>
      </div>

      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(o) => !o && setConfirming(null)}
        title={confirming === "letter" ? "Approve and send the letter?" : "Approve the receivable?"}
        confirmLabel={confirming === "letter" ? "Send the letter" : "Approve"}
        loading={letter.isPending || receivable.isPending}
        onConfirm={() => {
          const done = () => setConfirming(null);
          if (confirming === "letter") letter.mutate(undefined, { onSettled: done });
          else receivable.mutate(undefined, { onSettled: done });
        }}
      >
        {confirming === "letter" ? (
          <p>
            The gateway queues the letter to {d.notice_to.name} ({d.notice_to.email}) disputing <span className="num font-semibold text-ink">{money(s.amount)}</span> of invoice{" "}
            <span className="font-mono">{s.invoice_id}</span>. Nothing posts to the ledger.
          </p>
        ) : (
          <p>
            This recognises a receivable of <span className="num font-semibold text-ink">{money(open)}</span> from {s.landlord_name} in the ledger.
          </p>
        )}
        <p className="mt-2 text-ink-muted">Recorded in the audit trail under your name.</p>
      </ConfirmDialog>
      <span className="sr-only">{humanize(s.work_item_state)}</span>
      <X className="hidden" aria-hidden />
    </div>
  );
}

function Figure({ label, value, tone }: { label: string; value: string; tone?: "bad" | "ok" }) {
  return (
    <div className="border-l border-line px-5 py-3 first:border-l-0">
      <div className="eyebrow">{label}</div>
      <div className={cn("num mt-1 text-[1.4rem] font-semibold leading-tight", tone === "bad" && "text-bad", tone === "ok" && "text-ok")}>{value}</div>
    </div>
  );
}
