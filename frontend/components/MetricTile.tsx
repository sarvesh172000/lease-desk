import { cn } from "@/lib/utils";
import type { ReactNode } from "react";
import { Skeleton } from "./ui/States";

export function MetricTile({
  label,
  value,
  sub,
  tone = "neutral",
  loading,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "neutral" | "bad" | "warn" | "ok";
  loading?: boolean;
}) {
  return (
    <div className="relative overflow-hidden rounded-md border border-line bg-surface px-5 py-4 shadow-card">
      <span
        aria-hidden
        className={cn(
          "absolute inset-y-0 left-0 w-1",
          tone === "bad" && "bg-bad",
          tone === "warn" && "bg-warn",
          tone === "ok" && "bg-ok",
          tone === "neutral" && "bg-accent",
        )}
      />
      <div className="eyebrow">{label}</div>
      <div className="num mt-1.5 text-[2rem] font-semibold leading-none tracking-tight">
        {loading ? <Skeleton className="h-8 w-28" /> : value}
      </div>
      {sub ? <div className="mt-2 text-sm text-ink-muted">{sub}</div> : null}
    </div>
  );
}
