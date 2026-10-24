import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it.each([
    ["balanced", "Balanced", "text-ok"],
    ["exception", "Exception", "text-bad"],
    ["pending_review", "Pending review", "text-warn"],
    ["escalated", "Escalated", "text-esc"],
  ] as const)("renders %s as %s with its own colour", (status, label, cls) => {
    const { container } = render(<StatusBadge status={status} />);
    const badge = container.querySelector(`[data-status="${status}"]`)!;
    expect(badge).toHaveTextContent(label);
    expect(badge.className).toContain(cls);
  });

  it("gives every status a distinct glyph, not just a colour", () => {
    const glyphs = (["balanced", "exception", "pending_review", "escalated"] as const).map((s) => {
      const { container, unmount } = render(<StatusBadge status={s} />);
      const g = container.querySelector("[aria-hidden]")!.textContent;
      unmount();
      return g;
    });
    expect(new Set(glyphs).size).toBe(4);
  });

  it("shows an unknown status neutrally instead of crashing", () => {
    render(<StatusBadge status="reticulating" />);
    expect(screen.getByText("reticulating")).toBeInTheDocument();
  });
});
