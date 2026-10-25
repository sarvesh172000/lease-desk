"use client";

import { motion, useReducedMotion } from "framer-motion";
import { useEffect, useState, type RefObject } from "react";

interface Line {
  d: string;
  a: [number, number];
  b: [number, number];
}

/** A box's anchor, kept inside its own scrolling viewer so the line never points off-page. */
function anchor(el: Element, root: DOMRect, side: "left" | "right"): [number, number] | null {
  const r = el.getBoundingClientRect();
  const viewer = el.closest("[data-viewer]")?.getBoundingClientRect();
  if (!viewer || r.bottom < viewer.top || r.top > viewer.bottom) return null;
  const y = Math.min(Math.max(r.top + r.height / 2, viewer.top + 8), viewer.bottom - 8);
  const x = side === "right" ? Math.min(r.right, viewer.right) : Math.max(r.left, viewer.left);
  return [x - root.left, y - root.top];
}

/**
 * A quiet line from the billed line on the invoice to the clause it is judged
 * against, so the eye travels between the two documents the way a reviewer's
 * would. Purely visual: it follows the boxes the viewers drew and hides when
 * either is scrolled away.
 */
export function BoxConnector({ root }: { root: RefObject<HTMLElement | null> }) {
  const reduce = useReducedMotion();
  const [line, setLine] = useState<Line | null>(null);

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    let raf = 0;
    const measure = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const rr = el.getBoundingClientRect();
        const billed = el.querySelector('[data-testid="citation-box"][data-tone="billed"]');
        const cited = el.querySelector('[data-testid="citation-box"][data-tone="cited"]');
        const a = billed ? anchor(billed, rr, "right") : null;
        const b = cited ? anchor(cited, rr, "left") : null;
        if (!a || !b) return setLine(null);
        const mid = (a[0] + b[0]) / 2;
        setLine({ d: `M ${a[0]} ${a[1]} C ${mid} ${a[1]}, ${mid} ${b[1]}, ${b[0]} ${b[1]}`, a, b });
      });
    };
    measure();
    const mo = new MutationObserver(measure);
    mo.observe(el, { subtree: true, childList: true, attributes: true, attributeFilter: ["style", "src"] });
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    el.addEventListener("scroll", measure, true);
    el.addEventListener("load", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      cancelAnimationFrame(raf);
      mo.disconnect();
      ro.disconnect();
      el.removeEventListener("scroll", measure, true);
      el.removeEventListener("load", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [root]);

  if (!line) return null;
  return (
    <svg aria-hidden className="pointer-events-none absolute inset-0 z-10 h-full w-full overflow-visible text-accent" data-testid="box-connector">
      <motion.path
        d={line.d}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeDasharray="4 4"
        strokeOpacity="0.7"
        initial={reduce ? false : { pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.8, delay: 0.6, ease: [0.2, 0.8, 0.2, 1] }}
      />
      <circle cx={line.a[0]} cy={line.a[1]} r="3.5" className="fill-bad" />
      <circle cx={line.b[0]} cy={line.b[1]} r="3.5" className="fill-warn" />
    </svg>
  );
}
