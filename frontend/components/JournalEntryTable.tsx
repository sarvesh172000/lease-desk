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
}: {
  entries: JournalLine[];
  /** The engine's own verdict (§16 `investigation.balanced`). */
  balanced?: boolean;
  emptyMessage?: string;
}) {
  if (!entries.length) {
    return <EmptyState title={emptyMessage}>Nothing will post until an investigation proposes entries.</EmptyState>;
  }
  const t = journalTotals(entries);
  const disagree = balanced !== undefined && balanced !== t.ties;
  const ok = t.ties && !disagree;

  return (
    <div>
      <table className="w-full border-collapse text-[0.95rem]" aria-label="Proposed journal entries">
        <thead>
          <tr className="table-head">
            <th className="py-2 pl-3 pr-2 font-semibold">Account</th>
            <th className="w-40 px-3 py-2 text-right font-semibold">Debit</th>
            <th className="w-40 px-3 py-2 text-right font-semibold">Credit</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((l, i) => (
            <tr key={i} className="border-b border-line/70">
              <td className={cn("py-2 pr-2", l.credit > 0 && l.debit === 0 ? "pl-8 text-ink-soft" : "pl-3")}>{l.account}</td>
              <td className="num px-3 py-2 text-right" data-testid="debit">
                {ledger(l.debit)}
              </td>
              <td className="num px-3 py-2 text-right" data-testid="credit">
                {ledger(l.credit)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-ink/80 font-semibold">
            <td className="py-2 pl-3 pr-2">Total</td>
            <td className="num px-3 py-2 text-right underline decoration-double underline-offset-4" data-testid="total-debit">
              {money(t.debit)}
            </td>
            <td className="num px-3 py-2 text-right underline decoration-double underline-offset-4" data-testid="total-credit">
              {money(t.credit)}
            </td>
          </tr>
        </tfoot>
      </table>

      <div
        role="status"
        data-testid="balance-assertion"
        data-balanced={ok ? "true" : "false"}
        className={cn(
          "mt-3 flex items-center gap-3 rounded-md border px-3 py-2 text-sm",
          ok ? "border-ok-line bg-ok-soft text-ok" : "border-bad-line bg-bad-soft text-bad",
        )}
      >
        <span aria-hidden className="flex h-5 w-5 items-center justify-center rounded-full border border-current text-xs font-bold">
          {ok ? "=" : "≠"}
        </span>
        {ok ? (
          <span>
            <strong>Balanced.</strong> Debits equal credits at <span className="num font-semibold">{money(t.debit)}</span>.
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
      </div>
    </div>
  );
}
