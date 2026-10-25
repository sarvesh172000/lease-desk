"use client";

import { investigate } from "@/lib/api";
import type { InvestigationEvent } from "@/lib/types";
import { useQueryClient } from "@tanstack/react-query";
import { useReducedMotion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";

export type RunState = "idle" | "running" | "done" | "error";
export type Stage = "searching" | "found" | "remeasured" | "complete";

/** Where the screen is in the story; "settled" is a result already on record. */
export type Phase = "ready" | "settled" | Stage;

export interface InvestigationRun {
  state: RunState;
  events: InvestigationEvent[];
  error: string | null;
  /** The latest stage reached in this session's run (not_found answers "found"). */
  stage: Stage | null;
  get: <S extends InvestigationEvent["stage"]>(s: S) => Extract<InvestigationEvent, { stage: S }> | undefined;
  start: () => void;
}

const ORDER: Stage[] = ["searching", "found", "remeasured", "complete"];

/**
 * How long each beat holds the stage before the next may show, so a fast
 * stream still reads as four steps. Pacing only delays what is shown; it never
 * invents an event.
 */
const DWELL_MS: Record<Stage, number> = { searching: 1800, found: 2000, remeasured: 2200, complete: 0 };
const DWELL_REDUCED_MS = 350;

function stageIndex(ev: InvestigationEvent): number {
  return ev.stage === "not_found" ? 1 : ORDER.indexOf(ev.stage as Stage);
}

/**
 * The investigation stream for one exception, shared by everything on the
 * money screen that reacts to it: the timeline, the document stack, the
 * remeasurement and the entries. Events are only ever what the server sent.
 * When the run ends, the exception refetches so `investigation` arrives from
 * the API, which is where every figure on screen comes from.
 */
export function useInvestigationRun(exceptionId: string): InvestigationRun {
  const [events, setEvents] = useState<InvestigationEvent[]>([]);
  const [streamState, setState] = useState<RunState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState(-1);
  const abortRef = useRef<AbortController | null>(null);
  const qc = useQueryClient();
  const reduce = useReducedMotion();

  const start = useCallback(() => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setEvents([]);
    setError(null);
    setShown(-1);
    setState("running");
    let failed: string | null = null;
    investigate(
      exceptionId,
      (ev) => {
        if (ev.stage === "error") {
          failed = ev.message;
          return;
        }
        setEvents((prev) => [...prev, ev]);
        // the remeasured balances are recorded on the item; fetch them as soon as they exist
        if (ev.stage === "remeasured" || ev.stage === "complete") void qc.invalidateQueries({ queryKey: ["exception", exceptionId] });
      },
      ctrl.signal,
    )
      .then(() => {
        if (ctrl.signal.aborted) return;
        if (failed) {
          setError(failed);
          setState("error");
        } else {
          setState("done");
        }
        for (const k of ["exception", "audit", "allowed-actions", "item-sources"]) void qc.invalidateQueries({ queryKey: [k] });
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setError(e instanceof Error ? e.message : String(e));
        setState("error");
      });
  }, [exceptionId, qc]);

  useEffect(() => () => abortRef.current?.abort(), []);
  // a different exception is a different story
  useEffect(() => {
    abortRef.current?.abort();
    setEvents([]);
    setError(null);
    setShown(-1);
    setState("idle");
  }, [exceptionId]);

  // advance what is shown one beat at a time, never past what has arrived
  const arrived = events.reduce((m, e) => Math.max(m, stageIndex(e)), -1);
  useEffect(() => {
    if (shown >= arrived) return;
    const wait = shown < 0 ? 0 : reduce ? DWELL_REDUCED_MS : DWELL_MS[ORDER[shown]];
    const t = setTimeout(() => setShown((v) => v + 1), wait);
    return () => clearTimeout(t);
  }, [shown, arrived, reduce]);

  const visible = events.filter((e) => stageIndex(e) <= shown);
  const byStage = new Map(visible.map((e) => [e.stage, e]));
  const stage: Stage | null = shown >= 0 ? ORDER[Math.min(shown, ORDER.length - 1)] : null;
  // the run reads as finished only once the last beat it received has been shown
  const state: RunState = streamState !== "running" && shown < arrived ? "running" : streamState;

  return {
    state,
    events: visible,
    error: state === "error" ? error : null,
    stage,
    get: ((s: string) => byStage.get(s as InvestigationEvent["stage"])) as InvestigationRun["get"],
    start,
  };
}

/** The phase the screen shows: a live run wins; otherwise what is on record. */
export function phaseOf(run: InvestigationRun, investigated: boolean): Phase {
  // a run that stopped (refused, or the stream broke) leaves what is on record, not a mailbox still searching
  if (run.state === "idle" || run.state === "error") return investigated ? "settled" : "ready";
  return run.stage ?? "searching";
}

/** True once the story has reached (or passed) `s`, or the result is simply on record. */
export function reached(phase: Phase, s: Stage): boolean {
  if (phase === "settled") return true;
  if (phase === "ready") return false;
  return ORDER.indexOf(phase) >= ORDER.indexOf(s);
}
