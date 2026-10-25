import { describe, expect, it } from "vitest";
import { hiddenColumns, isUniform, visibleColumns, type ColumnSpec } from "./columns";

type Row = { title: string; confidence: number | null; clinic: string | null; variance: number };
const cols: ColumnSpec<Row>[] = [
  { key: "title", get: (r) => r.title, always: true },
  { key: "confidence", get: (r) => r.confidence },
  { key: "clinic", get: (r) => r.clinic },
  { key: "variance", get: (r) => r.variance },
];

describe("column hiding", () => {
  it("hides a column that is empty on every row", () => {
    const rows: Row[] = [
      { title: "a", confidence: null, clinic: "C1", variance: 1 },
      { title: "b", confidence: null, clinic: "C2", variance: 2 },
    ];
    expect(hiddenColumns(rows, cols)).toEqual(["confidence"]);
    expect(visibleColumns(rows, cols).map((c) => c.key)).toEqual(["title", "clinic", "variance"]);
  });

  it("hides a column that is identical on every row (the 56% confidence problem)", () => {
    const rows: Row[] = [
      { title: "a", confidence: 0.56, clinic: "C1", variance: 1 },
      { title: "b", confidence: 0.56, clinic: "C1", variance: 2 },
      { title: "c", confidence: 0.56, clinic: "C1", variance: 3 },
    ];
    expect(hiddenColumns(rows, cols)).toEqual(["confidence", "clinic"]);
  });

  it("keeps a column once any row differs", () => {
    const rows: Row[] = [
      { title: "a", confidence: 0.56, clinic: "C1", variance: 1 },
      { title: "b", confidence: 0.94, clinic: "C1", variance: 1 },
    ];
    expect(hiddenColumns(rows, cols)).toEqual(["clinic", "variance"]);
    expect(visibleColumns(rows, cols).map((c) => c.key)).toContain("confidence");
  });

  it("never hides an always-on column, and treats a dash as empty", () => {
    const rows = [{ title: "same", confidence: null, clinic: "—", variance: 0 }, { title: "same", confidence: null, clinic: "—", variance: 0 }];
    expect(isUniform(rows, cols[0])).toBe(false);
    expect(hiddenColumns(rows, cols)).toEqual(["confidence", "clinic", "variance"]);
  });

  it("shows every column for a single row unless it is empty", () => {
    const rows: Row[] = [{ title: "a", confidence: null, clinic: "C1", variance: 5 }];
    expect(hiddenColumns(rows, cols)).toEqual(["confidence"]);
  });

  it("hides nothing when there are no rows", () => {
    expect(hiddenColumns([], cols)).toEqual([]);
  });
});
