import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function freshApi() {
  return await import("./api");
}

/** Fixtures mode is read from the env at import, so stub it before importing. */
async function fixturesApi() {
  vi.stubEnv("NEXT_PUBLIC_USE_FIXTURES", "1");
  return await freshApi();
}

describe("api: an unreachable live API is an error, never fixtures", () => {
  it("throws ApiUnreachableError, stays on the API, and reports the health for the banner", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);
    const api = await freshApi();

    expect(api.getDataSource()).toBe("api");
    expect(api.getApiHealth()).toEqual({ reachable: true });
    const seen = vi.fn();
    api.subscribeApiHealth(seen);

    await expect(api.getException("exc_01_jul_amendment")).rejects.toBeInstanceOf(api.ApiUnreachableError);
    expect(api.getDataSource()).toBe("api");
    expect(api.getApiHealth()).toMatchObject({ reachable: false, error: expect.stringContaining("Failed to fetch") });
    expect(seen).toHaveBeenCalledTimes(1);

    // every later call still asks the API (a retry can recover), and still fails loudly
    await expect(api.getLeases()).rejects.toBeInstanceOf(api.ApiUnreachableError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(seen).toHaveBeenCalledTimes(1); // same error, no repeat notification
  });

  it("clears the unreachable state once the API answers again", async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValue(json([]));
    vi.stubGlobal("fetch", fetchMock);
    const api = await freshApi();
    await expect(api.getLeases()).rejects.toBeInstanceOf(api.ApiUnreachableError);
    expect(api.getApiHealth().reachable).toBe(false);
    expect(await api.getLeases()).toEqual([]);
    expect(api.getApiHealth()).toEqual({ reachable: true });
  });

  it("does not replay fixtures for an investigation when the API is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const api = await freshApi();
    const stages: string[] = [];
    await expect(api.investigate("exc_01_jul_amendment", (e) => stages.push(e.stage), undefined, 0)).rejects.toBeInstanceOf(
      api.ApiUnreachableError,
    );
    expect(stages).toEqual([]);
  });

  it("does not mask HTTP errors from a live API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "region scope" }), { status: 403 })));
    const api = await freshApi();
    await expect(api.approveException("exc_01_jul_amendment")).rejects.toMatchObject({ status: 403 });
    expect(api.getDataSource()).toBe("api");
    expect(api.getApiHealth()).toEqual({ reachable: true }); // a 403 is an answer, not an outage
  });
});

describe("api fixtures mode (NEXT_PUBLIC_USE_FIXTURES=1)", () => {
  it("serves the §16 fixtures verbatim and never calls the network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const api = await fixturesApi();
    const { SECTION_16_EXCEPTION_DETAIL, SECTION_16_LEASES } = await import("./fixtures");

    expect(api.getDataSource()).toBe("fixtures");
    const detail = await api.getException("exc_01_jul_amendment");
    expect(detail.investigation).toEqual(SECTION_16_EXCEPTION_DETAIL.investigation);
    expect(detail.delta).toBe(-2226.65);
    const leases = await api.getLeases();
    expect(leases[0]).toEqual(SECTION_16_LEASES[0]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("replays the four §16 SSE events in order", async () => {
    vi.stubGlobal("fetch", vi.fn());
    const api = await fixturesApi();
    const stages: string[] = [];
    await api.investigate("exc_01_jul_amendment", (e) => stages.push(e.stage), undefined, 0);
    expect(stages).toEqual(["searching", "found", "remeasured", "complete"]);
  });

  it("lets a controller approve, and the audit trail records it", async () => {
    vi.stubGlobal("fetch", vi.fn());
    const api = await fixturesApi();
    expect((await api.getAllowedActions("exc_01_jul_amendment")).actions).toEqual(["approve", "hold"]);
    expect(await api.approveException("exc_01_jul_amendment")).toEqual({ exception_id: "exc_01_jul_amendment", status: "balanced" });
    expect((await api.getAllowedActions("exc_01_jul_amendment")).actions).toEqual([]);
    const audit = await api.getAudit();
    expect(audit.chain_verified).toBe(true);
    expect(audit.events.at(-1)).toMatchObject({ action: "approve", allowed: true, human_approved: true });
  });
});

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("live API wiring", () => {
  it("maps exception ids to work item ids and back", async () => {
    const api = await freshApi();
    expect(api.itemIdFor("exc_42")).toBe("42");
    expect(api.itemIdFor("exc_01_jul_amendment")).toBe("exc_01_jul_amendment"); // a fixture id is not a work item
    expect(api.exceptionIdFor(42)).toBe("exc_42");
  });

  it("asks /api/items/{item id} for allowed actions, with the session cookie", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ actions: ["approve", "hold"] }));
    vi.stubGlobal("fetch", fetchMock);
    const api = await freshApi();
    expect(await api.getAllowedActions("exc_7")).toEqual({ actions: ["approve", "hold"] });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/items/7/allowed-actions");
    expect(init.credentials).toBe("include");
  });

  it("reads an all-null investigation as not investigated, and keeps a real one", async () => {
    const empty = { root_cause: null, confidence: null, explains_variance: null, evidence: [], liability_before: null, liability_after: null, rou_before: null, rou_after: null, entries: [], balanced: null };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json({ exception_id: "exc_1", investigation: empty, invoice_line: null })));
    const api = await freshApi();
    const d = await api.getException("exc_1");
    expect(d.investigation).toBeNull();
    expect(d.invoice_line).toBeNull();
  });

  it("returns the server's posting status from approve", async () => {
    const answer = { status: "balanced", exception_id: "exc_5", state: "POSTED", posting: { status: "posted", journal_entry_id: 1, error: null } };
    const fetchMock = vi.fn().mockResolvedValue(json(answer));
    vi.stubGlobal("fetch", fetchMock);
    const api = await freshApi();
    expect(await api.approveException("exc_5")).toEqual(answer);
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/api/exceptions/exc_5/approve");
  });

  it("sends the pay-as-billed override with its reason to its own route", async () => {
    const answer = { status: "balanced", exception_id: "exc_5", state: "POSTED", posting: { status: "posted", journal_entry_id: 2, amount: 19626.65, disputed: 0 } };
    const fetchMock = vi.fn().mockResolvedValue(json(answer));
    vi.stubGlobal("fetch", fetchMock);
    const api = await freshApi();
    expect(await api.payAsBilledException("exc_5", "side letter")).toEqual(answer);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/exceptions/exc_5/pay-as-billed");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ reason: "side letter" });
  });

  it("does not mask a refused override (403) from the live API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "only a controller may pay a disputed charge as billed" }, 403)));
    const api = await freshApi();
    await expect(api.payAsBilledException("exc_5", "please")).rejects.toMatchObject({ status: 403 });
  });

  it("takes dashboard totals from /api/summary, not from the exception rows", async () => {
    const summary = { as_of: "2026-01-01", active_leases: 5, open_exceptions: 5, pending_review: 5, held_total: 25736.36, held_count: 5, portfolio_liability: 2259943.54 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(summary)));
    const api = await freshApi();
    expect(await api.getSummary()).toEqual(summary);
  });

  it("lists every charge check under its exception id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      json({ counts: {}, total: 2, items: [
        { id: 3, kind: "CHARGE_CHECK", state: "PROPOSED", title: "b", clinic_id: "STORE-01", period: "2026-01-01", amount: 1, proposal: "approve", reason: "Matches the lease." },
        { id: 1, kind: "CHARGE_CHECK", state: "PROPOSED", title: "a", clinic_id: "STORE-02", period: "2026-01-01", amount: 2, proposal: "hold", reason: "Suite 118" },
      ] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const api = await freshApi();
    const rows = await api.getChargeChecks();
    expect(rows.map((r) => r.exception_id)).toEqual(["exc_1", "exc_3"]);
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/api/items?kind=CHARGE_CHECK");
  });

  it("sends the browser to /login when a data call is 401", async () => {
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { pathname: "/exceptions/exc_1", search: "", assign } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "not signed in" }, 401)));
    const api = await freshApi();
    await expect(api.getExceptions()).rejects.toMatchObject({ status: 401 });
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fexceptions%2Fexc_1");
  });

  it("does not redirect for auth calls (signed out is an answer there)", async () => {
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { pathname: "/", search: "", assign } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "not signed in" }, 401)));
    const api = await freshApi();
    expect(await api.getMe()).toBeNull();
    expect(assign).not.toHaveBeenCalled();
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
    expect(parseSseChunk('data: {"stage": "not_found", "message": "No clause is cited for this charge."}')).toEqual({
      stage: "not_found",
      message: "No clause is cited for this charge.",
    });
    expect(parseSseChunk("data: not json")).toBeNull();
  });
});
