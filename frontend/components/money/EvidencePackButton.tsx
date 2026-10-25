"use client";

import { Button } from "@/components/ui/Button";
import { ApiError } from "@/lib/api";
import { useEvidencePack } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { FileDown, ShieldCheck, ShieldAlert } from "lucide-react";

/**
 * Download the evidence pack (PDF) for this item and say what the chain stamp
 * in the response said. The stamp is always printed in the PDF too.
 */
export function EvidencePackButton({ itemId, exceptionId }: { itemId: number | null | undefined; exceptionId: string }) {
  const pack = useEvidencePack();
  const notLive = pack.error instanceof ApiError && pack.error.status === 501;
  const r = pack.data;
  return (
    <div className="flex items-center gap-2">
      <Button
        variant="secondary"
        size="sm"
        icon={<FileDown aria-hidden className="h-3.5 w-3.5" />}
        loading={pack.isPending}
        disabled={itemId == null}
        disabledReason={itemId == null ? "Evidence packs are built from a work item; this exception has none" : undefined}
        onClick={() => pack.mutate({ subject: { type: "work_item", id: itemId! }, filename: `evidence-pack-${exceptionId}.pdf` })}
      >
        Evidence pack
      </Button>
      {r ? (
        <span
          role="status"
          className={cn(
            "flex items-center gap-1 text-xs font-medium",
            r.chainVerified === false ? "text-bad" : r.chainVerified ? "text-ok" : "text-ink-muted",
          )}
        >
          {r.chainVerified === false ? <ShieldAlert aria-hidden className="h-3.5 w-3.5" /> : <ShieldCheck aria-hidden className="h-3.5 w-3.5" />}
          {r.chainVerified === true
            ? "Chain verified"
            : r.chainVerified === false
              ? `Chain broken at #${r.brokenSeq ?? "?"}`
              : "Downloaded · chain stamp in the PDF"}
        </span>
      ) : pack.isError ? (
        <span role="alert" className="max-w-56 text-xs text-ink-muted">
          {notLive ? "Needs the live API" : pack.error.message}
        </span>
      ) : null}
    </div>
  );
}
