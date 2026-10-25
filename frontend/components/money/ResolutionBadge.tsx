import { money } from "@/lib/format";
import type { ExceptionDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CircleCheck, CircleDollarSign, CircleSlash, Lock } from "lucide-react";

/** The API's own account of a decided item, in one chip; null while it is still open. */
export function resolutionOf(ex: ExceptionDetail): { label: string; tone: "ok" | "esc" | "muted"; icon: "lock" | "check" | "paid" | "closed" } | null {
  const state = ex.state?.toUpperCase();
  if (ex.resolution === "pay_as_billed") return { label: "Paid as billed", tone: "esc", icon: "paid" };
  if (ex.resolution === "upheld") {
    const held = ex.disputed ?? ex.delta;
    return { label: `Hold upheld${held ? ` · ${money(Math.abs(held))} held` : ""}`, tone: "ok", icon: "lock" };
  }
  if (state === "POSTED") return { label: "Approved · posted", tone: "ok", icon: "check" };
  if (state === "APPROVED") return { label: "Approved", tone: "ok", icon: "check" };
  if (state === "REJECTED") return { label: "Rejected", tone: "muted", icon: "closed" };
  if (state === "CLOSED") return { label: "Closed", tone: "muted", icon: "closed" };
  return null;
}

const TONE = {
  ok: "border-ok-line bg-ok-soft text-ok",
  esc: "border-esc-line bg-esc-soft text-esc",
  muted: "border-line bg-sunken text-ink-soft",
};
const ICON = { lock: Lock, check: CircleCheck, paid: CircleDollarSign, closed: CircleSlash };

/**
 * For a decided item, the decision is the status: "Hold upheld · $4,820.00
 * held" next to a red variance says what happened, where a green "Balanced"
 * would contradict it.
 */
export function ResolutionBadge({ ex, size = "md" }: { ex: ExceptionDetail; size?: "sm" | "md" }) {
  const r = resolutionOf(ex);
  if (!r) return null;
  const Icon = ICON[r.icon];
  return (
    <span
      data-testid="resolution-badge"
      className={cn("inline-flex items-center gap-1.5 rounded-full border font-medium", TONE[r.tone], size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm")}
    >
      <Icon aria-hidden className={size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5"} />
      {r.label}
    </span>
  );
}
