import { pct } from "@/lib/format";
import { rootCauseLabel } from "@/lib/labels";
import type { Investigation } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * The investigation's own score, only when it found a document that explains the variance.
 *
 * It answers a different question from the hold's confidence (is the bill wrong?): how sure we are
 * that a document justifies changing the lease. When nothing explains the charge that score is 0 by
 * design, and printing "0%" would read as doubt about the hold, when it is the opposite.
 */
export function explanationScore(inv: Pick<Investigation, "explains_variance" | "confidence">): number | null {
  return inv.explains_variance && inv.confidence > 0 ? inv.confidence : null;
}

/** The header's verdict once an investigation has reached "found". */
export function InvestigationVerdict({ investigation }: Readonly<{ investigation: Investigation }>) {
  const score = explanationScore(investigation);
  return (
    <>
      <div className="font-semibold">{rootCauseLabel(investigation.root_cause)}</div>
      <div className={cn("text-sm", investigation.explains_variance ? "text-ok" : "text-ink-soft")}>
        {investigation.explains_variance ? "Explains the variance" : "No document changes the lease · the hold stands"}
        {score == null ? null : <span className="num text-ink-soft"> · {pct(score)} sure of the explanation</span>}
      </div>
    </>
  );
}
