"use client";

import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { money } from "@/lib/format";
import type { DisputeReply, DisputeReplyOutcome } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useState } from "react";

export const OUTCOME_LABEL: Record<DisputeReplyOutcome, string> = {
  acknowledged: "Acknowledged",
  queried: "Queried",
  full_credit: "Credited in full",
  partial_credit: "Credited in part",
  refused: "Refused",
};

export interface ReplyDraft {
  outcome: DisputeReplyOutcome;
  granted: string;
  credit_memo_ref: string;
  reason: string;
  received_on: string;
  body: string;
}

export const EMPTY_DRAFT: ReplyDraft = { outcome: "acknowledged", granted: "", credit_memo_ref: "", reason: "", received_on: "", body: "" };

/**
 * What a landlord's reply must carry before it is recorded, by outcome: a
 * credit needs its memo reference and, when partial, an amount strictly
 * between zero and the disputed amount; a refusal needs the reason.
 */
export function validateReply(d: ReplyDraft, disputed: number): Record<string, string> {
  const errors: Record<string, string> = {};
  if (d.outcome === "full_credit" || d.outcome === "partial_credit") {
    if (!d.credit_memo_ref.trim()) errors.credit_memo_ref = "The landlord's credit memo reference";
  }
  if (d.outcome === "partial_credit") {
    const n = Number(d.granted);
    if (!d.granted.trim() || !Number.isFinite(n)) errors.granted = "The amount credited";
    else if (n <= 0) errors.granted = "More than $0.00";
    else if (n >= disputed) errors.granted = `Less than the ${money(disputed)} disputed; use "Credited in full" for all of it`;
  }
  if (d.outcome === "refused" && !d.reason.trim()) errors.reason = "The landlord's reason";
  if (d.received_on && !/^\d{4}-\d{2}-\d{2}$/.test(d.received_on)) errors.received_on = "A date, YYYY-MM-DD";
  return errors;
}

/** The reply as the API takes it; only the fields the outcome uses. */
export function toReply(d: ReplyDraft, disputed: number): DisputeReply {
  const r: DisputeReply = { outcome: d.outcome };
  if (d.outcome === "full_credit") {
    r.granted = disputed;
    r.credit_memo_ref = d.credit_memo_ref.trim();
  }
  if (d.outcome === "partial_credit") {
    r.granted = Number(d.granted);
    r.credit_memo_ref = d.credit_memo_ref.trim();
  }
  if (d.outcome === "refused") r.reason = d.reason.trim();
  if (d.received_on) r.received_on = d.received_on;
  if (d.body.trim()) r.body = d.body.trim();
  return r;
}

const field = "mt-1 w-full rounded-xs border border-line-strong bg-surface px-2 py-1.5 text-sm text-ink";

/** Record what the landlord replied, with a confirm that restates the money. */
export function ReplyForm({
  disputed,
  outcomes,
  onSubmit,
  pending,
  error,
}: {
  disputed: number;
  outcomes: DisputeReplyOutcome[];
  onSubmit: (reply: DisputeReply) => void;
  pending: boolean;
  error: Error | null;
}) {
  const [d, setD] = useState<ReplyDraft>({ ...EMPTY_DRAFT, outcome: outcomes[0] ?? "acknowledged" });
  const [touched, setTouched] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const errors = validateReply(d, disputed);
  const ok = Object.keys(errors).length === 0;
  const set = <K extends keyof ReplyDraft>(k: K, v: ReplyDraft[K]) => setD((x) => ({ ...x, [k]: v }));
  const credited = d.outcome === "full_credit" ? disputed : d.outcome === "partial_credit" ? Number(d.granted) || 0 : 0;

  return (
    <form
      data-testid="reply-form"
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        setTouched(true);
        if (ok) setConfirm(true);
      }}
    >
      <div>
        <label htmlFor="reply-outcome" className="text-sm font-medium">
          The landlord
        </label>
        <select id="reply-outcome" className={field} value={d.outcome} onChange={(e) => set("outcome", e.target.value as DisputeReplyOutcome)}>
          {outcomes.map((o) => (
            <option key={o} value={o}>
              {OUTCOME_LABEL[o]}
            </option>
          ))}
        </select>
      </div>
      {d.outcome === "full_credit" || d.outcome === "partial_credit" ? (
        <div className="grid grid-cols-2 gap-3">
          {d.outcome === "partial_credit" ? (
            <div>
              <label htmlFor="reply-granted" className="text-sm font-medium">
                Amount credited
              </label>
              <input id="reply-granted" inputMode="decimal" className={cn(field, "num", touched && errors.granted && "border-bad")} value={d.granted} onChange={(e) => set("granted", e.target.value)} placeholder={`under ${money(disputed)}`} />
              {touched && errors.granted ? <p className="mt-0.5 text-xs text-bad">{errors.granted}</p> : null}
            </div>
          ) : (
            <div>
              <div className="text-sm font-medium">Amount credited</div>
              <div className={cn(field, "num bg-sunken text-ink-soft")}>{money(disputed)}</div>
            </div>
          )}
          <div>
            <label htmlFor="reply-memo" className="text-sm font-medium">
              Credit memo ref
            </label>
            <input id="reply-memo" className={cn(field, "font-mono", touched && errors.credit_memo_ref && "border-bad")} value={d.credit_memo_ref} onChange={(e) => set("credit_memo_ref", e.target.value)} placeholder="CM-2026-…" />
            {touched && errors.credit_memo_ref ? <p className="mt-0.5 text-xs text-bad">{errors.credit_memo_ref}</p> : null}
          </div>
        </div>
      ) : null}
      {d.outcome === "refused" ? (
        <div>
          <label htmlFor="reply-reason" className="text-sm font-medium">
            Their reason
          </label>
          <textarea id="reply-reason" rows={2} className={cn(field, touched && errors.reason && "border-bad")} value={d.reason} onChange={(e) => set("reason", e.target.value)} />
          {touched && errors.reason ? <p className="mt-0.5 text-xs text-bad">{errors.reason}</p> : null}
        </div>
      ) : null}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="reply-received" className="text-sm font-medium">
            Received on <span className="font-normal text-ink-muted">(optional)</span>
          </label>
          <input id="reply-received" type="date" className={cn(field, "num", touched && errors.received_on && "border-bad")} value={d.received_on} onChange={(e) => set("received_on", e.target.value)} />
        </div>
        <div>
          <label htmlFor="reply-body" className="text-sm font-medium">
            What they wrote <span className="font-normal text-ink-muted">(optional)</span>
          </label>
          <input id="reply-body" className={field} value={d.body} onChange={(e) => set("body", e.target.value)} />
        </div>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-bad">
          {error.message}
        </p>
      ) : null}
      <div className="flex items-center justify-end gap-3">
        {touched && !ok ? <span className="text-xs text-bad">Fill in the fields marked</span> : null}
        <Button type="submit" variant="primary" loading={pending} data-testid="record-reply">
          Record reply
        </Button>
      </div>

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={`Record: ${OUTCOME_LABEL[d.outcome].toLowerCase()}?`}
        confirmLabel="Record reply"
        loading={pending}
        onConfirm={() => {
          onSubmit(toReply(d, disputed));
          setConfirm(false);
        }}
      >
        <p>
          {credited > 0 ? (
            <>
              The landlord credits <span className="num font-semibold text-ink">{money(credited)}</span> of the <span className="num font-semibold text-ink">{money(disputed)}</span> disputed
              {d.credit_memo_ref ? (
                <>
                  {" "}
                  under memo <span className="font-mono text-ink">{d.credit_memo_ref.trim()}</span>
                </>
              ) : null}
              . {credited < disputed ? <>The remaining {money(disputed - credited)} stays open.</> : "Nothing stays open."}
            </>
          ) : d.outcome === "refused" ? (
            <>
              The landlord refuses the <span className="num font-semibold text-ink">{money(disputed)}</span> dispute. It stays open as a receivable for the controller.
            </>
          ) : (
            <>
              The landlord {OUTCOME_LABEL[d.outcome].toLowerCase()} the <span className="num font-semibold text-ink">{money(disputed)}</span> dispute. Nothing posts.
            </>
          )}
        </p>
        <p className="mt-2 text-ink-muted">Recorded in the audit trail under your name.</p>
      </ConfirmDialog>
    </form>
  );
}
