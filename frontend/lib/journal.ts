import type { JournalLine } from "./types";

/**
 * Totals for display and the balance assertion. Summed in integer cents so
 * 443255.70 + 4624.74 never drifts by a float epsilon. This is a check on the
 * engine's output, not accounting: the entries themselves come from the API.
 */
export function journalTotals(lines: JournalLine[]) {
  let debitCents = 0;
  let creditCents = 0;
  for (const l of lines) {
    debitCents += Math.round((l.debit || 0) * 100);
    creditCents += Math.round((l.credit || 0) * 100);
  }
  return {
    debit: debitCents / 100,
    credit: creditCents / 100,
    differenceCents: debitCents - creditCents,
    ties: debitCents === creditCents,
  };
}
