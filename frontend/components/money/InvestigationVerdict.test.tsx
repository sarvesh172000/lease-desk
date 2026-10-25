import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Investigation } from "@/lib/types";
import { explanationScore, InvestigationVerdict } from "./InvestigationVerdict";

const base: Investigation = {
  root_cause: "unexplained", confidence: 0, explains_variance: false, evidence: [],
  liability_before: null, liability_after: null, rou_before: null, rou_after: null, entries: [], balanced: false,
};

describe("InvestigationVerdict", () => {
  it("prints no score when nothing explains the variance", () => {
    render(<InvestigationVerdict investigation={base} />);
    expect(screen.getByText("No document changes the lease · the hold stands")).toBeInTheDocument();
    expect(screen.queryByText(/sure of the explanation/)).toBeNull();
    expect(explanationScore(base)).toBeNull();
  });

  it("prints the investigation's own score when a document explains it", () => {
    const found = { ...base, root_cause: "unrecorded_amendment", confidence: 0.95, explains_variance: true };
    render(<InvestigationVerdict investigation={found} />);
    expect(screen.getByText("Explains the variance")).toBeInTheDocument();
    expect(screen.getByText(/95% sure of the explanation/)).toBeInTheDocument();
  });
});
