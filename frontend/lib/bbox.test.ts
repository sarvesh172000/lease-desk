import { describe, expect, it } from "vitest";
import { boxToPercent, isValidBox, scaleBox } from "./bbox";
import { SECTION_16_EXCEPTION_DETAIL } from "./fixtures";
import type { Box } from "./types";

const LETTER = { width: 612, height: 792 };

describe("scaleBox", () => {
  it("is the identity when rendered at the page's own width", () => {
    const r = scaleBox([85, 125.3, 527, 152.1], LETTER, 612);
    expect(r.left).toBe(85);
    expect(r.top).toBe(125.3);
    expect(r.width).toBe(442);
    expect(r.height).toBeCloseTo(26.8, 9);
  });

  it("scales the §16 evidence box uniformly by renderedWidth / page.width", () => {
    const box = SECTION_16_EXCEPTION_DETAIL.investigation!.evidence[0].box;
    const r = scaleBox(box, LETTER, 306); // half size
    expect(r.left).toBeCloseTo(42.5);
    expect(r.top).toBeCloseTo(62.65);
    expect(r.width).toBeCloseTo(221);
    expect(r.height).toBeCloseTo(13.4);
  });

  it("keeps origin top-left: y grows downward, no flip against page height", () => {
    const r = scaleBox([0, 700, 100, 792], LETTER, 612);
    expect(r.top).toBe(700);
    expect(r.top + r.height).toBe(792);
  });

  it("normalises reversed corners", () => {
    expect(scaleBox([527, 152.1, 85, 125.3], LETTER, 612)).toEqual(scaleBox([85, 125.3, 527, 152.1], LETTER, 612));
  });

  it("clamps a box that spills off the page", () => {
    const r = scaleBox([-20, -5, 700, 900], LETTER, 612);
    expect(r).toEqual({ left: 0, top: 0, width: 612, height: 792 });
  });

  it("returns an empty rect for a zero-sized page or render", () => {
    expect(scaleBox([1, 1, 2, 2], { width: 0, height: 792 }, 600)).toEqual({ left: 0, top: 0, width: 0, height: 0 });
    expect(scaleBox([1, 1, 2, 2], LETTER, 0)).toEqual({ left: 0, top: 0, width: 0, height: 0 });
  });
});

describe("boxToPercent", () => {
  it("expresses x against width and y against height", () => {
    const r = boxToPercent([61.2, 79.2, 306, 396], LETTER);
    expect(r.left).toBeCloseTo(10);
    expect(r.width).toBeCloseTo(40);
    expect(r.top).toBeCloseTo(10);
    expect(r.height).toBeCloseTo(40);
  });
});

describe("isValidBox", () => {
  it("accepts four finite numbers only", () => {
    expect(isValidBox([1, 2, 3, 4] satisfies Box)).toBe(true);
    expect(isValidBox([1, 2, 3])).toBe(false);
    expect(isValidBox([1, 2, 3, Number.NaN])).toBe(false);
    expect(isValidBox(null)).toBe(false);
  });
});
