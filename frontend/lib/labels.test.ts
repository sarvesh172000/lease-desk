import { describe, expect, it } from "vitest";
import { chargeLabel, clinicLabel, monthLong, placeLabel, rootCauseLabel, TRUST_RANKS } from "./labels";

describe("labels", () => {
  it("names charge types in words", () => {
    expect(chargeLabel("base_rent")).toBe("Base rent");
    expect(chargeLabel("cam_estimate")).toBe("CAM estimate");
    expect(chargeLabel("cam_reconciliation")).toBe("CAM reconciliation");
    expect(chargeLabel("property_tax")).toBe("Property tax");
  });

  it("reads an unknown charge type as words, never as a key", () => {
    expect(chargeLabel("signage_fee")).toBe("Signage fee");
    expect(chargeLabel(null)).toBe("Charge");
    expect(chargeLabel("")).toBe("Charge");
  });

  it("names root causes", () => {
    expect(rootCauseLabel("amendment")).toBe("Executed amendment");
    expect(rootCauseLabel("unexplained")).toBe("Unexplained");
    expect(rootCauseLabel(undefined)).toBe("—");
  });

  it("turns a clinic's location into its place, with the id as the fallback", () => {
    expect(placeLabel("Northbay PT — Daly City — Suite 210")).toBe("Daly City, Suite 210");
    expect(placeLabel("Northbay Physical Therapy - San Mateo — Suite 100")).toBe("San Mateo, Suite 100");
    expect(clinicLabel("Northbay PT — Daly City — Suite 210", "CLINIC-01")).toBe("Northbay PT Daly City, Suite 210");
    expect(clinicLabel(null, "CLINIC-01")).toBe("CLINIC-01");
    expect(placeLabel(null)).toBeNull();
  });

  it("writes periods as a month in full", () => {
    expect(monthLong("2026-07-01")).toBe("July 2026");
    expect(monthLong("2026-01")).toBe("January 2026");
    expect(monthLong(null)).toBe("—");
  });

  it("has the six trust ranks in order, 1 the executed amendment", () => {
    expect(TRUST_RANKS.map((r) => r.rank)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(TRUST_RANKS[0].short).toBe("Executed amendment");
  });
});
