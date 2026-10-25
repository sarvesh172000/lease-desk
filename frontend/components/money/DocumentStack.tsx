"use client";

import { cn } from "@/lib/utils";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

export interface StackProps {
  /** searching: the stack fans out; found: the explaining document lifts out. */
  mode: "searching" | "found";
  /** How many documents the agent says it is searching (from the stream's message). */
  total: number | null;
  /** The found document's source, e.g. the sender. */
  foundLabel?: string | null;
  /** Called once the found document has landed, so the viewer can swap to it. */
  onLanded?: () => void;
}

/** Cards drawn: enough to read as a mailbox, few enough to stay calm. */
export const CARD_KINDS = ["Invoice", "Lease page", "Email", "Invoice", "Email", "Lease page", "Email", "Invoice", "Email", "Lease page", "Email"];
export const FOUND_INDEX = 6;

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

  // reduced motion and the 2D stack land on a timer; the 3D one reports itself
  const use3D = !reduce && gl === true;
  useEffect(() => {
    if (mode !== "found" || use3D) return;
    const t = setTimeout(() => onLanded?.(), reduce ? 300 : 1100);
    return () => clearTimeout(t);
  }, [mode, use3D, reduce, onLanded]);

  return (
    <div className="relative h-full overflow-hidden bg-sunken" data-testid="document-stack" data-mode={mode}>
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
                {props.total != null ? <span className="num font-semibold text-ink">{props.total.toLocaleString("en-US")}</span> : "the"} documents…
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

function Stack2D({ mode, foundLabel, reduce }: StackProps & { reduce: boolean }) {
  const n = CARD_KINDS.length;
  return (
    <div className="absolute inset-0 flex items-center justify-center [perspective:1000px]">
      {CARD_KINDS.map((kind, i) => {
        const found = i === FOUND_INDEX;
        const spread = (i - (n - 1) / 2) * 26;
        const fanned = { x: spread, y: Math.abs(spread) * 0.18, rotate: spread / 6, opacity: 1, scale: 1 };
        const target =
          mode === "found"
            ? found
              ? { x: 0, y: -18, rotate: 0, opacity: 1, scale: 1.18, zIndex: 50 }
              : { ...fanned, opacity: 0.18, scale: 0.94 }
            : fanned;
        return (
          <motion.div
            key={i}
            initial={reduce ? { opacity: 0 } : { x: 0, y: 0, rotate: 0, opacity: 0 }}
            animate={reduce ? { opacity: mode === "found" && !found ? 0.18 : 1 } : target}
            transition={{ duration: reduce ? 0.3 : 0.6, delay: reduce ? 0 : mode === "searching" ? i * 0.04 : 0, ease: [0.2, 0.8, 0.2, 1] }}
            style={{ zIndex: found && mode === "found" ? 50 : i }}
            className={cn(
              "absolute h-40 w-28 rounded-xs border bg-surface p-2 shadow-float",
              found && mode === "found" ? "border-accent ring-2 ring-accent/40" : "border-line",
            )}
          >
            <div className="eyebrow truncate">{kind}</div>
            <div className="mt-2 space-y-1.5">
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
