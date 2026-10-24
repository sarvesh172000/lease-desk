"use client";

/**
 * One document page with a citation box drawn over it.
 *
 * The page is the server's own render (GET /api/documents/{sha}/pages/{n}.png),
 * not a PDF parsed in the browser: the backend already rasterizes with PyMuPDF
 * and serves the result immutable, so there is no PDF engine, no web worker and
 * no second copy of the bytes on this side. The box is positioned in percent of
 * the page, so the render DPI never enters the arithmetic.
 */

import { pageImageUrl } from "@/lib/api";
import { boxToPercent, scaleBox, type PageSize } from "@/lib/bbox";
import type { Box } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useEffect, useRef, useState } from "react";

export interface PdfPageProps {
  docId: string;
  page: number;
  box?: Box | null;
  /** From GET /api/documents/{sha}/pages; falls back to the image's own size. */
  pageSize?: PageSize | null;
  tone?: "billed" | "cited";
  label?: string;
  onError?: (e: Error) => void;
}

const ZOOMS = [1, 1.5, 2] as const;

export default function PdfPage({ docId, page, box, pageSize, tone = "cited", label, onError }: PdfPageProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [rendered, setRendered] = useState(false);
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState<(typeof ZOOMS)[number]>(1);

  const src = pageImageUrl(docId, page);
  // `pageSize` is in PDF points; the image is a 150-DPI raster of the same
  // page. Only the points can place a box, so without them the page is shown
  // unhighlighted rather than with the box in the wrong place.
  const rect = box && pageSize ? boxToPercent(box, pageSize) : null;

  // a new page is a new render: do not keep the old one on screen
  useEffect(() => {
    setRendered(false);
    setFailed(false);
  }, [src]);

  // bring the box into view once the page has painted, and after each zoom
  useEffect(() => {
    const sc = scrollRef.current;
    const wrap = wrapRef.current;
    if (!rendered || !box || !pageSize || !sc || !wrap) return;
    const px = scaleBox(box, pageSize, wrap.clientWidth);
    // keep the page header in view when the box already fits; otherwise centre it
    const fits = px.top + px.height + 48 <= sc.clientHeight;
    sc.scrollTop = fits ? 0 : Math.max(0, px.top - sc.clientHeight / 3);
    sc.scrollLeft = zoom === 1 ? 0 : Math.max(0, px.left + px.width / 2 - sc.clientWidth / 2);
  }, [rendered, box, pageSize, zoom]);

  const color = tone === "billed" ? "border-bad bg-bad/10" : "border-mark bg-mark/20";

  if (failed) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-sm text-bad">
        Could not load page {page} of this document.
      </div>
    );
  }

  return (
    <div className="relative h-full">
      <div ref={scrollRef} className={cn("h-full overflow-y-auto bg-[#e9e7e1] p-3", zoom === 1 ? "overflow-x-hidden" : "overflow-x-auto")}>
        <div ref={wrapRef} className="relative mx-auto bg-white shadow-[0_1px_4px_rgba(0,0,0,0.18)]" style={{ width: `${zoom * 100}%` }}>
          {/* A cross-origin API render, already served immutable: the image
              optimizer would add a hop and nothing else. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={src}
            alt={`Page ${page}`}
            draggable={false}
            className="block w-full select-none"
            onLoad={() => setRendered(true)}
            onError={() => {
              setFailed(true);
              onError?.(new Error(`page ${page} did not load`));
            }}
          />
          {!rendered ? <div className="absolute inset-0 animate-pulse bg-sunken" /> : null}
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
