"use client";

import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Skeleton } from "@/components/ui/States";
import { humanize, money, signedMoney, STATUS_LABEL } from "@/lib/format";
import { useAllowedActions, useExceptionAction, useMe, usePayAsBilled } from "@/lib/hooks";
import { journalTotals } from "@/lib/journal";
import type { ActionResult, ExceptionDetail, ItemAction } from "@/lib/types";
import { useState } from "react";

const ACTION_LABEL: Record<string, string> = { approve: "Approve", hold: "Hold", reject: "Reject" };
// The money screen offers sign-off, hold and reject; the rest of the queue's
// actions (resume, close, ...) live on the queue.
const SCREEN_ACTIONS = new Set(["approve", "hold", "reject"]);
const ACTION_DONE: Record<string, string> = { approve: "Approved", hold: "Held", reject: "Rejected" };

/** What confirms before it acts: everything that moves money or closes the decision. */
type Pending = "approve" | "hold" | "reject" | "pay_as_billed";

function outcome(action: ItemAction, res: ActionResult, did?: string): string {
  did = did ?? ACTION_DONE[action] ?? humanize(action);
  const state = res.state ? ` · ${res.state}` : ` · now ${STATUS_LABEL[res.status] ?? res.status}`;
  const p = res.posting;
  const kept = p?.disputed ? `; ${money(p.disputed)} stays held` : "";
  if (p?.status === "posted") {
    const amount = p.amount != null ? `${money(p.amount)} ` : "";
    return `${did} · ${amount}posted to the ledger (journal entry #${p.journal_entry_id})${kept}${state}`;
  }
  if (p?.status === "closed") return `${did} · nothing paid${kept}${state}`;
  if (p?.status === "pending") return `${did} · posting pending${p.error ? ` (${p.error})` : ""}${state}`;
  return `${did}${state}`;
}

/** A held charge: what "Uphold hold" does with the money, in one line. */
export function upholdCopy(ex: ExceptionDetail): string {
  const payable = ex.payable ?? ex.expected ?? 0;
  const disputed = ex.disputed ?? ex.delta ?? 0;
  return payable > 0 ? `Posts the undisputed ${money(payable)}; ${money(disputed)} stays held.` : `Nothing is paid; the ${money(disputed)} stays held.`;
}

/**
 * The decision, docked in the header so it never covers the documents. Only
 * the actions the server allows for this person appear (useAllowedActions),
 * and every one restates the money in a confirm before it acts.
 */
export function DecisionActions({ ex }: { ex: ExceptionDetail }) {
  const allowed = useAllowedActions(ex.exception_id);
  const m = useExceptionAction(ex.exception_id);
  const override = usePayAsBilled(ex.exception_id);
  const me = useMe();
  const [done, setDone] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<Pending | null>(null);
  const [why, setWhy] = useState("");

  const inv = ex.investigation;
  const actions = (allowed.data?.actions ?? []).filter((a) => SCREEN_ACTIONS.has(a));
  const blockApprove = !!inv && (!inv.balanced || !inv.explains_variance);
  const isHold = ex.proposal === "hold";
  const canOverride = isHold && actions.includes("approve") && me.data?.role === "controller";
  const busy = m.isPending || override.isPending;
  const error = m.error ?? override.error;
  const totals = inv ? journalTotals(inv.entries) : null;
  const label = (a: string) => (a === "approve" && isHold ? "Uphold hold" : ACTION_LABEL[a] ?? humanize(a));

  const close = () => {
    setConfirming(null);
    setWhy("");
  };
  const run = (a: ItemAction) => {
    override.reset();
    m.mutate(a, {
      onSuccess: (res) => {
        close();
        setDone(outcome(a, res, a === "approve" && isHold ? "Hold upheld" : undefined));
      },
      onError: () => {
        close();
        setDone(null);
      },
    });
  };
  const payAsBilled = () => {
    if (!why.trim()) return;
    m.reset();
    override.mutate(why.trim(), {
      onSuccess: (res) => {
        close();
        setDone(outcome("approve", res, "Paid as billed (controller override)"));
      },
      onError: () => {
        close();
        setDone(null);
      },
    });
  };

  const dialog: Record<Pending, { title: string; confirm: string; tone: "primary" | "danger" }> = {
    approve: isHold ? { title: "Uphold the hold?", confirm: "Uphold hold", tone: "primary" } : { title: "Approve and post?", confirm: "Approve", tone: "primary" },
    hold: { title: "Hold this charge?", confirm: "Hold", tone: "primary" },
    reject: { title: "Reject this charge?", confirm: "Reject", tone: "danger" },
    pay_as_billed: { title: "Pay as billed?", confirm: "Pay as billed", tone: "danger" },
  };
  const d = confirming ? dialog[confirming] : null;

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex shrink-0 flex-wrap items-center justify-end gap-2" data-testid="actions">
        {allowed.isLoading ? (
          <Skeleton className="h-10 w-48" />
        ) : allowed.isError ? (
          <span className="text-sm text-bad">Actions unavailable: {(allowed.error as Error).message}</span>
        ) : actions.length ? (
          <>
            {canOverride ? (
              <Button variant="ghost" disabled={busy} loading={override.isPending} data-testid="pay-as-billed" onClick={() => setConfirming("pay_as_billed")}>
                Pay as billed…
              </Button>
            ) : null}
            {[...actions]
              .sort((a, b) => (a === "approve" ? 1 : 0) - (b === "approve" ? 1 : 0))
              .map((a) => (
                <Button
                  key={a}
                  variant={a === "approve" ? "primary" : a === "reject" ? "danger" : "secondary"}
                  loading={m.isPending && m.variables === a}
                  disabled={busy}
                  disabledReason={a === "approve" && blockApprove ? "Entries must balance and explain the variance before approval" : undefined}
                  title={a === "approve" && isHold ? `Agree the charge is wrong. ${upholdCopy(ex)}` : undefined}
                  onClick={() => setConfirming(a as Pending)}
                >
                  {label(a)}
                </Button>
              ))}
          </>
        ) : (
          <span data-testid="no-actions" className="rounded-sm border border-line bg-sunken px-3 py-2 text-sm text-ink-muted">
            {ex.status === "balanced" ? `${ex.state ? humanize(ex.state.toLowerCase()) : "Approved"}: nothing to do` : "No actions for your role"}
          </span>
        )}
      </div>
      {error ? (
        <span role="alert" className="max-w-md text-right text-sm text-bad">
          {(error as Error).message}
        </span>
      ) : done ? (
        <span role="status" data-testid="action-result" className="max-w-md text-right text-sm font-medium text-ok">
          {done}
        </span>
      ) : isHold && actions.includes("approve") ? (
        <span data-testid="uphold-copy" className="text-xs text-ink-soft">
          Uphold hold: {upholdCopy(ex)}
        </span>
      ) : null}

      <ConfirmDialog
        open={d !== null}
        onOpenChange={(open) => !open && close()}
        title={d?.title ?? ""}
        confirmLabel={d?.confirm ?? ""}
        tone={d?.tone ?? "primary"}
        loading={busy}
        confirmDisabled={confirming === "pay_as_billed" && !why.trim()}
        onConfirm={() => {
          if (confirming === "pay_as_billed") payAsBilled();
          else if (confirming) run(confirming);
        }}
      >
        {confirming === "pay_as_billed" ? (
          <div data-testid="pay-as-billed-form">
            <p>
              {(ex.payable ?? ex.expected ?? 0) > 0 ? (
                <>
                  This pays the billed <span className="num font-semibold text-ink">{money(ex.actual)}</span>, including the disputed{" "}
                  <span className="num font-semibold text-ink">{money(ex.disputed ?? ex.delta)}</span> the lease does not support.
                </>
              ) : (
                <>
                  This pays the billed <span className="num font-semibold text-ink">{money(ex.actual)}</span>. None of it is supported by the lease.
                </>
              )}
            </p>
            <label htmlFor="override-reason" className="mt-3 block text-sm font-medium text-ink">
              Reason <span className="text-ink-muted">(required, recorded in the audit trail)</span>
            </label>
            <textarea
              id="override-reason"
              required
              rows={3}
              value={why}
              onChange={(e) => setWhy(e.target.value)}
              placeholder="Why the disputed amount is being paid"
              className="mt-1 w-full rounded-xs border border-line-strong bg-surface px-2 py-1.5 text-sm text-ink"
            />
          </div>
        ) : confirming === "hold" ? (
          <p>
            Nothing posts. The billed <span className="num font-semibold text-ink">{money(ex.actual)}</span> stays held until someone decides it, and the
            item moves to Held.
          </p>
        ) : confirming === "reject" ? (
          <p>
            This closes the charge against the billed <span className="num font-semibold text-ink">{money(ex.actual)}</span>. Nothing posts to the ledger.
          </p>
        ) : isHold ? (
          <p>
            You agree the billed <span className="num font-semibold text-ink">{money(ex.actual)}</span> is wrong. {upholdCopy(ex)} The disputed amount never
            reaches the ledger.
          </p>
        ) : totals && inv && inv.entries.length ? (
          <p>
            This posts <strong>{inv.entries.length} entries</strong> totalling <span className="num font-semibold text-ink">{money(totals.debit)}</span> on each
            side, against a billed <span className="num font-semibold text-ink">{money(ex.actual)}</span> and a variance of{" "}
            <span className="num font-semibold text-ink">{signedMoney(ex.delta)}</span>.
          </p>
        ) : (
          <p>
            This posts the billed <span className="num font-semibold text-ink">{money(ex.payable ?? ex.actual)}</span> to the ledger through the gateway (Dr lease
            cost, Cr accounts payable)
            {ex.delta ? (
              <>
                {" "}
                — a variance of <span className="num font-semibold text-ink">{signedMoney(ex.delta)}</span>, with no proposed entries to correct it
              </>
            ) : null}
            .
          </p>
        )}
        <p className="mt-2 text-ink-muted">Recorded in the audit trail under your name, and not reversible from this screen.</p>
      </ConfirmDialog>
    </div>
  );
}
