import { humanize, pct } from "@/lib/format";
import type { ExceptionDetail } from "@/lib/types";
import { cn } from "@/lib/utils";

/** What the charge checker decided and why, with the clause it cited. Shown when no investigation is on record. */
export function CheckerFindingCard({ ex, selected, onSelect }: { ex: ExceptionDetail; selected?: boolean; onSelect?: () => void }) {
  const cited = ex.lease_citation;
  const Wrapper = onSelect && cited ? "button" : "div";
  return (
    <Wrapper
      type={Wrapper === "button" ? "button" : undefined}
      onClick={cited ? onSelect : undefined}
      data-testid="checker-finding"
      className={cn(
        "block w-full rounded-md border bg-surface p-4 text-left",
        selected ? "border-accent ring-1 ring-accent" : "border-line",
        Wrapper === "button" && "hover:border-line-strong",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="eyebrow">Charge checker · {humanize(ex.rule)}</div>
          <div className="mt-0.5 text-sm text-ink-soft">
            Proposes <span className={cn("font-semibold uppercase", ex.proposal === "hold" ? "text-bad" : "text-ok")}>{ex.proposal ?? "—"}</span>
          </div>
        </div>
        {cited?.match_score != null ? (
          <span className="shrink-0 rounded border border-accent/30 bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent" title="How exactly the cited words were found on the lease page">
            Quote found {pct(cited.match_score)}
          </span>
        ) : null}
      </div>
      {ex.reason ? <p className="mt-3 text-[0.98rem] leading-snug text-ink">{ex.reason}</p> : null}
      {cited ? (
        <>
          <blockquote className="mt-3 border-l-[3px] border-warn bg-warn-soft px-3 py-2 text-[0.98rem] leading-snug text-ink">“{cited.quote}”</blockquote>
          <div className="mt-2 text-sm text-ink-muted">
            {cited.label} · page {cited.page}
          </div>
        </>
      ) : (
        <p className="mt-3 text-sm text-ink-muted">The cited clause could not be located on the lease document.</p>
      )}
    </Wrapper>
  );
}
