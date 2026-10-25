import { TRUST_RANKS } from "@/lib/labels";
import { cn } from "@/lib/utils";

/**
 * The six trust ranks as a ladder, rank 1 at the top. The source's own rung is
 * lit; the rest stay visible so the rank means something on its own.
 */
export function TrustLadder({ rank, compact }: { rank: number; compact?: boolean }) {
  return (
    <ol className="flex flex-col gap-0.5" aria-label={`Trust rank ${rank} of 6, 1 is most authoritative`}>
      {TRUST_RANKS.map((r) => {
        const on = r.rank === rank;
        return (
          <li
            key={r.rank}
            aria-current={on ? "true" : undefined}
            className={cn(
              "flex items-center gap-2 rounded-xs px-2 text-xs transition-colors duration-base",
              compact ? "py-0.5" : "py-1",
              on ? "bg-accent-soft font-semibold text-accent" : "text-ink-muted",
            )}
          >
            <span className={cn("num flex h-4 w-4 shrink-0 items-center justify-center rounded-full border text-2xs", on ? "border-accent" : "border-line-strong")}>
              {r.rank}
            </span>
            <span className="truncate">{r.short}</span>
          </li>
        );
      })}
    </ol>
  );
}
