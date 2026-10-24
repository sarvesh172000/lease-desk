import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SECTION_16_EXCEPTION_DETAIL } from "@/lib/fixtures";
import { JournalEntryTable } from "./JournalEntryTable";

const inv = SECTION_16_EXCEPTION_DETAIL.investigation!;

describe("JournalEntryTable", () => {
  it("shows the §16 entries as balanced with totals of $447,880.44", () => {
    render(<JournalEntryTable entries={inv.entries} balanced={inv.balanced} />);
    expect(screen.getAllByRole("row")).toHaveLength(1 + 4 + 1); // head, lines, total
    expect(screen.getByTestId("total-debit")).toHaveTextContent("$447,880.44");
    expect(screen.getByTestId("total-credit")).toHaveTextContent("$447,880.44");
    const assertion = screen.getByTestId("balance-assertion");
    expect(assertion).toHaveAttribute("data-balanced", "true");
    expect(assertion).toHaveTextContent(/Balanced\. Debits equal credits at \$447,880\.44/);
  });

  it("right-aligns amounts in tabular figures and leaves zero cells blank", () => {
    render(<JournalEntryTable entries={inv.entries} balanced />);
    const debits = screen.getAllByTestId("debit");
    expect(debits[0]).toHaveTextContent(/^$/); // Lease liability: credit only
    expect(debits[1]).toHaveTextContent("443,255.70");
    for (const cell of [...debits, ...screen.getAllByTestId("credit")]) {
      expect(cell.className).toMatch(/\bnum\b/);
      expect(cell.className).toMatch(/text-right/);
    }
  });

  it("flags an unbalanced set with the difference and which side is higher", () => {
    const lines = [
      { account: "ROU asset", debit: 100.1, credit: 0 },
      { account: "Lease liability", debit: 0, credit: 100.0 },
    ];
    render(<JournalEntryTable entries={lines} balanced={false} />);
    const assertion = screen.getByTestId("balance-assertion");
    expect(assertion).toHaveAttribute("data-balanced", "false");
    expect(assertion).toHaveTextContent(/Out of balance by \$0\.10 \(debits higher\)/);
  });

  it("does not trust a balanced=true flag when the lines do not tie", () => {
    const lines = [
      { account: "ROU asset", debit: 50, credit: 0 },
      { account: "Lease liability", debit: 0, credit: 49.99 },
    ];
    render(<JournalEntryTable entries={lines} balanced />);
    expect(screen.getByTestId("balance-assertion")).toHaveAttribute("data-balanced", "false");
  });

  it("warns when lines tie but the engine says unbalanced", () => {
    render(<JournalEntryTable entries={inv.entries} balanced={false} />);
    const a = screen.getByTestId("balance-assertion");
    expect(a).toHaveAttribute("data-balanced", "false");
    expect(within(a).getByText(/Mismatch/)).toBeInTheDocument();
  });

  it("sums in cents, so float drift never fakes an imbalance", () => {
    const lines = [
      { account: "A", debit: 0.1, credit: 0 },
      { account: "B", debit: 0.2, credit: 0 },
      { account: "C", debit: 0, credit: 0.3 },
    ];
    render(<JournalEntryTable entries={lines} balanced />);
    expect(screen.getByTestId("balance-assertion")).toHaveAttribute("data-balanced", "true");
  });

  it("renders an empty state when nothing is proposed", () => {
    render(<JournalEntryTable entries={[]} />);
    expect(screen.getByText("No entries proposed.")).toBeInTheDocument();
    expect(screen.queryByTestId("balance-assertion")).toBeNull();
  });
});
