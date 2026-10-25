"use client";

import type { ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { pageImageUrl } from "@/lib/api";
import { boxToPercent } from "@/lib/bbox";
import { useDocumentPages } from "@/lib/hooks";
import type { Box, DocumentPages } from "@/lib/types";
import type { FanState } from "@/lib/welcome";
import { cn } from "@/lib/utils";

/**
 * The three documents of the amendment case, fanned in space: the lease at
 * the back, the invoice in the middle, the amendment in front. Each is the
 * API's own page render with the API's own box on it. Beat 1 scrolls the fan
 * through four states; the pages move, the boxes never do.
 *
 * CSS 3D, not WebGL: it works on any GPU, offline, and in a screenshot.
 */
export type FanPage = {
  key: "lease" | "invoice" | "email";
  docId: string;
  page: number | null;
  box: Box | null;
  tone: "lease" | "billed" | "found";
  tag: string;
  alt: string;
  /** Shown as words when the document has no page to draw (a live email body). */
  quote?: string;
  from?: string;
};

export type PageSource = { src: (docId: string, page: number) => string; sizes: Record<string, DocumentPages> } | null;

type Pose = { x: number; y: number; z: number; ry: number; rx?: number; s?: number; o?: number };

// where each page sits in each state, in px of a 520×560 stage
const POSES: Record<FanState, Record<FanPage["key"], Pose>> = {
  rest: {
    lease: { x: 24, y: 72, z: -220, ry: 34, rx: 4, o: 0.92 },
    invoice: { x: 118, y: 118, z: -90, ry: 22, rx: 3 },
    email: { x: 214, y: 166, z: 40, ry: 8, rx: 2 },
  },
  invoice: {
    lease: { x: 0, y: 60, z: -320, ry: 38, o: 0.55 },
    invoice: { x: 150, y: 60, z: 120, ry: -2, s: 1.22 },
    email: { x: 330, y: 150, z: -60, ry: -24, o: 0.6 },
  },
  email: {
    lease: { x: 0, y: 70, z: -320, ry: 38, o: 0.5 },
    invoice: { x: 70, y: 100, z: -200, ry: 26, o: 0.65 },
    email: { x: 200, y: 50, z: 120, ry: -4, s: 1.28 },
  },
  figure: {
    lease: { x: -10, y: 90, z: -360, ry: 40, o: 0.45 },
    invoice: { x: 60, y: 110, z: -240, ry: 28, o: 0.55 },
    email: { x: 150, y: 90, z: -80, ry: 10, o: 0.8 },
  },
};

const TONE = {
  lease: { box: "border-warn bg-warn/10", tag: "bg-warn text-accent-ink" },
  billed: { box: "border-bad bg-bad/10", tag: "bg-bad text-accent-ink" },
  found: { box: "border-accent bg-accent/10", tag: "bg-accent text-accent-ink" },
} as const;

export function DocumentFan({
  pages, state, source, figure, className,
}: {
  pages: FanPage[];
  state: FanState;
  source: PageSource;
  /** Shown in front of the receded fan in the "figure" state: the remeasured liability. */
  figure?: ReactNode;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const forward = state === "invoice" ? "invoice" : state === "email" ? "email" : null;
  return (
    <div className={cn("relative mx-auto h-[560px] w-[520px] max-w-full", className)} style={{ perspective: 1400, perspectiveOrigin: "42% 45%" }} data-testid="document-fan" data-state={state}>
      <div className="absolute inset-0" style={{ transformStyle: "preserve-3d" }}>
        {pages.map((p) => {
          const pose = POSES[state][p.key];
          return (
            <motion.div
              key={p.key}
              className="absolute left-0 top-0 w-[280px]"
              style={{ transformStyle: "preserve-3d" }}
              initial={false}
              animate={{ x: pose.x, y: pose.y, z: pose.z, rotateY: pose.ry, rotateX: pose.rx ?? 0, scale: pose.s ?? 1, opacity: pose.o ?? 1 }}
              transition={reduce ? { duration: 0 } : { duration: 0.7, ease: [0.2, 0.8, 0.2, 1] }}
            >
              <PageCard page={p} source={source} lifted={forward === p.key} />
            </motion.div>
          );
        })}
        {figure ? (
          <motion.div
            className="absolute left-[300px] top-[150px] w-[220px]"
            initial={false}
            animate={state === "figure" ? { opacity: 1, z: 140, y: 150 } : { opacity: 0, z: -40, y: 190 }}
            transition={reduce ? { duration: 0 } : { duration: 0.6, delay: state === "figure" ? 0.25 : 0, ease: [0.2, 0.8, 0.2, 1] }}
            style={{ pointerEvents: state === "figure" ? "auto" : "none" }}
            aria-hidden={state !== "figure"}
          >
            {figure}
          </motion.div>
        ) : null}
      </div>
    </div>
  );
}

/** One page of the fan: the render with its box, or the words when there is no page. */
function PageCard({ page, source, lifted }: { page: FanPage; source: PageSource; lifted: boolean }) {
  const fromApi = useDocumentPages(page.page && !source ? page.docId : null);
  const size = (source ? source.sizes[page.docId]?.pages : fromApi.data?.pages)?.find((s) => s.page === page.page) ?? null;
  const rect = page.box && size ? boxToPercent(page.box, size) : null;
  const ratio = size ? size.height / size.width : 1.2941;
  const tone = TONE[page.tone];
  return (
    <figure
      className={cn(
        "relative m-0 overflow-hidden rounded-sm border border-line bg-white shadow-[0_30px_50px_-24px_rgb(var(--shadow)/0.45),0_2px_6px_rgb(var(--shadow)/0.12)]",
        lifted && "shadow-[0_50px_90px_-30px_rgb(var(--shadow)/0.6),0_0_0_3px_rgb(var(--accent)/0.12)]",
      )}
      style={{ aspectRatio: `1 / ${ratio}` }}
    >
      {page.page ? (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={source ? source.src(page.docId, page.page) : pageImageUrl(page.docId, page.page)} alt={page.alt} className="absolute left-0 top-0 w-full" />
          {rect ? (
            <span
              aria-hidden
              data-testid="fan-box"
              className={cn("absolute rounded-[2px] border-2", tone.box, lifted && "border-[3px] shadow-[0_0_0_6px_rgb(var(--accent)/0.10)]")}
              style={{ left: `${rect.left}%`, top: `${rect.top}%`, width: `${rect.width}%`, height: `${rect.height}%` }}
            />
          ) : null}
        </>
      ) : (
        <div className="absolute inset-0 p-4 text-[10px] leading-snug text-ink">
          <div className="font-mono text-[9px] text-ink-muted">From: {page.from ?? "—"}</div>
          <div className="mt-3 border-l-2 border-accent bg-accent/10 px-2 py-1 text-[11px]">{page.quote}</div>
          <div className="mt-3 text-[9px] text-ink-muted">The mailbox keeps this message as text; the sentence is shown as written.</div>
        </div>
      )}
      <figcaption className={cn("absolute bottom-2.5 left-2.5 rounded px-2 py-0.5 font-mono text-[10px] tracking-[0.06em]", tone.tag)}>{page.tag}</figcaption>
    </figure>
  );
}
