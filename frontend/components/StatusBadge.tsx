import { STATUS_LABEL } from "@/lib/format";
import type { Status } from "@/lib/types";
import { cn } from "@/lib/utils";

const STYLE: Record<Status, string> = {
  balanced: "bg-ok-soft text-ok border-ok-line",
  exception: "bg-bad-soft text-bad border-bad-line",
  pending_review: "bg-warn-soft text-warn border-warn-line",
  escalated: "bg-esc-soft text-esc border-esc-line",
};

/** Shape as well as colour, so status survives a washed-out projector or colour blindness. */
const GLYPH: Record<Status, string> = {
  balanced: "✓",
  exception: "!",
  pending_review: "◷",
  escalated: "↑",
};

export function StatusBadge({ status, size = "md", className }: { status: Status | string; size?: "sm" | "md" | "lg"; className?: string }) {
  const known = (status in STYLE ? status : null) as Status | null;
  const label = known ? STATUS_LABEL[known] : String(status || "unknown");
  return (
    <span
      data-status={status}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded border font-medium",
        size === "sm" && "px-1.5 py-px text-2xs",
        size === "md" && "px-2 py-0.5 text-xs",
        size === "lg" && "px-2.5 py-1 text-sm",
        known ? STYLE[known] : "border-line bg-sunken text-ink-muted",
        className,
      )}
    >
      <span aria-hidden className="font-semibold leading-none">
        {known ? GLYPH[known] : "?"}
      </span>
      {label}
    </span>
  );
}
