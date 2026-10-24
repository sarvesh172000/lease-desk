import type { Box } from "./types";

export interface PageSize {
  width: number;
  height: number;
}

export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Scale a citation box `[x0, y0, x1, y1]` in PDF points (origin top-left, as
 * §16 specifies) to pixels on a page rendered `renderedWidth` px wide.
 *
 * The scale is uniform (renderedWidth / page.width), so the rendered height is
 * implied by the page's aspect ratio. Reversed corners are normalised and the
 * result is clamped to the page, so a sloppy box never draws off the page.
 */
export function scaleBox(box: Box, page: PageSize, renderedWidth: number): Rect {
  if (!(page.width > 0) || !(page.height > 0) || !(renderedWidth > 0)) {
    return { left: 0, top: 0, width: 0, height: 0 };
  }
  const s = renderedWidth / page.width;
  const clampX = (v: number) => Math.min(Math.max(v, 0), page.width);
  const clampY = (v: number) => Math.min(Math.max(v, 0), page.height);
  const x0 = clampX(Math.min(box[0], box[2]));
  const x1 = clampX(Math.max(box[0], box[2]));
  const y0 = clampY(Math.min(box[1], box[3]));
  const y1 = clampY(Math.max(box[1], box[3]));
  return { left: x0 * s, top: y0 * s, width: (x1 - x0) * s, height: (y1 - y0) * s };
}

/** The same box as percentages of the page, for overlays that resize with the page. */
export function boxToPercent(box: Box, page: PageSize): Rect {
  // scaleBox at renderedWidth = page.width gives clamped points; divide out.
  const r = scaleBox(box, page, page.width);
  if (!(page.width > 0) || !(page.height > 0)) return r;
  return {
    left: (r.left / page.width) * 100,
    width: (r.width / page.width) * 100,
    top: (r.top / page.height) * 100,
    height: (r.height / page.height) * 100,
  };
}

export function isValidBox(box: unknown): box is Box {
  return Array.isArray(box) && box.length === 4 && box.every((v) => typeof v === "number" && Number.isFinite(v));
}
