import { day, humanize, pct } from "@/lib/format";
import type { Evidence } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Trust ranks as defined in backend/app/agents/trust.py (1 = highest authority). */
const TRUST_LABEL: Record<number, string> = {
  1: "Executed amendment signed by both parties",
  2: "Original executed lease",
  3: "Authorized representative, in writing",
  4: "Property management, no stated authority",
  5: "Landlord invoice or statement",
  6: "Payment history",
};

export function ConfidenceMeter({ value }: { value: number }) {
  const p = Math.max(0, Math.min(1, value));
  const tone = p >= 0.85 ? "bg-ok" : p >= 0.7 ? "bg-warn" : "bg-bad";
  return (
    <div className="flex items-center gap-2" aria-label={`Confidence ${pct(p)}`}>
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-sunken">
        <div className={cn("h-full", tone)} style={{ width: `${p * 100}%` }} />
      </div>
      <span className="num text-sm font-semibold">{pct(p)}</span>
    </div>
  );
}

export function EvidenceCard({
  evidence,
  confidence,
  rootCause,
  selected,
  onSelect,
}: {
  evidence: Evidence;
  confidence?: number;
  rootCause?: string;
  selected?: boolean;
  onSelect?: () => void;
}) {
  const Wrapper = onSelect ? "button" : "div";
  return (
    <Wrapper
      type={onSelect ? "button" : undefined}
      onClick={onSelect}
      className={cn(
        "block w-full rounded-md border bg-surface p-4 text-left",
        selected ? "border-accent ring-1 ring-accent" : "border-line",
        onSelect && "hover:border-line-strong",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="eyebrow">Evidence{rootCause ? ` · ${humanize(rootCause)}` : ""}</div>
          <div className="mt-0.5 truncate font-mono text-sm text-ink-soft" title={evidence.doc_id}>
            {evidence.doc_id} · p.{evidence.page}
          </div>
        </div>
        <span
          className="shrink-0 rounded border border-accent/30 bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent"
          title="Source trust rank, 1 = most authoritative"
        >
          Trust rank {evidence.trust_rank}
        </span>
      </div>

      <blockquote className="mt-3 border-l-[3px] border-mark bg-[#fff8e1] px-3 py-2 text-[1.02rem] leading-snug text-ink">
        “{evidence.quote}”
      </blockquote>

      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-ink-muted">Source</dt>
        <dd className="truncate" title={evidence.source}>
          {evidence.source}
        </dd>
        {TRUST_LABEL[evidence.trust_rank] ? (
          <>
            <dt className="text-ink-muted">Ranked as</dt>
            <dd>{TRUST_LABEL[evidence.trust_rank]}</dd>
          </>
        ) : null}
        <dt className="text-ink-muted">Dated</dt>
        <dd>{day(evidence.date)}</dd>
        {confidence != null ? (
          <>
            <dt className="self-center text-ink-muted">Confidence</dt>
            <dd>
              <ConfidenceMeter value={confidence} />
            </dd>
          </>
        ) : null}
      </dl>
    </Wrapper>
  );
}
