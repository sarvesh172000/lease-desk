import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

async function freshApi() {
  return await import("./api");
}

describe("api fixtures fallback", () => {
  it("serves the §16 fixtures verbatim when the API is unreachable, and stays in fixtures mode", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const api = await freshApi();
    const { SECTION_16_EXCEPTION_DETAIL, SECTION_16_LEASES } = await import("./fixtures");

    expect(api.getDataSource()).toBe("api");
    const detail = await api.getException("exc_01_jul_amendment");
    expect(api.getDataSource()).toBe("fixtures");
    expect(detail.investigation).toEqual(SECTION_16_EXCEPTION_DETAIL.investigation);
    expect(detail.delta).toBe(-2226.65);

    const leases = await api.getLeases();
    expect(leases[0]).toEqual(SECTION_16_LEASES[0]);
    expect(fetchMock).toHaveBeenCalledTimes(1); // no retry storm once in fixtures mode
  });

  it("does not mask HTTP errors from a live API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "region scope" }), { status: 403 })));
    const api = await freshApi();
    await expect(api.approveException("exc_01_jul_amendment")).rejects.toMatchObject({ status: 403 });
    expect(api.getDataSource()).toBe("api");
  });

  it("replays the four §16 SSE events in order in fixtures mode", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const api = await freshApi();
    await api.getLeases(); // trip the fallback
    const stages: string[] = [];
    await api.investigate("exc_01_jul_amendment", (e) => stages.push(e.stage), undefined, 0);
    expect(stages).toEqual(["searching", "found", "remeasured", "complete"]);
  });

  it("fixtures mode lets a controller approve, and the audit trail records it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const api = await freshApi();
    expect((await api.getAllowedActions("exc_01_jul_amendment")).actions).toEqual(["approve", "hold"]);
    expect(await api.approveException("exc_01_jul_amendment")).toEqual({ exception_id: "exc_01_jul_amendment", status: "balanced" });
    expect((await api.getAllowedActions("exc_01_jul_amendment")).actions).toEqual([]);
    const audit = await api.getAudit();
    expect(audit.chain_verified).toBe(true);
    expect(audit.events.at(-1)).toMatchObject({ action: "approve", allowed: true, human_approved: true });
  });
});

describe("parseSseChunk", () => {
  it("parses a data frame and ignores comments", async () => {
    const { parseSseChunk } = await freshApi();
    expect(parseSseChunk('event: message\ndata: {"stage": "complete", "entries": 4, "balanced": true}')).toEqual({
      stage: "complete",
      entries: 4,
      balanced: true,
    });
    expect(parseSseChunk(": keep-alive")).toBeNull();
    expect(parseSseChunk("data: not json")).toBeNull();
  });
});
