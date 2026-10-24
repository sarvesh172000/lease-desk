import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type Tone = "neutral" | "ok" | "bad" | "warn" | "esc" | "accent";

const TONE: Record<Tone, string> = {
  neutral: "border-line bg-raised text-ink-soft",
  ok: "border-ok-line bg-ok-soft text-ok",
  bad: "border-bad-line bg-bad-soft text-bad",
  warn: "border-warn-line bg-warn-soft text-warn",
  esc: "border-esc-line bg-esc-soft text-esc",
  accent: "border-accent/40 bg-accent-soft text-accent",
};

export function Badge({
  tone = "neutral", dot, children, className,
}: {
  tone?: Tone;
  dot?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1",
        "text-2xs font-medium leading-none whitespace-nowrap",
        TONE[tone],
        className,
      )}
    >
      {dot ? <span className={cn("h-1.5 w-1.5 rounded-full bg-current", tone === "warn" && "animate-pulse-dot")} /> : null}
      {children}
    </span>
  );
}
