import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Actor, ExceptionDetail } from "@/lib/types";
import { TooltipProvider } from "../ui/Tooltip";

// The server decides what this person may press; the test plays the server.
const h = vi.hoisted(() => ({
  actions: [] as string[],
  role: "controller",
  mutate: vi.fn(),
}));

vi.mock("@/lib/hooks", () => ({
  useAllowedActions: () => ({ data: { actions: h.actions }, isLoading: false, isError: false }),
  useExceptionAction: () => ({ mutate: h.mutate, reset: vi.fn(), isPending: false, error: null, variables: undefined }),
  usePayAsBilled: () => ({ mutate: vi.fn(), reset: vi.fn(), isPending: false, error: null }),
  useMe: () => ({ data: { id: "P", name: "P", role: h.role, region_id: null, entity_id: null } as Actor }),
}));

import { DecisionActions } from "./DecisionActions";

const held: ExceptionDetail = {
  exception_id: "exc_7",
  lease_id: "LEASE-01",
  period: "2026-01-01",
  expected: 0,
  actual: 19626.65,
  delta: 19626.65,
  status: "pending_review",
  investigation: null,
  proposal: "hold",
  payable: 0,
  disputed: 19626.65,
};

function renderActions(ex: ExceptionDetail = held) {
  return render(
    <TooltipProvider>
      <DecisionActions ex={ex} />
    </TooltipProvider>,
  );
}

const buttons = () => within(screen.getByTestId("actions")).queryAllByRole("button").map((b) => b.textContent);

beforeEach(() => {
  h.actions = [];
  h.role = "controller";
  h.mutate.mockReset();
});

describe("DecisionActions", () => {
  it("shows nothing to press when the server allows nothing", () => {
    renderActions();
    expect(buttons()).toEqual([]);
    expect(screen.getByTestId("no-actions")).toHaveTextContent("No actions for your role");
  });

  it("shows only the allowed actions: hold only means no Uphold, Reject or Pay as billed", () => {
    h.actions = ["hold"];
    renderActions();
    expect(buttons()).toEqual(["Hold"]);
  });

  it("names approve on a hold as Uphold hold, and offers the controller Pay as billed", () => {
    h.actions = ["hold", "approve", "reject"];
    renderActions();
    expect(buttons()).toEqual(["Pay as billed…", "Hold", "Reject", "Uphold hold"]);
  });

  it("never offers Pay as billed to anyone but the controller", () => {
    h.actions = ["hold", "approve"];
    h.role = "regional_manager";
    renderActions();
    expect(buttons()).toEqual(["Hold", "Uphold hold"]);
  });

  it("ignores actions this screen does not offer (resume, close)", () => {
    h.actions = ["resume", "close", "hold"];
    renderActions();
    expect(buttons()).toEqual(["Hold"]);
  });

  it("restates the money in a confirm before acting, and acts only on confirm", () => {
    h.actions = ["approve"];
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Uphold hold" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Nothing is paid; the $19,626.65 stays held.");
    expect(h.mutate).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Uphold hold" }));
    expect(h.mutate).toHaveBeenCalledWith("approve", expect.anything());
  });
});
