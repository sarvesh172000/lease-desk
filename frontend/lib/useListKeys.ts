"use client";

import { useCallback, useEffect, useState } from "react";

export interface ListKeys {
  /** The highlighted row, or -1 when none. */
  index: number;
  setIndex: (i: number) => void;
}

/** Typing in a field, or a dialog being open, must never move the queue. */
function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  if (el.closest?.("[role=dialog]")) return true;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

/**
 * J/K move down and up a list, Enter opens the highlighted row, and A or H
 * act on it. The handlers only fire for a highlighted row; what A and H may
 * do is the caller's to decide (the server's allowed actions), and both
 * should confirm before anything posts.
 */
export function useListKeys({
  count,
  onOpen,
  onApprove,
  onHold,
  enabled = true,
}: {
  count: number;
  onOpen?: (index: number) => void;
  onApprove?: (index: number) => void;
  onHold?: (index: number) => void;
  enabled?: boolean;
}): ListKeys {
  const [index, setIndex] = useState(-1);

  // a shorter list than the highlight points at: fall back to its last row
  useEffect(() => {
    if (index >= count) setIndex(count - 1);
  }, [count, index]);

  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (!enabled || e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      if (count === 0) return;
      switch (e.key) {
        case "j":
        case "J":
        case "ArrowDown":
          e.preventDefault();
          setIndex((i) => Math.min(count - 1, i + 1));
          break;
        case "k":
        case "K":
        case "ArrowUp":
          e.preventDefault();
          setIndex((i) => Math.max(0, i < 0 ? 0 : i - 1));
          break;
        case "Enter":
          if (index >= 0) {
            e.preventDefault();
            onOpen?.(index);
          }
          break;
        case "a":
        case "A":
          if (index >= 0 && onApprove) {
            e.preventDefault();
            onApprove(index);
          }
          break;
        case "h":
        case "H":
          if (index >= 0 && onHold) {
            e.preventDefault();
            onHold(index);
          }
          break;
      }
    },
    [enabled, count, index, onOpen, onApprove, onHold],
  );

  useEffect(() => {
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onKey]);

  return { index, setIndex };
}
