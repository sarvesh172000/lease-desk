import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// A stand-in for the generated SpacetimeDB client: records the callbacks the
// hook registers so the test can play the server's part.
const fake = vi.hoisted(() => {
  const state = {
    builds: 0,
    disconnects: 0,
    subscribed: [] as unknown[],
    onInsert: [] as Array<(...a: unknown[]) => void>,
    onUpdate: [] as Array<(...a: unknown[]) => void>,
    onApplied: undefined as undefined | (() => void),
    connect: undefined as undefined | (() => void),
  };
  const conn = {
    db: {
      deskStatus: {
        onInsert: (cb: () => void) => state.onInsert.push(cb),
        onUpdate: (cb: () => void) => state.onUpdate.push(cb),
      },
      agentStep: { onInsert: () => undefined, iter: () => [][Symbol.iterator]() },
    },
    subscriptionBuilder: () => {
      const sb = {
        onApplied: (cb: () => void) => ((state.onApplied = cb), sb),
        onError: () => sb,
        subscribe: (q: unknown[]) => {
          state.subscribed = q;
          return {};
        },
      };
      return sb;
    },
    disconnect: () => {
      state.disconnects += 1;
    },
  };
  const builder = {
    withUri: () => builder,
    withDatabaseName: () => builder,
    onConnect: (cb: (c: typeof conn) => void) => ((state.connect = () => cb(conn)), builder),
    onConnectError: () => builder,
    build: () => {
      state.builds += 1;
      return conn;
    },
  };
  return { state, builder };
});

vi.mock("./spacetime", () => ({
  DbConnection: { builder: () => fake.builder },
  tables: { deskStatus: "deskStatus", agentStep: "agentStep" },
}));

import { LIVE_QUERY_KEYS, useLiveStatus } from "./live";
import { Providers } from "@/app/providers";

function wrapperFor(qc: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  Object.assign(fake.state, {
    builds: 0, disconnects: 0, subscribed: [], onInsert: [], onUpdate: [],
    onApplied: undefined, connect: undefined,
  });
  vi.useFakeTimers();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

describe("useLiveStatus", () => {
  it("does nothing without the env: no connection, no error", async () => {
    vi.stubEnv("NEXT_PUBLIC_SPACETIME_URI", "");
    vi.stubEnv("NEXT_PUBLIC_SPACETIME_DB", "");
    const warn = vi.spyOn(console, "warn");
    const { unmount } = render(<Providers><p>app</p></Providers>);
    await vi.dynamicImportSettled();
    unmount();
    expect(fake.state.builds).toBe(0);
    expect(warn).not.toHaveBeenCalled();
  });

  it("invalidates the approval's queries on a desk_status change, not on the initial rows", async () => {
    vi.stubEnv("NEXT_PUBLIC_SPACETIME_URI", "wss://maincloud.spacetimedb.com");
    vi.stubEnv("NEXT_PUBLIC_SPACETIME_DB", "leasedesk-live");
    const qc = new QueryClient();
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    const { unmount } = renderHook(() => useLiveStatus(), { wrapper: wrapperFor(qc) });

    await act(async () => {
      await vi.dynamicImportSettled();
    });
    expect(fake.state.builds).toBe(1);
    act(() => fake.state.connect!());
    expect(fake.state.subscribed).toContain("deskStatus");

    // rows delivered with the subscription are history
    act(() => fake.state.onInsert.forEach((cb) => cb({}, { exceptionId: "exc_1" })));
    act(() => vi.advanceTimersByTime(500));
    expect(invalidate).not.toHaveBeenCalled();

    act(() => fake.state.onApplied!());
    act(() => {
      fake.state.onUpdate.forEach((cb) => cb({}, {}, { exceptionId: "exc_1", status: "balanced" }));
      fake.state.onInsert.forEach((cb) => cb({}, { exceptionId: "exc_2" }));
    });
    act(() => vi.advanceTimersByTime(500));

    const keys = invalidate.mock.calls.map((c) => (c[0] as { queryKey: string[] }).queryKey[0]);
    for (const k of ["exceptions", "summary", "exception", "audit"]) expect(keys).toContain(k);
    expect(keys).toHaveLength(LIVE_QUERY_KEYS.length); // a burst is one refetch

    unmount();
    expect(fake.state.disconnects).toBe(1);
  });
});
