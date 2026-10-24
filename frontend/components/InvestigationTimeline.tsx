"use client";

import { investigate } from "@/lib/api";
import { pct, signedMoney } from "@/lib/format";
import type { InvestigationEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
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
          <span className="font-mono text-ink-soft" title={ev.doc_id ?? undefined}>
            {ev.source ?? (ev.doc_id ? (ev.doc_id.length > 24 ? `${ev.doc_id.slice(0, 12)}…` : ev.doc_id) : "document not on file")}
          </span>
          {ev.page != null ? <span className="text-ink-muted"> · p.{ev.page}</span> : null}
          {ev.confidence != null ? (
            <>
              {" "}
              · confidence <span className="num font-semibold">{pct(ev.confidence)}</span>
            </>
          ) : null}
          <span className="mt-1 block italic text-ink-soft">“{ev.quote}”</span>
        </span>
      );
    case "not_found":
      return <span className="text-bad">{ev.message}</span>;
    case "remeasured":
      return (
        <span className="num">
          Liability {signedMoney(ev.liability_delta)} · ROU {signedMoney(ev.rou_delta)}
        </span>
      );
    case "complete":
      return ev.balanced == null ? (
        <span>
          {ev.entries ? `${ev.entries} entries proposed` : "No entries proposed"}
          {ev.message ? <span className="mt-1 block text-ink-soft">{ev.message}</span> : null}
        </span>
      ) : (
        <span>
          {ev.entries} entries proposed ·{" "}
          <span className={cn("font-semibold", ev.balanced ? "text-ok" : "text-bad")}>{ev.balanced ? "balanced" : "NOT balanced"}</span>
          {ev.message ? <span className="mt-1 block text-ink-soft">{ev.message}</span> : null}
        </span>
      );
  }
}

/** The stage that fills a timeline slot: `not_found` answers the "found" step. */
function eventFor(seen: Map<string, InvestigationEvent>, stage: Stage): InvestigationEvent | undefined {
  return seen.get(stage) ?? (stage === "found" ? seen.get("not_found") : undefined);
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

  const seen = new Map<string, InvestigationEvent>(events.map((e) => [e.stage, e]));
  const finished = seen.has("complete");
  const nextIdx = STAGES.findIndex((s) => !eventFor(seen, s.stage));

  return (
    <div>
      <ol className="relative">
        {STAGES.map((s, i) => {
          const ev = eventFor(seen, s.stage);
          const active = state === "running" && i === nextIdx && !finished;
          const skipped = !ev && finished;
          return (
            <li key={s.stage} className="relative flex gap-3 pb-4 last:pb-0" data-stage={s.stage} data-done={ev ? "true" : "false"}>
              {i < STAGES.length - 1 ? (
                <span aria-hidden className={cn("absolute left-[9px] top-5 h-[calc(100%-12px)] w-px", ev ? "bg-accent" : "bg-line")} />
              ) : null}
              <span
                aria-hidden
                className={cn(
                  "relative z-10 mt-0.5 flex h-[19px] w-[19px] shrink-0 items-center justify-center rounded-full border text-[10px] font-bold",
                  ev ? "border-accent bg-accent text-white" : active ? "animate-pulse border-accent bg-accent-soft" : "border-line-strong bg-surface",
                )}
              >
                {ev ? "✓" : ""}
              </span>
              <div className="min-w-0 flex-1 text-sm">
                <div className="flex items-baseline justify-between gap-2">
                  <span className={cn("font-medium", !ev && !active && "text-ink-muted")}>{s.title}</span>
                  <span className="text-2xs uppercase tracking-wide text-ink-faint">{s.agent}</span>
                </div>
                {ev ? (
                  <div className="mt-0.5 text-ink-soft">{detail(ev)}</div>
                ) : active ? (
                  <div className="mt-0.5 text-ink-muted">Working…</div>
                ) : skipped ? (
                  <div className="mt-0.5 text-ink-muted">Skipped · nothing on record changes the lease terms.</div>
                ) : null}
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
          {state === "done" && `${events.length} event${events.length === 1 ? "" : "s"} received.`}
          {state === "error" && "Stopped."}
        </span>
        <Button size="sm" variant={state === "idle" ? "primary" : "secondary"} onClick={() => void run()} disabled={state === "running"}>
          {state === "idle" ? "Run investigation" : "Re-run"}
        </Button>
      </div>
    </div>
  );
}
