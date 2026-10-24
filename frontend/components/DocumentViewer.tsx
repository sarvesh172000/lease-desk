"use client";

import { documentUrl, getDocumentPages } from "@/lib/api";
import { isValidBox } from "@/lib/bbox";
import type { Box } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useState, type ReactNode } from "react";
import { Skeleton } from "./ui/States";

const PdfPage = dynamic(() => import("./PdfPage"), {
  ssr: false,
  loading: () => (
    <div className="space-y-3 p-6">
      <Skeleton className="h-5 w-1/2" />
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-64 w-full" />
    </div>
  ),
});

/**
 * A stored document page with its citation boxed. Page size comes from
 * GET /api/documents/{sha}/pages so the box scales exactly as §16 specifies.
 * If the document cannot be shown, the cited text is still printed so the
 * reviewer is never left with nothing.
 */
export function DocumentViewer({
  title,
  eyebrow,
  docId,
  page,
  box,
  tone,
  label,
  fallbackText,
  height = 560,
  toolbar,
}: {
  title: ReactNode;
  eyebrow: ReactNode;
  docId?: string | null;
  page?: number;
  box?: Box | null;
  tone: "billed" | "cited";
  label?: string;
  fallbackText?: ReactNode;
  height?: number;
  toolbar?: ReactNode;
}) {
  const [pdfError, setPdfError] = useState<string | null>(null);
  const pages = useQuery({
    queryKey: ["document-pages", docId],
    queryFn: () => getDocumentPages(docId!),
    enabled: !!docId,
    retry: false,
  });
  const pageNo = page ?? 1;
  const size = pages.data?.pages.find((p) => p.page === pageNo) ?? null;
  const validBox = isValidBox(box) ? box : null;

  let body: ReactNode;
  if (!docId) {
    body = <Fallback reason="No document is attached to this side yet." text={fallbackText} />;
  } else if (pages.isError && !pdfError) {
    // page sizes unavailable: still try the PDF, which knows its own size
    body = <PdfPage url={documentUrl(docId)} page={pageNo} box={validBox} tone={tone} label={label} onError={(e) => setPdfError(e.message)} />;
  } else if (pdfError) {
    body = <Fallback reason={`Document ${docId} could not be opened (${pdfError}).`} text={fallbackText} />;
  } else if (pages.isLoading) {
    body = (
      <div className="space-y-3 p-6">
        <Skeleton className="h-5 w-1/2" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  } else {
    body = (
      <PdfPage url={documentUrl(docId)} page={pageNo} box={validBox} pageSize={size} tone={tone} label={label} onError={(e) => setPdfError(e.message)} />
    );
  }

  return (
    <section className="flex min-w-0 flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card">
      <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
        <div className="min-w-0">
          <div className="eyebrow">{eyebrow}</div>
          <div className="truncate text-sm font-semibold" title={typeof title === "string" ? title : undefined}>
            {title}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {toolbar}
          {docId ? <span className="rounded bg-sunken px-1.5 py-0.5 font-mono text-2xs text-ink-muted">p.{pageNo}</span> : null}
        </div>
      </header>
      <div style={{ height }} className="min-h-0">
        {body}
      </div>
    </section>
  );
}

function Fallback({ reason, text }: { reason: string; text?: ReactNode }) {
  return (
    <div className="flex h-full flex-col justify-center gap-3 bg-sunken/50 p-6">
      <p className="text-sm text-ink-muted">{reason}</p>
      {text ? <blockquote className="border-l-[3px] border-mark bg-[#fff8e1] px-3 py-2 text-ink">{text}</blockquote> : null}
    </div>
  );
}
