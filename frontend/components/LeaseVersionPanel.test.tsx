import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LeaseTerm, LeaseVersion } from "@/lib/types";

const mutate = vi.fn();
let data: LeaseVersion[] = [];

vi.mock("@/lib/hooks", () => ({
  useLeaseVersions: () => ({ data, isLoading: false, isError: false }),
  useConfirmLeaseVersion: () => ({ mutate, isPending: false, isError: false }),
}));
vi.mock("@/components/DocumentViewer", () => ({
  DocumentViewer: ({ page, box }: { page: number; box: number[] }) => (
    <div data-testid="viewer">
      p{page} {box.join(",")}
    </div>
  ),
}));

import { formatTermValue, LeaseVersionPanel } from "./LeaseVersionPanel";

const run = { run_id: 1, agent: "abstraction:generator", prompt_id: "generator:datagen.leases", prompt_version: null, model: null };
const rent: LeaseTerm = {
  field: "base_rent_monthly", value: 18500, page: 3, bbox: [72, 100, 300, 112],
  quote: "The initial Monthly Base Rent is $18,500.00 per month", confidence: 1, document_id: "a".repeat(32), extracted_by: run,
};
const deposit: LeaseTerm = {
  field: "security_deposit", value: 37000, page: null, bbox: null, quote: "nowhere", confidence: 0, document_id: null, extracted_by: run,
};

function version(over: Partial<LeaseVersion> = {}): LeaseVersion {
  return {
    lease_id: "LEASE-01", version: 1, lease_version_id: 7, effective_from: "2024-01-01",
    confirmed: false, confirmed_by: null, confirmed_at: null,
    work_item: { id: 42, state: "PROPOSED", proposal: "approve", allowed_actions: ["approve", "reject", "hold"] },
    terms: [rent, deposit], ...over,
  };
}

describe("LeaseVersionPanel", () => {
  beforeEach(() => mutate.mockReset());

  it("lists each field with its confidence and offers Confirm when allowed", () => {
    data = [version()];
    render(<LeaseVersionPanel leaseId="LEASE-01" />);
    expect(screen.getByText(/awaiting confirmation/)).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByText("not located")).toBeInTheDocument();
    expect(screen.getByText(/from the generated lease terms/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm lease terms" }));
    expect(mutate).toHaveBeenCalledWith(42);
  });

  it("opens the cited page with the box", () => {
    data = [version()];
    render(<LeaseVersionPanel leaseId="LEASE-01" />);
    fireEvent.click(screen.getByRole("button", { name: "p.3" }));
    expect(screen.getByTestId("viewer")).toHaveTextContent("p3 72,100,300,112");
  });

  it("draws no Confirm for someone can() refuses, and says who confirmed", () => {
    data = [version({ confirmed: true, confirmed_by: "PER-RM-BAY", confirmed_at: "2026-01-02T10:00:00Z",
                      work_item: { id: 42, state: "APPROVED", proposal: "approve", allowed_actions: ["hold"] } })];
    render(<LeaseVersionPanel leaseId="LEASE-01" />);
    expect(screen.queryByRole("button", { name: "Confirm lease terms" })).toBeNull();
    expect(screen.getByText(/confirmed by PER-RM-BAY/)).toBeInTheDocument();
  });

  it("formats values without changing them", () => {
    expect(formatTermValue(rent)).toBe("$18,500.00");
    expect(formatTermValue({ ...rent, field: "escalation_amount", value: 0.03 })).toBe("3.00%");
    expect(formatTermValue({ ...rent, field: "escalation_kind", value: "fixed_step" })).not.toBe("—");
    expect(formatTermValue({ ...rent, field: "renewal_count", value: null })).toBe("—");
  });
});
