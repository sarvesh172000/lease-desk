import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/Tooltip";
import { BROKEN_CHAIN_FIXTURE } from "@/lib/chain";
import type { AuditResponse } from "@/lib/types";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), useSearchParams: () => new URLSearchParams() }));
vi.mock("@/lib/hooks", async (orig) => ({ ...(await orig<typeof import("@/lib/hooks")>()), useMe: () => ({ data: { id: "PER-AUD", name: "External Auditor", role: "auditor", region_id: null, entity_id: null } }) }));
// jsdom has no WebGL: the strip takes its flat form
vi.mock("framer-motion", async (orig) => ({ ...(await orig<typeof import("framer-motion")>()), useReducedMotion: () => true }));

import { AuditView } from "@/components/audit/AuditView";

function renderView(data: AuditResponse) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <AuditView data={data} loading={false} error={null} refetch={vi.fn()} fetching={false} updatedAt={Date.now()} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const verified: AuditResponse = { chain_verified: true, events: BROKEN_CHAIN_FIXTURE.events };

describe("audit trail", () => {
  it("shows the API's verdict, verified with the count", () => {
    renderView(verified);
    const banner = screen.getByTestId("chain-banner");
    expect(banner).toHaveAttribute("data-verified", "true");
    expect(banner).toHaveTextContent("Chain verified · 5 events");
  });

  it("shows a broken chain in red at the exact sequence number, with the rows after it struck", () => {
    renderView(BROKEN_CHAIN_FIXTURE);
    const banner = screen.getByTestId("chain-banner");
    expect(banner).toHaveAttribute("data-verified", "false");
    expect(banner).toHaveTextContent("Chain broken at #4");
    expect(banner).toHaveAttribute("role", "alert");
    expect(screen.getByTestId("chain-strip")).toHaveAttribute("data-crack", "4");
    // the hash cells of #4 and #5 are struck through; #3's is not
    const hashOf = (seq: number) => within(screen.getByTestId("audit-table").querySelector(`[data-seq="${seq}"]`) as HTMLElement).getByTestId("row-hash");
    expect(hashOf(5).className).toContain("line-through");
    expect(hashOf(4).className).toContain("line-through");
    expect(hashOf(3).className).not.toContain("line-through");
    // the simulation never overrides a real break
    expect(screen.queryByTestId("simulation-label")).not.toBeInTheDocument();
  });

  it("keeps refused attempts in the chain and names what was tried", () => {
    renderView(verified);
    fireEvent.click(screen.getByTestId("outcome-refused"));
    const rows = screen.getAllByTestId("audit-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("tried to approve");
    expect(rows[0]).toHaveTextContent("Refused");
    fireEvent.click(rows[0]);
    const detail = screen.getByTestId("event-detail");
    expect(detail).toHaveAttribute("data-seq", "3");
    expect(detail).toHaveTextContent("Role agent may not approve accounting judgments");
    expect(detail).toHaveTextContent("seals #2");
  });

  it("simulating tampering cracks the strip with a label, and leaves the verdict alone", () => {
    renderView(verified);
    fireEvent.click(screen.getAllByTestId("audit-row")[2]); // #3
    fireEvent.click(screen.getByTestId("simulate-toggle"));
    expect(screen.getByTestId("simulation-label")).toHaveTextContent("nothing is changed");
    expect(screen.getByTestId("chain-strip")).toHaveAttribute("data-crack", "3");
    expect(screen.getByTestId("chain-banner")).toHaveAttribute("data-verified", "true");
  });

  it("finds a row by hash prefix", () => {
    renderView(verified);
    fireEvent.change(screen.getByLabelText("Search by sequence number or hash prefix"), { target: { value: "c71e" } });
    const rows = screen.getAllByTestId("audit-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveAttribute("data-seq", "3");
  });
});
