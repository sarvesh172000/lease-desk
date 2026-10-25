"use client";

import { motion, useReducedMotion } from "framer-motion";
import { Lock } from "lucide-react";
import { journalTotals } from "@/lib/journal";
import { ledger, money } from "@/lib/format";
import type { JournalLine } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EmptyState } from "./ui/States";

/**
 * Proposed entries as a two-column ledger, with the balance assertion in plain
 * sight. The lines and the `balanced` flag come from the engine; the table only
 * totals them (in cents) and shouts if the two disagree.
 */
export function JournalEntryTable({
  entries,
  balanced,
  emptyMessage = "No entries proposed.",
  reveal = false,
  dense = false,
}: {
  entries: JournalLine[];
  /** The engine's own verdict (§16 `investigation.balanced`). */
  balanced?: boolean;
  emptyMessage?: string;
  /** Lines arrive one by one, then the balance seal locks in (the investigation's last beat). */
  reveal?: boolean;
  /** Narrow panels: smaller type and money columns sized to the figures. */
  dense?: boolean;
}) {
  const reduce = useReducedMotion();
  if (!entries.length) {
    return <EmptyState title={emptyMessage}>Nothing will post until an investigation proposes entries.</EmptyState>;
  }
  const t = journalTotals(entries);
  const disagree = balanced !== undefined && balanced !== t.ties;
  const ok = t.ties && !disagree;
  const play = reveal && !reduce;
  const ROW = 0.22;
  const sealDelay = play ? entries.length * ROW + 0.25 : 0;

  return (
    <div>
      <table className={cn("w-full border-collapse", dense ? "text-sm" : "text-[0.95rem]")} aria-label="Proposed journal entries">
        <thead>
          <tr className="table-head">
            <th className={cn("pr-2 font-semibold", dense ? "py-1.5 pl-1.5" : "py-2 pl-3")}>Account</th>
            <th className={cn("text-right font-semibold", dense ? "px-1.5 py-1.5" : "w-40 px-3 py-2")}>Debit</th>
            <th className={cn("text-right font-semibold", dense ? "px-1.5 py-1.5" : "w-40 px-3 py-2")}>Credit</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((l, i) => (
            <motion.tr
              key={`${l.account}:${l.debit}:${l.credit}`}
              className="border-b border-line/70"
              initial={play ? { opacity: 0, x: -8 } : false}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, delay: play ? i * ROW : 0, ease: [0.2, 0.8, 0.2, 1] }}
            >
              <td className={cn("py-2 pr-2", l.credit > 0 && l.debit === 0 ? (dense ? "pl-5 text-ink-soft" : "pl-8 text-ink-soft") : dense ? "pl-1.5" : "pl-3")}>{l.account}</td>
              <td className={cn("num whitespace-nowrap py-2 text-right", dense ? "px-1.5" : "px-3")} data-testid="debit">
                {ledger(l.debit)}
              </td>
              <td className={cn("num whitespace-nowrap py-2 text-right", dense ? "px-1.5" : "px-3")} data-testid="credit">
                {ledger(l.credit)}
              </td>
            </motion.tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-ink/80 font-semibold">
            <td className={cn("py-2 pr-2", dense ? "pl-1.5" : "pl-3")}>Total</td>
            <td className={cn("num whitespace-nowrap py-2 text-right underline decoration-double underline-offset-4", dense ? "px-1.5" : "px-3")} data-testid="total-debit">
              {money(t.debit)}
            </td>
            <td className={cn("num whitespace-nowrap py-2 text-right underline decoration-double underline-offset-4", dense ? "px-1.5" : "px-3")} data-testid="total-credit">
              {money(t.credit)}
            </td>
          </tr>
        </tfoot>
      </table>

      <motion.div
        key={ok ? "ok" : "bad"}
        initial={reduce ? false : play ? { opacity: 0, scale: 0.96 } : { opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={reduce ? { duration: 0 } : { duration: 0.35, ease: [0.22, 1, 0.36, 1], delay: sealDelay }}
        role="status"
        data-testid="balance-assertion"
        data-balanced={ok ? "true" : "false"}
        className={cn(
          "mt-3 flex items-center gap-3 rounded-md border px-3 py-2 text-sm",
          ok ? "border-ok-line bg-ok-soft text-ok" : "border-bad-line bg-bad-soft text-bad",
        )}
      >
        <motion.span
          aria-hidden
          initial={false}
          animate={ok && !reduce ? { scale: [1, 1.3, 1] } : { scale: 1 }}
          transition={{ duration: 0.4, ease: "easeOut", delay: sealDelay + 0.15 }}
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-current text-xs font-bold"
        >
          {ok ? <Lock className="h-3.5 w-3.5" strokeWidth={2.25} /> : "≠"}
        </motion.span>
        {ok ? (
          <span>
            <strong>Balanced: debits = credits</strong> at <span className="num font-semibold">{money(t.debit)}</span> each side.
          </span>
        ) : !t.ties ? (
          <span>
            <strong>Out of balance</strong> by <span className="num font-semibold">{money(Math.abs(t.differenceCents) / 100)}</span>
            {" "}({t.differenceCents > 0 ? "debits" : "credits"} higher). These entries cannot post.
          </span>
        ) : (
          <span>
            <strong>Mismatch:</strong> the lines tie but the engine reported <code>balanced: false</code>. Do not approve.
          </span>
        )}
      </motion.div>
    </div>
  );
}
