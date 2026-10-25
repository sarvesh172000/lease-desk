import { describe, expect, it } from "vitest";
import { phaseOf, type InvestigationRun } from "./useInvestigationRun";
import { runErrorText } from "../InvestigationTimeline";

const run = (state: InvestigationRun["state"], stage: InvestigationRun["stage"] = null): InvestigationRun =>
  ({ state, stage, events: [], error: null, get: () => undefined, start: () => undefined }) as unknown as InvestigationRun;

describe("the phase the money screen shows", () => {
  it("leaves the mailbox when a run stops: what is on record, or nothing yet", () => {
    expect(phaseOf(run("error", "searching"), false)).toBe("ready");
    expect(phaseOf(run("error", "searching"), true)).toBe("settled");
  });

  it("follows a live run while it streams", () => {
    expect(phaseOf(run("running", "searching"), true)).toBe("searching");
    expect(phaseOf(run("running", null), false)).toBe("searching");
  });
});

describe("a stopped run, in words", () => {
  it("says who may run it when the API refused", () => {
    expect(runErrorText("403 Forbidden")).toMatch(/controller or the regional manager/);
    expect(runErrorText("403")).toMatch(/cannot run/);
  });

  it("keeps any other reason as the API gave it", () => {
    expect(runErrorText("stream closed")).toBe("stream closed");
    expect(runErrorText(null)).toBe("Stopped.");
  });
});
