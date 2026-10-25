import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LeaseTerm, LeaseVersion } from "@/lib/types";

const mutate = vi.fn();
let data: LeaseVersion[] = [];
let role = "regional_manager";

vi.mock("@/lib/hooks", () => ({
  useLeaseVersions: () => ({ data, isLoading: false, isError: false }),
  useConfirmLeaseVersion: () => ({ mutate, isPending: false, isError: false }),
  useMe: () => ({ data: { id: "PER-RM-BAY", name: "Dana Whitfield", role, region_id: "REG-BAY", entity_id: null } }),
}));
vi.mock("@/components/DocumentViewer", () => ({
  DocumentViewer: ({ page, box, docId }: { page: number; box: number[]; docId: string }) => (
    <div data-testid="viewer" data-doc={docId}>
      p{page} {box.join(",")}
    </div>
  ),
}));

import { formatTermValue, TermsPanel } from "./TermsPanel";

const llm = { run_id: 1, agent: "abstraction:llm", prompt_id: "abstraction.v3", prompt_version: "3", model: "claude-opus-5-5" };
const generator = { run_id: 1, agent: "abstraction:generator", prompt_id: "generator:datagen.leases", prompt_version: null, model: null };
const rent: LeaseTerm = {
  field: "base_rent_monthly", value: 18500, page: 3, bbox: [72, 100, 300, 112],
  quote: "The initial Monthly Base Rent is $18,500.00 per month", confidence: 1, document_id: "a".repeat(32), extracted_by: llm,
};
const expiry: LeaseTerm = {
  field: "expiration", value: "2028-12-31", page: 2, bbox: [60, 400, 320, 414],
  quote: "The Term shall expire on December 31, 2028", confidence: 0.96, document_id: "a".repeat(32), extracted_by: llm,
};
const deposit: LeaseTerm = {
  field: "security_deposit", value: 37000, page: null, bbox: null, quote: "nowhere", confidence: 0, document_id: null, extracted_by: llm,
};

function version(over: Partial<LeaseVersion> = {}): LeaseVersion {
  return {
    lease_id: "LEASE-01", version: 1, lease_version_id: 7, effective_from: "2024-01-01",
    confirmed: false, confirmed_by: null, confirmed_at: null,
    work_item: { id: 42, state: "PROPOSED", proposal: "approve", allowed_actions: ["approve", "reject", "hold"] },
    terms: [rent, expiry, deposit], ...over,
  };
}

describe("TermsPanel", () => {
  beforeEach(() => {
    mutate.mockReset();
    role = "regional_manager";
  });

  it("shows every term with its value and match, and never 'not abstracted yet' when terms exist", () => {
    data = [version()];
    render(<TermsPanel leaseId="LEASE-01" />);
    expect(screen.queryByText(/not abstracted/i)).toBeNull();
    const rows = screen.getAllByTestId("term-row");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("Base rent, monthly");
    expect(rows[0]).toHaveTextContent("$18,500.00");
    expect(rows[0]).toHaveTextContent("100%");
    expect(rows[2]).toHaveTextContent("not located");
  });

  it("clicking a term opens the page with that term's bbox in the viewer", () => {
    data = [version()];
    render(<TermsPanel leaseId="LEASE-01" />);
    expect(screen.queryByTestId("viewer")).toBeNull();
    fireEvent.click(screen.getAllByTestId("term-row")[0]);
    expect(screen.getByTestId("viewer")).toHaveTextContent("p3 72,100,300,112");
    expect(screen.getByTestId("term-quote")).toHaveTextContent("The initial Monthly Base Rent is $18,500.00 per month");
    // another term: another page and box
    fireEvent.click(screen.getByRole("button", { name: "p.2" }));
    expect(screen.getByTestId("viewer")).toHaveTextContent("p2 60,400,320,414");
    // a term with no location cannot be selected
    fireEvent.click(screen.getAllByTestId("term-row")[2]);
    expect(screen.getByTestId("viewer")).toHaveTextContent("p2 60,400,320,414");
  });

  it("badges a version read by Claude, and one from the generator, differently", () => {
    data = [version({ version: 1, confirmed: true, confirmed_by: "PER-RM-BAY", confirmed_at: "2026-01-02T10:00:00Z", terms: [{ ...rent, extracted_by: generator }] }), version({ version: 2, lease_version_id: 8, effective_from: "2026-07-01" })];
    render(<TermsPanel leaseId="LEASE-01" />);
    // the newest version opens, read by Claude
    const panelBadges = screen.getAllByTestId("extractor-badge");
    expect(panelBadges[0]).toHaveAttribute("data-kind", "llm");
    expect(panelBadges[0]).toHaveTextContent("Read by Claude");
    expect(panelBadges[0]).toHaveTextContent("abstraction:llm");
    // the version strip badges each one
    expect(within(screen.getByTestId("version-1")).getByTestId("extractor-badge")).toHaveAttribute("data-kind", "generator");
    expect(within(screen.getByTestId("version-2")).getByTestId("extractor-badge")).toHaveAttribute("data-kind", "llm");
    expect(screen.getByTestId("version-1")).toHaveTextContent("confirmed by PER-RM-BAY");
    expect(screen.getByTestId("version-2")).toHaveTextContent("awaiting confirmation");
  });

  it("offers Confirm to someone the server allows, and confirms through the work item", () => {
    data = [version()];
    render(<TermsPanel leaseId="LEASE-01" />);
    fireEvent.click(screen.getByTestId("confirm-version"));
    expect(mutate).toHaveBeenCalledWith(42);
  });

  it("draws no Confirm when the server refuses or the version is confirmed", () => {
    data = [version({ work_item: { id: 42, state: "PROPOSED", proposal: "approve", allowed_actions: ["hold"] } })];
    const { unmount } = render(<TermsPanel leaseId="LEASE-01" />);
    expect(screen.queryByTestId("confirm-version")).toBeNull();
    expect(screen.getByText("Not yours to confirm")).toBeInTheDocument();
    unmount();
    data = [version({ confirmed: true, confirmed_by: "PER-RM-BAY", confirmed_at: "2026-01-02T10:00:00Z" })];
    render(<TermsPanel leaseId="LEASE-01" />);
    expect(screen.queryByTestId("confirm-version")).toBeNull();
  });

  it("formats values without changing them", () => {
    expect(formatTermValue(rent)).toBe("$18,500.00");
    expect(formatTermValue({ ...rent, field: "escalation_amount", value: 0.03 })).toBe("3.00%");
    expect(formatTermValue({ ...rent, field: "escalation_kind", value: "fixed_step" })).not.toBe("—");
    expect(formatTermValue({ ...rent, field: "renewal_count", value: null })).toBe("—");
    expect(formatTermValue({ ...rent, field: "rentable_sf", value: 6200 })).toBe("6,200 sf");
  });
});
