import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Actor } from "@/lib/types";

// what GET /api/auth/demo-actors could return: people, and the actors that only exist in the audit trail
const h = vi.hoisted(() => ({
  actors: [
    { id: "PER-CTRL", name: "Priya Raghunathan", role: "controller", region_id: null, entity_id: "ENT-CA" },
    { id: "PER-RM-BAY", name: "Dana Whitfield", role: "regional_manager", region_id: "REG-BAY", entity_id: "ENT-CA" },
    { id: "PER-AP", name: "Marcus Oyelaran", role: "ap_clerk", region_id: null, entity_id: "ENT-CA" },
    { id: "PER-AUD", name: "External Auditor", role: "auditor", region_id: null, entity_id: null },
    { id: "system:gateway", name: "Gateway", role: "system", region_id: null, entity_id: null },
    { id: "agent:checker", name: "Checker agent", role: "agent", region_id: null, entity_id: null },
  ] as Actor[],
  source: "api" as "api" | "fixtures",
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/hooks", () => ({
  useDataSource: () => h.source,
  useDemoActors: () => ({ data: h.actors, isLoading: false }),
}));
vi.mock("@/lib/api", () => ({ login: vi.fn(), demoSwitch: vi.fn() }));

import LoginPage from "./page";

function renderLogin() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <LoginPage />
    </QueryClientProvider>,
  );
}

describe("/login", () => {
  it("offers people to sign in as, never the gateway or an agent", () => {
    renderLogin();
    const list = screen.getByTestId("personas");
    const buttons = within(list).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual([
      expect.stringContaining("Priya Raghunathan"),
      expect.stringContaining("Dana Whitfield"),
      expect.stringContaining("Marcus Oyelaran"),
      expect.stringContaining("External Auditor"),
    ]);
    expect(screen.queryByText(/gateway/i)).toBeNull();
    expect(screen.queryByText(/checker agent/i)).toBeNull();
  });

  it("shows role and region on each card, and the demo badge", () => {
    renderLogin();
    expect(screen.getByTestId("demo-badge")).toHaveTextContent(/demo mode/i);
    expect(screen.getByText(/regional manager · bay area/i)).toBeInTheDocument();
    expect(screen.getByText(/controller · all regions/i)).toBeInTheDocument();
  });

  it("keeps the email and password form for everyone else", () => {
    renderLogin();
    expect(screen.getByLabelText("Work email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeRequired();
  });

  it("hides the personas and the badge when demo mode is off", () => {
    h.actors = [];
    renderLogin();
    expect(screen.queryByTestId("personas")).toBeNull();
    expect(screen.queryByTestId("demo-badge")).toBeNull();
  });
});
