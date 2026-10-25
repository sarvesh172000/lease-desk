import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { middleware, SESSION_COOKIE } from "./middleware";

const visit = (cookie?: string) =>
  middleware(new NextRequest("https://lease-desk.example/", cookie ? { headers: { cookie } } : undefined));

describe("middleware: the front door", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("sends a visitor with no session to the welcome page", () => {
    const res = visit();
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("https://lease-desk.example/welcome");
  });

  it("lets a signed-in visitor through to Today", () => {
    expect(visit(`${SESSION_COOKIE}=abc`).headers.get("location")).toBeNull();
  });

  it("keeps fixtures mode on Today, where there is never a session", () => {
    vi.stubEnv("NEXT_PUBLIC_USE_FIXTURES", "1");
    expect(visit().headers.get("location")).toBeNull();
  });
});
