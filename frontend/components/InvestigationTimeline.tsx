"use client";

import { money, pct, signedMoney } from "@/lib/format";
import type { Investigation, InvestigationEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Check, Play, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";
import type { InvestigationRun, Stage } from "./money/useInvestigationRun";
import { Button } from "./ui/Button";

const STAGES: Array<{ stage: Stage; title: string; agent: string }> = [
  { stage: "searching", title: "Search the mailbox", agent: "Investigation agent" },
  { stage: "found", title: "Find the explaining document", agent: "Investigation agent" },
  { stage: "remeasured", title: "Remeasure the lease", agent: "Accounting engine" },
  { stage: "complete", title: "Propose entries", agent: "Accounting engine" },
];

function liveDetail(ev: InvestigationEvent): ReactNode {
  switch (ev.stage) {
    case "searching":
      return <span>{ev.message}</span>;
    case "found":
      return (
        <span>
          <span className="font-medium text-ink">{ev.source ?? ev.doc_id ?? "Document not on file"}</span>
          {ev.page != null ? <span className="text-ink-muted"> · p.{ev.page}</span> : null}
          {ev.confidence != null ? (
            <>
              {" "}
              · confidence <span className="num font-semibold">{pct(ev.confidence)}</span>
            </>
          ) : null}
        </span>
      );
    case "not_found":
      return (
        <span>
          {ev.message}
          <span className="mt-0.5 block text-ink-muted">No document changes the lease; the hold stands.</span>
        </span>
      );
    case "remeasured":
      return (
        <span className="num">
          Liability {signedMoney(ev.liability_delta)}
          {ev.rou_delta != null ? ` · ROU ${signedMoney(ev.rou_delta)}` : ""}
        </span>
      );
    case "complete":
      return (
        <span>
          {ev.entries ? `${ev.entries} entries proposed` : "No entries · nothing to post until the charge is explained"}
          {ev.balanced != null && ev.entries ? (
            <>
              {" · "}
              <span className={cn("font-semibold", ev.balanced ? "text-ok" : "text-bad")}>{ev.balanced ? "balanced" : "not balanced"}</span>
            </>
          ) : null}
          {ev.message ? <span className="mt-1 block text-ink-soft">{ev.message}</span> : null}
        </span>
      );
    case "error":
      return <span className="text-bad">{ev.message}</span>;
  }
}

/** The same four lines, read from the investigation already on record. */
function recordedDetail(stage: Stage, inv: Investigation): ReactNode {
  const ev = inv.evidence[0];
  switch (stage) {
    case "searching":
      return <span>Mailbox and document store searched.</span>;
    case "found":
      return ev ? (
        <span>
          <span className="font-medium text-ink">{ev.source}</span>
          {ev.page != null ? <span className="text-ink-muted"> · p.{ev.page}</span> : null} · confidence <span className="num font-semibold">{pct(inv.confidence)}</span>
        </span>
      ) : (
        <span>
          No explaining document.
          <span className="mt-0.5 block text-ink-muted">No document changes the lease; the hold stands.</span>
        </span>
      );
    case "remeasured":
      return inv.liability_before != null && inv.liability_after != null ? (
        <span className="num">
          Liability {money(inv.liability_before)} → {money(inv.liability_after)}
        </span>
      ) : (
        <span className="text-ink-muted">Skipped · nothing changes the lease terms.</span>
      );
    case "complete":
      return inv.entries.length ? (
        <span>
          {inv.entries.length} entries proposed ·{" "}
          <span className={cn("font-semibold", inv.balanced ? "text-ok" : "text-bad")}>{inv.balanced ? "balanced" : "not balanced"}</span>
        </span>
      ) : (
        <span>No entries · nothing to post until the charge is explained</span>
      );
  }
}

/**
 * The investigation, stage by stage. A live run shows exactly what the stream
 * sent, as it arrives; an investigation already on record shows its result at
 * once, with Replay to watch it again.
 */
/** The server's 403 in words: who may run it, not a number. */
export function runErrorText(error: string | null | undefined): string {
  if (!error) return "Stopped.";
  if (/^403\b|\b403\b/.test(error)) return "Your role cannot run the investigation; the controller or the regional manager can.";
  if (/^401\b/.test(error)) return "Sign in again to run the investigation.";
  return error;
}

export function InvestigationTimeline({ run, recorded, canRun = true }: { run: InvestigationRun; recorded?: Investigation | null; canRun?: boolean }) {
  const reduce = useReducedMotion();
  const settled = run.state === "idle" && !!recorded;
  const finished = !!run.get("complete");
  const nextIdx = STAGES.findIndex((s) => !(run.get(s.stage) ?? (s.stage === "found" ? run.get("not_found") : undefined)));
  const draw = reduce ? { duration: 0 } : { duration: 0.42, ease: [0.22, 1, 0.36, 1] as const };

  return (
    <div>
      <ol className="relative">
        {STAGES.map((s, i) => {
          const ev = run.get(s.stage) ?? (s.stage === "found" ? run.get("not_found") : undefined);
          const recordedSkip = settled && s.stage === "remeasured" && recorded?.liability_after == null;
          const done = (settled && !recordedSkip) || !!ev;
          const active = run.state === "running" && i === nextIdx && !finished;
          const skipped = !done && (run.state === "done" || recordedSkip);
          return (
            <li key={s.stage} className="relative flex gap-3 pb-4 last:pb-0" data-stage={s.stage} data-done={done ? "true" : "false"}>
              {i < STAGES.length - 1 ? (
                <span aria-hidden className="absolute left-[9px] top-5 h-[calc(100%-12px)] w-px bg-line">
                  <motion.span
                    className="absolute inset-0 block origin-top bg-accent"
                    initial={false}
                    animate={{ scaleY: done ? 1 : 0 }}
                    transition={settled ? { duration: 0 } : draw}
                  />
                </span>
              ) : null}
              <motion.span
                aria-hidden
                initial={false}
                animate={ev && !reduce ? { scale: [1, 1.22, 1] } : { scale: 1 }}
                transition={{ duration: 0.34, ease: "easeOut" }}
                className={cn(
                  "relative z-10 mt-0.5 flex h-[19px] w-[19px] shrink-0 items-center justify-center rounded-full border",
                  done ? "border-accent bg-accent text-accent-ink" : active ? "animate-pulse border-accent bg-accent-soft" : "border-line-strong bg-surface",
                )}
              >
                {done ? <Check className="h-3 w-3" strokeWidth={3} /> : null}
              </motion.span>
              <div className="min-w-0 flex-1 text-sm">
                <div className="flex items-baseline justify-between gap-2">
                  <span className={cn("font-medium transition-colors", !done && !active && "text-ink-muted")}>{s.title}</span>
                  <span className="shrink-0 text-2xs uppercase tracking-wide text-ink-faint">{s.agent}</span>
                </div>
                <AnimatePresence initial={false} mode="wait">
                  {settled && recorded ? (
                    <div key="recorded" className="mt-0.5 text-ink-soft">
                      {recordedDetail(s.stage, recorded)}
                    </div>
                  ) : ev ? (
                    <motion.div
                      key="detail"
                      initial={reduce ? { opacity: 0 } : { opacity: 0, y: -4 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.24, ease: "easeOut", delay: 0.1 }}
                      className="mt-0.5 text-ink-soft"
                    >
                      {liveDetail(ev)}
                    </motion.div>
                  ) : active ? (
                    <motion.div key="working" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-0.5 text-ink-muted">
                      Working…
                    </motion.div>
                  ) : skipped ? (
                    <motion.div key="skipped" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-0.5 text-ink-muted">
                      Skipped · nothing changes the lease terms.
                    </motion.div>
                  ) : null}
                </AnimatePresence>
              </div>
            </li>
          );
        })}
      </ol>

      {run.state === "error" ? (
        <div role="alert" className="mt-3 flex items-start justify-between gap-3 rounded-sm border border-bad-line bg-bad-soft px-3 py-2 text-sm text-bad">
          <span>{runErrorText(run.error)}</span>
          {canRun && !/403/.test(run.error ?? "") ? (
            <Button size="sm" variant="secondary" onClick={run.start}>
              Retry
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="mt-4 flex items-center justify-between gap-3">
        <span className="text-xs text-ink-muted" role="status">
          {run.state === "idle" && (recorded ? (canRun ? "On record. Replay to watch it again." : "On record.") : canRun ? "Not run yet." : "Not run yet; the controller or the regional manager runs it.")}
          {run.state === "running" && "Streaming from the investigation…"}
          {run.state === "done" && `${run.events.length} event${run.events.length === 1 ? "" : "s"} received.`}
          {run.state === "error" && "Stopped."}
        </span>
        {run.state !== "error" && canRun ? (
          <Button
            size="sm"
            variant={run.state === "idle" && !recorded ? "primary" : "secondary"}
            icon={run.state === "idle" && !recorded ? <Play aria-hidden className="h-3.5 w-3.5" /> : <RotateCcw aria-hidden className="h-3.5 w-3.5" />}
            onClick={run.start}
            loading={run.state === "running"}
            disabled={run.state === "running"}
          >
            {run.state === "idle" && !recorded ? "Run investigation" : "Replay"}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
