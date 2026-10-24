import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-md border border-line bg-surface shadow-raised",
        "transition-colors duration-base ease-out",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({
  title, eyebrow, actions, right, className,
}: {
  title: ReactNode;
  eyebrow?: ReactNode;
  /** Existing name, kept so no caller has to change. */
  actions?: ReactNode;
  /** Alias for `actions`. */
  right?: ReactNode;
  className?: string;
}) {
  const trailing = actions ?? right;
  return (
    <div className={cn("flex items-start justify-between gap-4 border-b border-line px-5 py-3", className)}>
      <div className="min-w-0">
        {eyebrow ? <div className="eyebrow mb-0.5">{eyebrow}</div> : null}
        <h2 className="truncate text-[0.95rem] font-semibold tracking-tight">{title}</h2>
      </div>
      {trailing ? <div className="flex shrink-0 items-center gap-2">{trailing}</div> : null}
    </div>
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 py-4", className)} {...props} />;
}
