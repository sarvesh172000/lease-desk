import { cn } from "@/lib/utils";

/** The eight work states (backend/app/work/transitions.py), styled to sit next to StatusBadge. */
const STYLE: Record<string, string> = {
  NEW: "bg-bad-soft text-bad border-bad-line",
  PROPOSED: "bg-warn-soft text-warn border-warn-line",
  NEEDS_INFO: "bg-esc-soft text-esc border-esc-line",
  HELD: "bg-esc-soft text-esc border-esc-line",
  APPROVED: "bg-ok-soft text-ok border-ok-line",
  POSTED: "bg-ok text-white border-ok",
  REJECTED: "bg-sunken text-ink-muted border-line",
  CLOSED: "bg-sunken text-ink-muted border-line",
};

const LABEL: Record<string, string> = {
  NEW: "New",
  PROPOSED: "Proposed",
  NEEDS_INFO: "Needs info",
  HELD: "Held",
  APPROVED: "Approved",
  POSTED: "Posted",
  REJECTED: "Rejected",
  CLOSED: "Closed",
};

export function WorkStateBadge({ state, className }: { state: string | null | undefined; className?: string }) {
  const s = state ?? "";
  return (
    <span
      data-state={s}
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded border px-1.5 py-px font-mono text-2xs font-semibold uppercase tracking-wide",
        STYLE[s] ?? "border-line bg-sunken text-ink-muted",
        className,
      )}
    >
      {LABEL[s] ?? (s || "—")}
    </span>
  );
}
