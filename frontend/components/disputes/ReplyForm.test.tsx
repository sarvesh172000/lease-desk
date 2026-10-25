import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EMPTY_DRAFT, ReplyForm, toReply, validateReply } from "./ReplyForm";

const draft = (over: Partial<typeof EMPTY_DRAFT>) => ({ ...EMPTY_DRAFT, ...over });

describe("dispute reply validation", () => {
  it("a partial credit needs an amount strictly between zero and the disputed amount, and a memo", () => {
    expect(validateReply(draft({ outcome: "partial_credit" }), 4820)).toMatchObject({ granted: expect.any(String), credit_memo_ref: expect.any(String) });
    expect(validateReply(draft({ outcome: "partial_credit", granted: "0", credit_memo_ref: "CM-1" }), 4820).granted).toMatch(/More than/);
    expect(validateReply(draft({ outcome: "partial_credit", granted: "4820", credit_memo_ref: "CM-1" }), 4820).granted).toMatch(/Less than the \$4,820\.00/);
    expect(validateReply(draft({ outcome: "partial_credit", granted: "abc", credit_memo_ref: "CM-1" }), 4820).granted).toBeTruthy();
    expect(validateReply(draft({ outcome: "partial_credit", granted: "1500.50", credit_memo_ref: "CM-1" }), 4820)).toEqual({});
  });

  it("a full credit needs only the memo; a refusal needs the reason; an acknowledgement needs nothing", () => {
    expect(validateReply(draft({ outcome: "full_credit" }), 4820)).toEqual({ credit_memo_ref: expect.any(String) });
    expect(validateReply(draft({ outcome: "full_credit", credit_memo_ref: "CM-9" }), 4820)).toEqual({});
    expect(validateReply(draft({ outcome: "refused" }), 4820)).toEqual({ reason: expect.any(String) });
    expect(validateReply(draft({ outcome: "acknowledged" }), 4820)).toEqual({});
    expect(validateReply(draft({ outcome: "acknowledged", received_on: "yesterday" }), 4820)).toEqual({ received_on: expect.any(String) });
  });

  it("sends only the fields the outcome uses, with the full credit set to the disputed amount", () => {
    expect(toReply(draft({ outcome: "full_credit", credit_memo_ref: " CM-9 " }), 4820)).toEqual({ outcome: "full_credit", granted: 4820, credit_memo_ref: "CM-9" });
    expect(toReply(draft({ outcome: "partial_credit", granted: "1500.50", credit_memo_ref: "CM-1", received_on: "2026-07-10" }), 4820)).toEqual({ outcome: "partial_credit", granted: 1500.5, credit_memo_ref: "CM-1", received_on: "2026-07-10" });
    expect(toReply(draft({ outcome: "refused", reason: "Suite 118 is yours" }), 4820)).toEqual({ outcome: "refused", reason: "Suite 118 is yours" });
    expect(toReply(draft({ outcome: "acknowledged", body: "Received." }), 4820)).toEqual({ outcome: "acknowledged", body: "Received." });
  });

  it("does not open the confirm until the form is valid", () => {
    const onSubmit = vi.fn();
    render(<ReplyForm disputed={4820} outcomes={["acknowledged", "partial_credit", "full_credit", "refused"]} onSubmit={onSubmit} pending={false} error={null} />);
    fireEvent.change(screen.getByLabelText("The landlord"), { target: { value: "partial_credit" } });
    fireEvent.click(screen.getByTestId("record-reply"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText(/The amount credited/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Amount credited"), { target: { value: "1500" } });
    fireEvent.change(screen.getByLabelText("Credit memo ref"), { target: { value: "CM-2026-07" } });
    fireEvent.click(screen.getByTestId("record-reply"));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("credits $1,500.00 of the $4,820.00 disputed");
    expect(dialog).toHaveTextContent("The remaining $3,320.00 stays open.");
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
