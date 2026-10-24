"use client";

/**
 * One PDF page with a citation box drawn over it. Browser-only (pdf.js), so it
 * is loaded through next/dynamic from DocumentViewer.
 */

import { boxToPercent, scaleBox, type PageSize } from "@/lib/bbox";
import type { Box } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

export interface PdfPageProps {
  url: string;
  page: number;
  box?: Box | null;
  /** From GET /api/documents/{sha}/pages; falls back to the PDF's own size. */
  pageSize?: PageSize | null;
  tone?: "billed" | "cited";
  label?: string;
  onError?: (e: Error) => void;
}

/** Canvas resolution. The page is then scaled to its column with CSS, so a
 * resize never re-renders the PDF and the %-positioned box tracks it exactly. */
const RENDER_WIDTH = 1100;

const ZOOMS = [1, 1.5, 2] as const;

export default function PdfPage({ url, page, box, pageSize, tone = "cited", label, onError }: PdfPageProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [intrinsic, setIntrinsic] = useState<PageSize | null>(null);
  const [rendered, setRendered] = useState(false);
  const [zoom, setZoom] = useState<(typeof ZOOMS)[number]>(1);

  const size = pageSize ?? intrinsic;
  const rect = box && size ? boxToPercent(box, size) : null;

  // bring the box into view once the page has painted, and after each zoom
  useEffect(() => {
    const sc = scrollRef.current;
    const wrap = wrapRef.current;
    if (!rendered || !box || !size || !sc || !wrap) return;
    const px = scaleBox(box, size, wrap.clientWidth);
    sc.scrollTop = Math.max(0, px.top - sc.clientHeight / 3);
    sc.scrollLeft = Math.max(0, px.left + px.width / 2 - sc.clientWidth / 2);
  }, [rendered, box, size, zoom]);

  const color = tone === "billed" ? "border-bad bg-bad/10" : "border-mark bg-mark/20";

  return (
    <div className="relative h-full">
      <div ref={scrollRef} className={cn("h-full overflow-y-auto bg-[#e9e7e1] p-3", zoom === 1 ? "overflow-x-hidden" : "overflow-x-auto")}>
        <div ref={wrapRef} className="relative mx-auto bg-white shadow-[0_1px_4px_rgba(0,0,0,0.18)]" style={{ width: `${zoom * 100}%` }}>
          <Document
            file={url}
            loading={<div className="flex h-[480px] items-center justify-center text-sm text-ink-muted">Loading document…</div>}
            error={<div className="flex h-[300px] items-center justify-center px-6 text-center text-sm text-bad">Could not open this PDF.</div>}
            onLoadError={(e) => onError?.(e)}
          >
            <Page
              pageNumber={page}
              width={RENDER_WIDTH}
              renderTextLayer={false}
              renderAnnotationLayer={false}
              onLoadSuccess={(p) => setIntrinsic({ width: p.originalWidth, height: p.originalHeight })}
              onRenderSuccess={() => setRendered(true)}
              loading={<div className="h-[480px]" />}
            />
          </Document>
          {rect && rendered ? (
            <>
              <div
                data-testid="citation-box"
                aria-label={label ? `Highlighted: ${label}` : "Highlighted region"}
                className={cn("pointer-events-none absolute rounded-[2px] border-2", color)}
                style={{
                  left: `calc(${rect.left}% - 3px)`,
                  top: `calc(${rect.top}% - 2px)`,
                  width: `calc(${rect.width}% + 6px)`,
                  height: `calc(${rect.height}% + 4px)`,
                }}
              />
              {/* margin marker: points at the box without covering any text */}
              <div
                aria-hidden
                className={cn("pointer-events-none absolute left-1 w-1.5 rounded-full", tone === "billed" ? "bg-bad" : "bg-mark")}
                style={{ top: `calc(${rect.top}% - 2px)`, height: `calc(${rect.height}% + 4px)` }}
              />
            </>
          ) : null}
        </div>
      </div>
      {rendered ? (
        <div className="absolute bottom-3 right-5 flex overflow-hidden rounded border border-line-strong bg-surface text-xs shadow-card" role="group" aria-label="Zoom">
          {ZOOMS.map((z) => (
            <button
              key={z}
              type="button"
              aria-pressed={zoom === z}
              onClick={() => setZoom(z)}
              className={cn("num px-2 py-1 font-medium", zoom === z ? "bg-accent text-white" : "text-ink-soft hover:bg-sunken")}
            >
              {z === 1 ? "Fit" : `${z * 100}%`}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
