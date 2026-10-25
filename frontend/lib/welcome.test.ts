import { describe, expect, it } from "vitest";
import { isPerson } from "./labels";
import type { Actor, ExceptionSummary } from "./types";
import { amendmentCaseId, figureSource, sourceLabel } from "./welcome";

const measured = { measured_at: "2026-10-25T03:25:30+00:00", by: "make eval" };

describe("where a welcome-page figure comes from", () => {
  it("is live only when the API is the source, reachable, and the query succeeded", () => {
    expect(figureSource({ source: "api", reachable: true, liveOk: true, asOf: "2026-07-01" })).toEqual({ kind: "live", asOf: "2026-07-01" });
    expect(figureSource({ source: "api", reachable: false, liveOk: true, measured }).kind).toBe("measured");
    expect(figureSource({ source: "api", reachable: true, liveOk: false, measured }).kind).toBe("measured");
  });

  it("never calls fixtures live, whatever they contain", () => {
    const s = figureSource({ source: "fixtures", reachable: true, liveOk: true, measured });
    expect(s.kind).toBe("measured");
    expect(sourceLabel(s)).toBe("measured 25 Oct 2026 by make eval");
  });

  it("names the fixtures as fixtures when nothing was measured", () => {
    const s = figureSource({ source: "fixtures", reachable: false, liveOk: true, measured: null });
    expect(s.kind).toBe("fixtures");
    expect(sourceLabel(s)).toMatch(/offline, not live/);
  });

  it("says so when there is nothing to show", () => {
    const s = figureSource({ source: "api", reachable: false, liveOk: false, measured: null });
    expect(s.kind).toBe("none");
    expect(sourceLabel(s)).toMatch(/unreachable/);
  });

  it("labels live figures with the business date", () => {
    expect(sourceLabel({ kind: "live", asOf: "2026-07-01" })).toBe("live · as of 1 Jul 2026");
    expect(sourceLabel({ kind: "live", asOf: null })).toBe("live");
  });
});

describe("the amendment case", () => {
  const row = (over: Partial<ExceptionSummary>): ExceptionSummary => ({
    exception_id: "exc_1", lease_id: "LEASE-01", clinic_id: "STORE-01", period: "2026-01-01", charge_type: "cam_estimate",
    expected: 1, actual: 2, delta: 1, status: "pending_review", confidence: 1, ...over,
  });

  it("is the July base-rent under-bill, whatever id the running system gave it", () => {
    const rows = [row({}), row({ exception_id: "exc_18", period: "2026-07-01", charge_type: "base_rent", delta: -2226.65 })];
    expect(amendmentCaseId(rows)).toBe("exc_18");
  });

  it("is nothing rather than a guess", () => {
    expect(amendmentCaseId([row({ period: "2026-07-01", charge_type: "base_rent", delta: 10 })])).toBeNull();
    expect(amendmentCaseId(undefined)).toBeNull();
  });
});

describe("people", () => {
  const actor = (id: string, role: string): Actor => ({ id, name: id, role, region_id: null, entity_id: null });

  it("excludes the gateway and the agents, by id and by role", () => {
    expect(isPerson(actor("PER-CTRL", "controller"))).toBe(true);
    expect(isPerson(actor("system:gateway", "system"))).toBe(false);
    expect(isPerson(actor("agent:checker", "agent"))).toBe(false);
    expect(isPerson(actor("system:engine", "controller"))).toBe(false);
    expect(isPerson(actor("PER-X", "agent"))).toBe(false);
  });
});

describe("the document fan", () => {
  it("walks rest → invoice → email → figure as beat 1 scrolls", async () => {
    const { fanState } = await import("./welcome");
    expect([0, 0.1, 0.2, 0.5, 0.8, 1].map((p) => fanState(p))).toEqual(["rest", "rest", "invoice", "email", "figure", "figure"]);
  });

  it("tells the story in its final frame when motion is reduced", async () => {
    const { fanState } = await import("./welcome");
    expect(fanState(0, true)).toBe("figure");
  });
});
