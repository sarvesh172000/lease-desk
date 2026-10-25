import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiHealth } from "@/lib/api";
import type { Actor } from "@/lib/types";

// The shell reads everything through hooks; the test plays the API's part.
const h = vi.hoisted(() => ({
  me: { id: "PER-CTRL", name: "Priya Raghunathan", role: "controller", region_id: null, entity_id: "ENT-CA" } as Actor,
  actors: [] as Actor[],
  source: "api" as "api" | "fixtures",
  health: { reachable: true } as ApiHealth,
  live: "off" as string,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@/lib/hooks", () => ({
  useMe: () => ({ data: h.me, isLoading: false, isError: false, isSuccess: true }),
  useDemoActors: () => ({ data: h.actors }),
  useDataSource: () => h.source,
  useApiHealth: () => h.health,
  useExceptions: () => ({ data: [{ status: "pending_review" }, { status: "balanced" }] }),
  useSummary: () => ({ data: { as_of: "2026-07-01" }, isLoading: false }),
}));

vi.mock("@/lib/live", () => ({ useLiveConnection: () => h.live }));

import { AppShell } from "./AppShell";
import { TooltipProvider } from "./ui/Tooltip";

function renderShell(children: ReactNode = <p>page</p>) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <AppShell>{children}</AppShell>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  h.actors = [];
  h.source = "api";
  h.health = { reachable: true };
  h.live = "off";
});

describe("AppShell", () => {
  it("has the nine screens in the rail, with today's open exceptions counted", () => {
    renderShell();
    const nav = screen.getByRole("navigation", { name: "Main" });
    const labels = within(nav).getAllByRole("link").map((a) => a.textContent?.replace(/\d+$/, ""));
    expect(labels).toEqual([
      "Today", "Month run", "Exceptions", "Questions", "Leases", "Obligations", "Disputes", "Policies", "Audit trail",
    ]);
    expect(within(nav).getByRole("link", { name: /Today/ })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByLabelText("1 open")).toBeInTheDocument();
  });

  it("offers only people in the role switcher, never agents or the gateway", async () => {
    h.actors = [
      h.me,
      { id: "PER-RM-BAY", name: "Dana Whitfield", role: "regional_manager", region_id: "REG-BAY", entity_id: "ENT-CA" },
      { id: "system:gateway", name: "Gateway", role: "system", region_id: null, entity_id: null },
      { id: "agent:checker", name: "Charge checker", role: "agent", region_id: null, entity_id: null },
    ];
    renderShell();
    const trigger = screen.getByRole("button", { name: /Signed in as Priya Raghunathan/ });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "Enter" });
    const menu = await screen.findByRole("menu");
    expect(within(menu).getByText("Dana Whitfield")).toBeInTheDocument();
    expect(within(menu).queryByText("Gateway")).not.toBeInTheDocument();
    expect(within(menu).queryByText("Charge checker")).not.toBeInTheDocument();
  });

  it("shows a full-width banner with the error when the live API is unreachable", () => {
    h.health = { reachable: false, error: "API unreachable at http://localhost:8000: Failed to fetch" };
    renderShell();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("API unreachable. No figures on this page are current.");
    expect(alert).toHaveTextContent("Failed to fetch");
    expect(within(alert).getByRole("button", { name: /Retry/ })).toBeInTheDocument();
    expect(screen.getByTestId("data-source")).toHaveTextContent("API unreachable"); // never "Live API" while down
  });

  it("names the data source, and fixtures only as an offline demo", () => {
    const { unmount } = renderShell();
    expect(screen.getByTestId("data-source")).toHaveTextContent("Live API");
    unmount();
    h.source = "fixtures";
    renderShell();
    expect(screen.getByTestId("data-source")).toHaveTextContent("Offline · fixtures");
  });

  it("shows the live connection, with off as a quiet normal state", () => {
    const { unmount } = renderShell();
    expect(screen.getByTestId("live-indicator")).toHaveAttribute("data-state", "off");
    expect(screen.getByTestId("live-indicator")).toHaveTextContent("Live off");
    unmount();
    h.live = "reconnecting";
    renderShell();
    expect(screen.getByTestId("live-indicator")).toHaveTextContent("Reconnecting");
  });

  it("shows only the current person's avatar on the persona button", () => {
    h.actors = [
      h.me,
      { id: "PER-RM-BAY", name: "Dana Whitfield", role: "regional_manager", region_id: "REG-BAY", entity_id: "ENT-CA" },
    ];
    renderShell();
    const trigger = screen.getByRole("button", { name: /Signed in as Priya Raghunathan/ });
    expect(trigger).toHaveTextContent("PR");
    expect(trigger).not.toHaveTextContent("DW");
  });

  it("shows the period from the API's business clock", () => {
    renderShell();
    expect(screen.getByRole("button", { name: /period Jul 2026/ })).toBeInTheDocument();
  });
});
