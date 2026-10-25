import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Investigation } from "@/lib/types";
import { explanationScore, InvestigationVerdict } from "./InvestigationVerdict";

const base: Investigation = {
  root_cause: "unexplained", confidence: 0, explains_variance: false, evidence: [],
  liability_before: null, liability_after: null, rou_before: null, rou_after: null, entries: [], balanced: false,
};

describe("InvestigationVerdict", () => {
  it("leads with the conclusion and prints no score when nothing explains the variance", () => {
    render(<InvestigationVerdict investigation={base} />);
    expect(screen.getByText("Hold stands")).toBeInTheDocument();
    expect(screen.getByText("Investigated · no document changes the lease")).toBeInTheDocument();
    expect(screen.queryByText(/Unexplained/)).toBeNull();
    expect(screen.queryByText(/sure of the explanation/)).toBeNull();
    expect(explanationScore(base)).toBeNull();
  });

  it("names the root cause instead once a controller has paid the charge as billed", () => {
    render(<InvestigationVerdict investigation={base} resolution="pay_as_billed" />);
    expect(screen.queryByText("Hold stands")).toBeNull();
    expect(screen.getByText("Unexplained")).toBeInTheDocument();
  });

  it("prints the investigation's own score when a document explains it", () => {
    const found = { ...base, root_cause: "unrecorded_amendment", confidence: 0.95, explains_variance: true };
    render(<InvestigationVerdict investigation={found} />);
    expect(screen.getByText("Explains the variance")).toBeInTheDocument();
    expect(screen.getByText(/95% sure of the explanation/)).toBeInTheDocument();
    expect(screen.queryByText("Hold stands")).toBeNull();
  });
});
