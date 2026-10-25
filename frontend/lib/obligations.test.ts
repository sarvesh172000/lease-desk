import { describe, expect, it } from "vitest";
import { countByUrgency, groupByMonth, urgencyOf } from "./obligations";
import type { Obligation } from "./types";

const ob = (id: number, due_date: string, days_left: number, kind: Obligation["kind"] = "renewal_notice"): Obligation =>
  ({ id, lease_id: "LEASE-01", clinic_id: "CLINIC-01", region_id: "REG-BAY", entity_id: "ENT-CA", kind, key: `k${id}`, due_date, days_left, action: "Act", citation: { section: null, page: null, quote: null, document_id: null, field: null, lease_version_id: null }, source: "lease_term", lease_version_id: 1, details: {}, alert_dates: { "90": due_date, "60": due_date, "30": due_date }, alerts: [] });

describe("obligation urgency", () => {
  it("bands by days left against the business clock", () => {
    expect(urgencyOf(-1)).toBe("overdue");
    expect(urgencyOf(0)).toBe("soon");
    expect(urgencyOf(30)).toBe("soon");
    expect(urgencyOf(31)).toBe("quarter");
    expect(urgencyOf(90)).toBe("quarter");
    expect(urgencyOf(91)).toBe("later");
  });

  it("groups deadlines by the month they fall in, soonest first", () => {
    const groups = groupByMonth([ob(3, "2026-09-15", 76), ob(1, "2026-07-20", 19), ob(2, "2026-07-05", 4), ob(4, "2027-01-01", 184)]);
    expect(groups.map((g) => g.month)).toEqual(["2026-07", "2026-09", "2027-01"]);
    expect(groups[0].obligations.map((o) => o.id)).toEqual([2, 1]);
  });

  it("counts each band", () => {
    expect(countByUrgency([ob(1, "2026-06-01", -30), ob(2, "2026-07-10", 9), ob(3, "2026-08-30", 60), ob(4, "2027-01-01", 184), ob(5, "2027-02-01", 215)])).toEqual({ overdue: 1, soon: 1, quarter: 1, later: 2 });
  });
});
