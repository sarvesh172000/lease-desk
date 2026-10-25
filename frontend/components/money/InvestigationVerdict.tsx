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

/**
 * The header's verdict once an investigation has reached "found".
 *
 * When nothing explains the charge the conclusion leads ("Hold stands"), not the root-cause code: on a
 * projector "Unexplained" reads as the system failing, when the search did its job and the hold held.
 * Once a controller has overridden the hold (`pay_as_billed`) the conclusion is no longer true, so the
 * root cause is named instead and the resolution badge carries the outcome.
 */
export function InvestigationVerdict({ investigation, resolution }: Readonly<{ investigation: Investigation; resolution?: string | null }>) {
  const score = explanationScore(investigation);
  const holdStands = !investigation.explains_variance && resolution !== "pay_as_billed";
  return (
    <>
      <div className="font-semibold">{holdStands ? "Hold stands" : rootCauseLabel(investigation.root_cause)}</div>
      <div className={cn("text-sm", investigation.explains_variance ? "text-ok" : "text-ink-soft")}>
        {investigation.explains_variance ? "Explains the variance" : "Investigated · no document changes the lease"}
        {score == null ? null : <span className="num text-ink-soft"> · {pct(score)} sure of the explanation</span>}
      </div>
    </>
  );
}
