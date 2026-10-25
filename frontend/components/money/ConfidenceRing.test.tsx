import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConfidenceRing } from "./ConfidenceRing";

describe("ConfidenceRing", () => {
  it("prints the API's figure and colours it by value", () => {
    render(<ConfidenceRing value={0.56} label="Checker confidence" />);
    const ring = screen.getByTestId("confidence-ring");
    expect(ring).toHaveAttribute("data-tone", "value");
    expect(ring).toHaveAttribute("aria-label", "Checker confidence 56%");
    expect(screen.getByText("56%")).toHaveClass("text-bad");
    expect(screen.getByText("Checker confidence")).toBeInTheDocument();
  });

  it("keeps the same figure in plain ink when the tone is neutral", () => {
    render(<ConfidenceRing value={0.56} label="Hold confidence" tone="neutral" />);
    expect(screen.getByTestId("confidence-ring")).toHaveAttribute("data-tone", "neutral");
    const num = screen.getByText("56%");
    expect(num).toHaveClass("text-ink-soft");
    expect(num).not.toHaveClass("text-bad");
  });

  it("dims the last figure while a run re-checks it", () => {
    render(<ConfidenceRing value={0.56} label="Checking…" tone="busy" />);
    expect(screen.getByTestId("confidence-ring")).toHaveAttribute("aria-label", "Checking… 56%");
    expect(screen.getByText("56%")).toHaveClass("text-ink-muted");
  });

  it("renders nothing without a figure rather than a dash", () => {
    const { container } = render(<ConfidenceRing value={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
