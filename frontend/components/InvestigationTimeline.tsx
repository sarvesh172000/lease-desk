"use client";

import { investigate } from "@/lib/api";
import { pct, signedMoney } from "@/lib/format";
import type { InvestigationEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "./ui/Button";

type Stage = InvestigationEvent["stage"];
const STAGES: Array<{ stage: Stage; title: string; agent: string }> = [
  { stage: "searching", title: "Search the corpus", agent: "Investigation agent" },
  { stage: "found", title: "Find the explaining document", agent: "Investigation agent" },
  { stage: "remeasured", title: "Remeasure the lease", agent: "Accounting engine" },
  { stage: "complete", title: "Propose entries", agent: "Accounting engine" },
];

function detail(ev: InvestigationEvent) {
  switch (ev.stage) {
    case "searching":
      return <span>{ev.message}</span>;
    case "found":
      return (
        <span>
          <span className="font-mono text-ink-soft">{ev.doc_id}</span> · confidence <span className="num font-semibold">{pct(ev.confidence)}</span>
          <span className="mt-1 block italic text-ink-soft">“{ev.quote}”</span>
        </span>
      );
    case "remeasured":
      return (
        <span className="num">
          Liability {signedMoney(ev.liability_delta)} · ROU {signedMoney(ev.rou_delta)}
        </span>
      );
    case "complete":
      return (
        <span>
          {ev.entries} entries proposed ·{" "}
          <span className={cn("font-semibold", ev.balanced ? "text-ok" : "text-bad")}>{ev.balanced ? "balanced" : "NOT balanced"}</span>
        </span>
      );
  }
}

export function InvestigationTimeline({
  exceptionId,
  autoStart = false,
  onEvent,
}: {
  exceptionId: string;
  autoStart?: boolean;
  onEvent?: (e: InvestigationEvent) => void;
}) {
  const [events, setEvents] = useState<InvestigationEvent[]>([]);
  const [state, setState] = useState<"idle" | "running" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const reduce = useReducedMotion();

  const run = useCallback(async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setEvents([]);
    setError(null);
    setState("running");
    try {
      await investigate(
        exceptionId,
        (ev) => {
          setEvents((prev) => [...prev, ev]);
          onEventRef.current?.(ev);
        },
        ctrl.signal,
      );
      if (!ctrl.signal.aborted) setState("done");
    } catch (e) {
      if (ctrl.signal.aborted) return;
      setError(e instanceof Error ? e.message : String(e));
      setState("error");
    }
  }, [exceptionId]);

  useEffect(() => {
    if (autoStart) void run();
    return () => abortRef.current?.abort();
  }, [autoStart, run]);

  const seen = new Map(events.map((e) => [e.stage, e]));
  const nextIdx = STAGES.findIndex((s) => !seen.has(s.stage));

  // The line into a step draws only once its own event has arrived, so the
  // stroke is a readout of real progress, not a timed animation.
  const draw = reduce ? { duration: 0 } : { duration: 0.42, ease: [0.22, 1, 0.36, 1] as const };

  return (
    <div>
      <ol className="relative">
        {STAGES.map((s, i) => {
          const ev = seen.get(s.stage);
          const active = state === "running" && i === nextIdx;
          return (
            <li key={s.stage} className="relative flex gap-3 pb-4 last:pb-0" data-stage={s.stage} data-done={ev ? "true" : "false"}>
              {i < STAGES.length - 1 ? (
                <span aria-hidden className="absolute left-[9px] top-5 h-[calc(100%-12px)] w-px bg-line">
                  <motion.span
                    className="absolute inset-0 block origin-top bg-accent"
                    initial={false}
                    animate={{ scaleY: ev ? 1 : 0 }}
                    transition={draw}
                  />
                </span>
              ) : null}
              <motion.span
                aria-hidden
                initial={false}
                animate={ev ? { scale: [1, 1.22, 1] } : { scale: 1 }}
                transition={reduce ? { duration: 0 } : { duration: 0.34, ease: "easeOut" }}
                className={cn(
                  "relative z-10 mt-0.5 flex h-[19px] w-[19px] shrink-0 items-center justify-center rounded-full border text-[10px] font-bold",
                  ev ? "border-accent bg-accent text-white" : active ? "animate-pulse border-accent bg-accent-soft" : "border-line-strong bg-surface",
                )}
              >
                {ev ? "✓" : ""}
              </motion.span>
              <div className="min-w-0 flex-1 text-sm">
                <div className="flex items-baseline justify-between gap-2">
                  <span className={cn("font-medium transition-colors", !ev && !active && "text-ink-muted")}>{s.title}</span>
                  <span className="text-2xs uppercase tracking-wide text-ink-faint">{s.agent}</span>
                </div>
                <AnimatePresence initial={false} mode="wait">
                  {ev ? (
                    <motion.div
                      key="detail"
                      initial={reduce ? false : { opacity: 0, y: -4 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={reduce ? { duration: 0 } : { duration: 0.24, ease: "easeOut", delay: 0.1 }}
                      className="mt-0.5 text-ink-soft"
                    >
                      {detail(ev)}
                    </motion.div>
                  ) : active ? (
                    <motion.div
                      key="working"
                      initial={reduce ? false : { opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="mt-0.5 text-ink-muted"
                    >
                      Working…
                    </motion.div>
                  ) : null}
                </AnimatePresence>
              </div>
            </li>
          );
        })}
      </ol>

      {state === "error" ? (
        <p role="alert" className="mt-3 rounded border border-bad-line bg-bad-soft px-3 py-2 text-sm text-bad">
          Investigation stream failed: <span className="font-mono">{error}</span>
        </p>
      ) : null}

      <div className="mt-4 flex items-center justify-between gap-3">
        <span className="text-xs text-ink-muted">
          {state === "idle" && "Not run in this session."}
          {state === "running" && "Streaming from the investigation…"}
          {state === "done" && `${events.length} of ${STAGES.length} stages received.`}
          {state === "error" && "Stopped."}
        </span>
        <Button size="sm" variant={state === "idle" ? "primary" : "secondary"} onClick={() => void run()} disabled={state === "running"}>
          {state === "idle" ? "Run investigation" : "Re-run"}
        </Button>
      </div>
    </div>
  );
}
