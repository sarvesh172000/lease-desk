import { cn } from "@/lib/utils";
import type { ReactNode } from "react";
import { Button } from "./Button";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-sunken", className)} aria-hidden />;
}

/** Placeholder rows shaped like the content they stand in for. */
export function LoadingBlock({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-3 py-1">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4">
          <Skeleton className="h-4 w-1/4" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-24" />
        </div>
      ))}
      <span className="sr-only">{label}…</span>
    </div>
  );
}

export function ErrorState({
  title = "Could not load this",
  error,
  onRetry,
  className,
}: {
  title?: string;
  error?: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const message = error instanceof Error ? error.message : error ? String(error) : null;
  return (
    <div role="alert" className={cn("rounded-md border border-bad-line bg-bad-soft/60 px-4 py-3", className)}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-semibold text-bad">{title}</p>
          {message ? <p className="mt-0.5 font-mono text-sm text-ink-soft">{message}</p> : null}
        </div>
        {onRetry ? (
          <Button size="sm" variant="secondary" onClick={onRetry}>
            Retry
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function EmptyState({ title, children, className }: { title: string; children?: ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-md border border-dashed border-line-strong px-5 py-8 text-center", className)}>
      <p className="font-medium text-ink-soft">{title}</p>
      {children ? <div className="mt-1 text-sm text-ink-muted">{children}</div> : null}
    </div>
  );
}
