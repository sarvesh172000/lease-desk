"use client";

import { useEffect, useRef, useState } from "react";
import { useInView } from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * A figure that counts up once, when it comes into view.
 *
 * Tabular by default so the width never changes while it runs — a number that
 * reflows mid-count reads as a glitch, and on this page the number is the
 * entire argument.
 */
export function CountUp({
  value, from = 0, prefix = "", suffix = "", decimals = 2, duration = 1100, className,
}: {
  value: number;
  /** Where the count starts (a before figure); it always ends on `value` exactly. */
  from?: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  duration?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });
  const [shown, setShown] = useState(from);

  useEffect(() => {
    if (!inView) return;

    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setShown(value);
      return;
    }

    let raf = 0;
    const started = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / duration);
      // Ease out: fast at first, settling into the final figure.
      // the last frame is the API's figure itself, never an interpolation of it
      setShown(t < 1 ? from + (value - from) * (1 - Math.pow(1 - t, 3)) : value);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [inView, value, from, duration]);

  return (
    <span ref={ref} className={cn("num tabular-nums", className)}>
      {prefix}
      {shown.toLocaleString("en-US", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}
      {suffix}
    </span>
  );
}
