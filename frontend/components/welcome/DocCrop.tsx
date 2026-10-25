"use client";

import { useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { pageImageUrl } from "@/lib/api";
import { boxToPercent } from "@/lib/bbox";
import { useDocumentPages } from "@/lib/hooks";
import type { Box, DocumentPages } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * A strip of a real document page with the cited box drawing itself around
 * the line the system relied on. The page is the server's own render and the
 * box is the API's, in page points; nothing here is drawn by hand.
 *
 * With no page or box (a live email body has neither) the quote is shown as
 * words instead, never a page with a box in a guessed place.
 */
export function DocCrop({
  docId, page, box, quote, caption, crop, tone = "accent", className, pages,
}: {
  docId: string;
  page: number | null;
  box: Box | null;
  /** Fixture copies of the page images and sizes, when the API is not the source. */
  pages?: { src: (docId: string, page: number) => string; sizes: Record<string, DocumentPages> } | null;
  quote?: string;
  caption?: string;
  /** Which band of the page to show, as a percentage of its height. */
  crop?: { top: number; height: number };
  tone?: "accent" | "bad";
  className?: string;
}) {
  const reduce = useReducedMotion();
  const fromApi = useDocumentPages(page && !pages ? docId : null);
  const [failed, setFailed] = useState(false);
  const size = (pages ? pages.sizes[docId]?.pages : fromApi.data?.pages)?.find((p) => p.page === page) ?? null;
  const rect = box && size ? boxToPercent(box, size) : null;
  const band = crop ?? { top: 0, height: 40 };
  // the page's own proportions when the API has told us them; Letter until then
  const ratio = size ? size.height / size.width : 1.2941;

  if (!page || failed) {
    return (
      <figure className={cn("rounded-md border border-line bg-surface p-4", className)}>
        <blockquote className="border-l-2 border-accent pl-3 text-sm leading-relaxed text-ink">{quote ?? "—"}</blockquote>
        {caption ? <figcaption className="mt-2 font-mono text-2xs text-ink-muted">{caption}</figcaption> : null}
      </figure>
    );
  }

  return (
    <figure className={cn("relative", className)}>
      <div
        className="relative w-full overflow-hidden rounded-sm border border-line bg-white shadow-raised"
        style={{ aspectRatio: `100 / ${band.height * ratio}` }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={pages ? pages.src(docId, page) : pageImageUrl(docId, page)}
          alt={quote ? `Page ${page}: ${quote}` : `Page ${page}`}
          onError={() => setFailed(true)}
          className="absolute left-0 top-0 w-full max-w-none"
          // percent of the image's own height: the band starts band.top% down the page
          style={{ transform: `translateY(-${band.top}%)` }}
        />
        {rect ? (
          <motion.span
            aria-hidden
            data-testid="doc-box"
            initial={reduce ? false : { opacity: 0, scale: 1.25 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true, amount: 0.6 }}
            transition={{ duration: 0.5, delay: 0.35, ease: [0.2, 0.8, 0.2, 1] }}
            className={cn(
              "absolute rounded-[2px] border-2 shadow-[0_0_0_4px_rgb(var(--bg)/0.08)]",
              tone === "bad" ? "border-bad bg-bad/10" : "border-accent bg-accent/10",
            )}
            style={{
              left: `${rect.left}%`,
              width: `${rect.width}%`,
              top: `${((rect.top - band.top) / band.height) * 100}%`,
              height: `${(rect.height / band.height) * 100}%`,
            }}
          />
        ) : null}
      </div>
      {caption ? <figcaption className="mt-2 font-mono text-2xs text-ink-muted">{caption}</figcaption> : null}
    </figure>
  );
}
