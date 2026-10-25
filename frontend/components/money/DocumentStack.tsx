"use client";

import { cn } from "@/lib/utils";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

export interface StackProps {
  /** searching: the stack fans out; found: the explaining document lifts out; none: nothing did, the cards settle. */
  mode: "searching" | "found" | "none";
  /** How many documents the agent says it is searching (from the stream's message). */
  total: number | null;
  /** The found document's source, e.g. the sender. */
  foundLabel?: string | null;
  /** Called once the found document has landed, so the viewer can swap to it. */
  onLanded?: () => void;
  /** The case's own page renders, by card kind, to texture the cards; a kind without one is drawn. */
  textures?: Partial<Record<CardKind, string>>;
}

export type CardKind = "Invoice" | "Lease page" | "Email";

/** Cards drawn: enough to read as a mailbox, few enough to stay calm. */
export const CARD_KINDS: CardKind[] = ["Invoice", "Lease page", "Email", "Invoice", "Email", "Lease page", "Email", "Invoice", "Email", "Lease page", "Email"];
export const FOUND_INDEX = 6;
/** Each card with a stable id, for React keys (a kind repeats, so it can't be the key). */
export const CARDS = CARD_KINDS.map((kind, n) => ({ kind, id: `card-${n}` }));

const Stack3D = dynamic(() => import("./DocumentStack3D"), { ssr: false, loading: () => null });

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

/** "Searching 1,284 documents…" → 1284. Only the stream's own number, never a guess. */
export function totalFromMessage(message: string | null | undefined): number | null {
  const m = message?.match(/(\d[\d,]*)\s+(?:documents?|emails?|messages?|files?)/i);
  return m ? Number(m[1].replace(/,/g, "")) : null;
}

/**
 * The agent searching the mailbox, as a stack of documents. 3D when WebGL and
 * motion are available (lazy-loaded, never blocking the page); a flat stack
 * otherwise, and only fades under reduced motion.
 */
export function DocumentStack(props: StackProps) {
  const reduce = useReducedMotion();
  const [gl, setGl] = useState<boolean | null>(null);
  useEffect(() => setGl(webglAvailable()), []);
  const { onLanded, mode } = props;

  // reduced motion and the 2D stack land on a timer; the 3D one reports itself.
  // Nothing found: the finding holds the stage a moment, then the lease clause returns.
  const use3D = !reduce && gl === true;
  useEffect(() => {
    if (mode === "searching" || (mode === "found" && use3D)) return;
    const t = setTimeout(() => onLanded?.(), reduce ? 300 : mode === "none" ? 1800 : 1100);
    return () => clearTimeout(t);
  }, [mode, use3D, reduce, onLanded]);

  return (
    <div className="relative h-full overflow-hidden bg-stage" data-testid="document-stack" data-mode={mode}>
      {use3D ? <Stack3D {...props} /> : <Stack2D {...props} reduce={!!reduce} />}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 p-4">
        <AnimatePresence mode="wait">
          <motion.div
            key={mode}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="mx-auto w-fit rounded-sm border border-line bg-surface/90 px-3 py-1.5 text-sm text-ink-soft shadow-raised backdrop-blur"
          >
            {mode === "searching" ? (
              <>
                Searching{" "}
                {props.total != null ? <Ticker total={props.total} reduce={!!reduce} /> : "the"} documents…
              </>
            ) : mode === "none" ? (
              <>
                <span className="font-semibold text-ink">No document changes the lease.</span> The charge is unsupported; the hold stands.
              </>
            ) : (
              <>
                Found: <span className="font-semibold text-ink">{props.foundLabel ?? "the explaining document"}</span>
              </>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

/** The document count ticking up over the search, ending on the stream's own number. Not viewport-triggered: the pane is where it is. */
function Ticker({ total, reduce }: { total: number; reduce: boolean }) {
  const [shown, setShown] = useState(reduce ? total : 0);
  useEffect(() => {
    if (reduce) return setShown(total);
    let raf = 0;
    const started = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / 2400);
      setShown(t < 1 ? Math.round(total * (1 - Math.pow(1 - t, 3))) : total);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [total, reduce]);
  return <span className="num font-semibold text-ink">{shown.toLocaleString("en-US")}</span>;
}

function Stack2D({ mode, foundLabel, reduce, textures }: StackProps & { reduce: boolean }) {
  const n = CARD_KINDS.length;
  return (
    <div className="absolute inset-0 flex items-center justify-center [perspective:1000px]">
      {CARDS.map(({ kind, id }, i) => {
        const found = i === FOUND_INDEX;
        const spread = (i - (n - 1) / 2) * 26;
        const fanned = { x: spread, y: Math.abs(spread) * 0.18, rotate: spread / 6, opacity: 1, scale: 1 };
        const target =
          mode === "found"
            ? found
              ? { x: 0, y: -18, rotate: 0, opacity: 1, scale: 1.18, zIndex: 50 }
              : { ...fanned, opacity: 0.18, scale: 0.94 }
            : mode === "none"
              ? { ...fanned, x: spread * 1.6, opacity: 0.3, scale: 0.9 }
              : fanned;
        return (
          <motion.div
            key={id}
            initial={reduce ? { opacity: 0 } : { x: 0, y: 0, rotate: 0, opacity: 0 }}
            animate={reduce ? { opacity: mode === "found" && !found ? 0.18 : mode === "none" ? 0.3 : 1 } : target}
            transition={{ duration: reduce ? 0.3 : 0.6, delay: reduce ? 0 : mode === "searching" ? i * 0.04 : 0, ease: [0.2, 0.8, 0.2, 1] }}
            style={{ zIndex: found && mode === "found" ? 50 : i }}
            className={cn(
              "absolute h-40 w-28 overflow-hidden rounded-xs border bg-surface p-2 shadow-float",
              found && mode === "found" ? "border-accent ring-2 ring-accent/40" : "border-line",
            )}
          >
            {textures?.[kind] ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={textures[kind]} alt="" className="pointer-events-none absolute inset-0 h-full w-full object-cover object-top" />
            ) : null}
            <div className="eyebrow relative truncate">{kind}</div>
            <div className="relative mt-2 space-y-1.5">
              <div className="h-1.5 w-full rounded bg-line" />
              <div className="h-1.5 w-4/5 rounded bg-line" />
              <div className={cn("h-1.5 w-11/12 rounded", found && mode === "found" ? "bg-warn" : "bg-line")} />
              <div className="h-1.5 w-3/5 rounded bg-line" />
            </div>
            {found && mode === "found" && foundLabel ? <div className="mt-3 line-clamp-3 break-all text-2xs text-ink-soft">{foundLabel}</div> : null}
          </motion.div>
        );
      })}
    </div>
  );
}
