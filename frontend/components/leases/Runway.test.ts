import { describe, expect, it } from "vitest";
import { ghostSpan } from "./Runway";

const day = (d: string) => Date.parse(`${d}T00:00:00Z`);

describe("ghostSpan", () => {
  it("spans v1's end to v2's while v2 waits for approval", () => {
    const span = ghostSpan({ from: 2, oldEnd: "2028-12-31", newEnd: "2031-12-31" }, "2028-12-31");
    expect(span).toEqual({ from: 2, oldEnd: "2028-12-31", newEnd: "2031-12-31", start: day("2028-12-31"), stop: day("2031-12-31") });
  });

  it("keeps the same span once v2 is confirmed and the lease ends with it", () => {
    const span = ghostSpan({ from: 2, oldEnd: "2028-12-31", newEnd: "2031-12-31" }, "2031-12-31");
    expect(span?.start).toBe(day("2028-12-31"));
    expect(span?.stop).toBe(day("2031-12-31"));
  });

  it("draws nothing when the ends agree, or there is no newer version", () => {
    expect(ghostSpan({ from: 2, oldEnd: "2031-12-31", newEnd: "2031-12-31" }, "2031-12-31")).toBeNull();
    expect(ghostSpan(null, "2031-12-31")).toBeNull();
  });

  it("falls back to the lease's end when v1's is not on record", () => {
    expect(ghostSpan({ from: 2, oldEnd: null, newEnd: "2031-12-31" }, "2028-12-31")?.oldEnd).toBe("2028-12-31");
  });
});
