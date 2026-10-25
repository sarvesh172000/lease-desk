import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LeaseChangeApproval } from "./LeaseChangeApproval";

const link = { item_id: 28, lease_version_id: 6, version: 2 };

describe("LeaseChangeApproval", () => {
  it("names the controller's approval and links the lease while it waits", () => {
    render(<LeaseChangeApproval leaseId="LEASE-01" modification={{ ...link, state: "PROPOSED" }} entries={4} balanced />);
    expect(screen.getByText(/post when a controller approves the lease change/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "LEASE-01 v2" })).toHaveAttribute("href", "/leases/LEASE-01");
    expect(screen.queryByText(/gateway posted/)).toBeNull();
  });

  it("says the entries are posted once the gateway has posted them", () => {
    render(<LeaseChangeApproval leaseId="LEASE-01" modification={{ ...link, state: "POSTED" }} entries={4} balanced />);
    expect(screen.getByText(/the gateway posted the 4 balanced entries/)).toBeInTheDocument();
    expect(screen.queryByText(/post when a controller approves/)).toBeNull();
  });
});
