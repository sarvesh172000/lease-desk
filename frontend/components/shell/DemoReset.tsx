"use client";

import { Button } from "@/components/ui/Button";
import { ApiError } from "@/lib/api";
import { useDemoReset } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import * as Dialog from "@radix-ui/react-dialog";
import { Check, RotateCcw, X } from "lucide-react";
import { useEffect, useState } from "react";

const STEPS = ["Restoring the snapshot", "Verifying the chain", "Checking the counts", "Clearing judge-provided items"];

/**
 * Reset the demo to its snapshot: a confirm that says what goes, progress
 * while it runs, and the API's own report when it is done. Demo mode and the
 * controller only; the menu hides it otherwise.
 */
export function DemoResetDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const reset = useDemoReset();
  const [step, setStep] = useState(0);
  // the API gives no progress stream; the steps advance on a timer while it runs, and settle on its answer
  useEffect(() => {
    if (!reset.isPending) return;
    setStep(0);
    const t = setInterval(() => setStep((s) => Math.min(STEPS.length - 1, s + 1)), 1200);
    return () => clearInterval(t);
  }, [reset.isPending]);
  const notLive = reset.error instanceof ApiError && reset.error.status === 501;
  const r = reset.data;

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => {
        if (!o) reset.reset();
        onOpenChange(o);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50 motion-safe:animate-in motion-safe:fade-in" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(30rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-md border border-line bg-surface shadow-float motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-95" data-testid="demo-reset">
          <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
            <div>
              <Dialog.Title className="flex items-center gap-2 text-lg font-semibold">
                <RotateCcw aria-hidden className="h-5 w-5 text-esc" /> Reset the demo
              </Dialog.Title>
              <Dialog.Description className="text-sm text-ink-muted">Back to the snapshot: every approval, hold, letter and question made since goes. The audit chain is re-verified afterwards.</Dialog.Description>
            </div>
            <Dialog.Close className="rounded-xs p-1 text-ink-muted hover:bg-raised hover:text-ink" aria-label="Close">
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>
          <div className="space-y-4 px-5 py-4">
            {reset.isPending || r ? (
              <ol className="space-y-2" aria-live="polite" data-testid="reset-progress">
                {STEPS.map((s, i) => {
                  const done = r ? true : i < step;
                  const now = !r && i === step;
                  return (
                    <li key={s} className={cn("flex items-center gap-2 text-sm", done ? "text-ink" : now ? "text-ink" : "text-ink-muted")}>
                      <span className={cn("flex h-5 w-5 items-center justify-center rounded-full border text-2xs", done ? "border-ok bg-ok text-accent-ink" : now ? "animate-pulse border-accent" : "border-line")}>{done ? <Check className="h-3 w-3" strokeWidth={3} /> : null}</span>
                      {s}
                      {now ? "…" : ""}
                    </li>
                  );
                })}
              </ol>
            ) : (
              <p className="text-sm text-ink-soft">The snapshot is the state the demo starts from. Items judges added are cleared too. Nothing outside the demo database is touched.</p>
            )}
            {r ? (
              <div className={cn("rounded-sm border px-3 py-2 text-sm", r.verified && r.chain_ok ? "border-ok-line bg-ok-soft" : "border-warn-line bg-warn-soft")} role="status" data-testid="reset-result">
                <div className="font-semibold">
                  {r.verified && r.chain_ok ? "Reset and verified" : "Reset, with warnings"} · <span className="num">{r.seconds.toFixed(1)}s</span>
                  {r.within_budget ? "" : ` (over the ${r.budget_seconds}s budget)`}
                </div>
                <div className="text-xs text-ink-soft">
                  Chain {r.chain_ok ? "verified" : "not verified"} · counts {r.counts_match ? "match" : "differ"} · head {r.head_match ? "matches" : "differs"} · {r.judge_provided_cleared} judge-provided item{r.judge_provided_cleared === 1 ? "" : "s"} cleared · audit #{r.event_seq}
                </div>
              </div>
            ) : null}
            {reset.isError ? (
              <p role="alert" className="text-sm text-bad">
                {notLive ? "Resetting needs the live API." : reset.error.message}
              </p>
            ) : null}
            <div className="flex justify-end gap-2">
              <Dialog.Close asChild>
                <Button variant="secondary">{r ? "Done" : "Cancel"}</Button>
              </Dialog.Close>
              {!r ? (
                <Button variant="danger" loading={reset.isPending} onClick={() => reset.mutate()} data-testid="confirm-reset">
                  Reset the demo
                </Button>
              ) : null}
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
