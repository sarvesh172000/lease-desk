"use client";

import { afterCrack } from "@/lib/chain";
import type { AuditEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useReducedMotion } from "framer-motion";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

export interface StripProps {
  /** Oldest first, as the chain was built. */
  events: AuditEvent[];
  selectedSeq: number | null;
  onSelect: (seq: number) => void;
  /** Where the chain cracks on screen (the API's break, or a simulation). */
  crackSeq: number | null;
  /** True when the crack is a client-side simulation; drawn with its label. */
  simulated: boolean;
  /** The rows the current filters keep; others fade. */
  visible: Set<number> | null;
}

const Strip3D = dynamic(() => import("./ChainStrip3D"), { ssr: false, loading: () => null });

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

/**
 * Every block of the chain in one strip, oldest to newest: teal when sealed,
 * red when a refused attempt (still in the chain), red and hollow past a
 * crack. Selecting a row glides the strip to its block. 3D when WebGL is
 * there and motion is allowed; the flat strip otherwise, and as the fallback.
 */
export function ChainStrip(props: StripProps) {
  const reduce = useReducedMotion();
  const [gl, setGl] = useState<boolean | null>(null);
  useEffect(() => setGl(webglAvailable()), []);
  const use3D = !reduce && gl === true;
  // when a simulated crack is switched on, the strip plays it from that block outward
  const [crackStartedAt, setCrackStartedAt] = useState<number | null>(null);
  useEffect(() => {
    setCrackStartedAt(props.simulated && props.crackSeq != null ? performance.now() : null);
  }, [props.simulated, props.crackSeq]);

  return (
    <div className="relative h-[200px] overflow-hidden rounded-md border border-line bg-surface" data-testid="chain-strip" data-mode={use3D ? "3d" : "2d"} data-crack={props.crackSeq ?? undefined}>
      {use3D ? <Strip3D {...props} crackStartedAt={crackStartedAt} /> : <Strip2D {...props} />}
      {props.simulated ? (
        <span className="absolute left-3 top-3 rounded-xs border border-warn-line bg-warn-soft px-2 py-0.5 text-2xs font-semibold uppercase tracking-wide text-warn" data-testid="simulation-label">
          Simulation · nothing is changed
        </span>
      ) : null}
      <Legend crack={props.crackSeq != null} />
    </div>
  );
}

function Legend({ crack }: { crack: boolean }) {
  return (
    <div className="pointer-events-none absolute inset-x-3 bottom-2 flex items-center gap-4 text-2xs text-ink-muted">
      <span className="flex items-center gap-1.5">
        <span aria-hidden className="h-2.5 w-1.5 rounded-[1px] bg-accent" /> sealed
      </span>
      <span className="flex items-center gap-1.5">
        <span aria-hidden className="h-2.5 w-1.5 rounded-[1px] bg-bad" /> refused attempt, still in the chain
      </span>
      {crack ? (
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="h-2.5 w-1.5 rounded-[1px] border border-dashed border-bad" /> unverifiable after the break
        </span>
      ) : null}
      <span className="ml-auto">oldest → newest · click a block to select it</span>
    </div>
  );
}

const short = (h?: string | null) => (h ? `${h.slice(0, 6)}…${h.slice(-4)}` : "—");

/**
 * The flat strip: an SVG with one tick per event, a window of blocks around
 * the selection so thousands of events still read, and the link between the
 * selected block and the one before it written out.
 */
export function Strip2D({ events, selectedSeq, onSelect, crackSeq, visible }: StripProps) {
  const ref = useRef<HTMLDivElement>(null);
  const selIdx = selectedSeq == null ? events.length - 1 : events.findIndex((e) => e.seq === selectedSeq);
  const SLOT = 14;
  const W = Math.max(events.length * SLOT, 10);
  const crackIdx = useMemo(() => (crackSeq == null ? -1 : events.findIndex((e) => e.seq >= crackSeq)), [events, crackSeq]);
  useEffect(() => {
    const el = ref.current;
    if (!el || selIdx < 0) return;
    el.scrollTo?.({ left: Math.max(0, selIdx * SLOT - el.clientWidth / 2), behavior: "auto" });
  }, [selIdx]);
  const sel = events[selIdx];
  const prev = selIdx > 0 ? events[selIdx - 1] : undefined;

  return (
    <div className="absolute inset-x-0 top-0 h-[164px]">
      <div ref={ref} className="h-[120px] overflow-x-auto overflow-y-hidden px-3 pt-3">
        <svg width={W} height={100} role="img" aria-label={`${events.length} events, oldest to newest`} className="block">
          <line x1="0" y1="60" x2={W} y2="60" stroke="rgb(var(--line-strong))" strokeWidth="1" />
          {events.map((e, i) => {
            const after = afterCrack(e.seq, crackSeq);
            const dim = visible && !visible.has(e.seq);
            const isSel = i === selIdx;
            const fill = !e.allowed ? "rgb(var(--bad))" : after ? "rgb(var(--bad) / 0.25)" : "rgb(var(--accent))";
            return (
              <g key={e.seq} opacity={dim ? 0.18 : 1} className="cursor-pointer" onClick={() => onSelect(e.seq)}>
                <rect
                  x={i * SLOT + 3}
                  y={isSel ? 16 : 32}
                  width={SLOT - 6}
                  height={isSel ? 72 : 48}
                  rx="1.5"
                  fill={fill}
                  stroke={after && e.allowed ? "rgb(var(--bad))" : isSel ? "rgb(var(--ink))" : "none"}
                  strokeWidth={isSel ? 1.5 : 1}
                  strokeDasharray={after && e.allowed ? "3 2" : undefined}
                >
                  <title>{`#${e.seq} · ${e.actor_name ?? e.actor_id} · ${e.action}${e.allowed ? "" : " · refused"}`}</title>
                </rect>
              </g>
            );
          })}
          {crackIdx >= 0 ? <path d={`M ${crackIdx * SLOT - 1} 10 l 6 18 l -8 14 l 8 16 l -6 20 l 7 14`} fill="none" stroke="rgb(var(--bad))" strokeWidth="2" /> : null}
        </svg>
      </div>
      {sel ? (
        <div className="mx-3 mt-1 flex items-center gap-3 font-mono text-2xs text-ink-muted">
          <span>
            <span className="text-ink-muted">#{sel.seq}</span> <span className="text-ink">{sel.actor_name ?? sel.actor_id}</span> · {sel.action}
            {!sel.allowed ? <span className="ml-1.5 font-semibold text-bad">REFUSED</span> : null}
          </span>
          {prev ? (
            <span className="ml-auto">
              #{prev.seq} hash <span className="text-ink">{short(prev.hash)}</span> → #{sel.seq} prev_hash{" "}
              <span className={sel.prev_hash === prev.hash ? "text-ok" : "text-bad"}>{short(sel.prev_hash)}</span>
            </span>
          ) : (
            <span className="ml-auto">prev_hash = 64 zeros · the first link</span>
          )}
        </div>
      ) : null}
    </div>
  );
}

export const stripClass = cn;
