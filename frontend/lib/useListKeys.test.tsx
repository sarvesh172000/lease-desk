import { act, fireEvent, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useListKeys } from "./useListKeys";

const press = (key: string, target: Element | Document = document) => act(() => void fireEvent.keyDown(target, { key }));

describe("useListKeys", () => {
  it("J and K move the highlight within the list, starting from the first row", () => {
    const { result } = renderHook(() => useListKeys({ count: 3 }));
    expect(result.current.index).toBe(-1);
    press("j");
    expect(result.current.index).toBe(0);
    press("j");
    press("j");
    press("j"); // past the end stays on the last row
    expect(result.current.index).toBe(2);
    press("k");
    expect(result.current.index).toBe(1);
    press("k");
    press("k"); // past the start stays on the first row
    expect(result.current.index).toBe(0);
  });

  it("Enter opens the highlighted row, and does nothing before one is highlighted", () => {
    const onOpen = vi.fn();
    renderHook(() => useListKeys({ count: 2, onOpen }));
    press("Enter");
    expect(onOpen).not.toHaveBeenCalled();
    press("j");
    press("j");
    press("Enter");
    expect(onOpen).toHaveBeenCalledWith(1);
  });

  it("A and H act on the highlighted row only when a handler is given", () => {
    const onApprove = vi.fn();
    const onHold = vi.fn();
    const { rerender } = renderHook((p: { approve: boolean }) => useListKeys({ count: 2, onApprove: p.approve ? onApprove : undefined, onHold }), {
      initialProps: { approve: false },
    });
    press("j");
    press("a");
    expect(onApprove).not.toHaveBeenCalled(); // not allowed: nothing happens
    press("h");
    expect(onHold).toHaveBeenCalledWith(0);
    rerender({ approve: true });
    press("a");
    expect(onApprove).toHaveBeenCalledWith(0);
  });

  it("ignores keys typed into a field or inside a dialog", () => {
    const onHold = vi.fn();
    const { result } = renderHook(() => useListKeys({ count: 2, onHold }));
    press("j");
    const input = document.createElement("input");
    document.body.appendChild(input);
    press("j", input);
    press("h", input);
    expect(result.current.index).toBe(0);
    expect(onHold).not.toHaveBeenCalled();
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    const inner = document.createElement("button");
    dialog.appendChild(inner);
    document.body.appendChild(dialog);
    press("h", inner);
    expect(onHold).not.toHaveBeenCalled();
    input.remove();
    dialog.remove();
  });

  it("clamps the highlight when the list shrinks", () => {
    const { result, rerender } = renderHook((p: { count: number }) => useListKeys({ count: p.count }), { initialProps: { count: 3 } });
    press("j");
    press("j");
    press("j");
    expect(result.current.index).toBe(2);
    rerender({ count: 1 });
    expect(result.current.index).toBe(0);
  });
});
