import type { Obligation } from "./types";

/**
 * How soon a deadline is, from the API's own days_left against the business
 * clock: overdue, within a month, within a quarter, later.
 */
export type Urgency = "overdue" | "soon" | "quarter" | "later";

export const URGENCY_ORDER: Urgency[] = ["overdue", "soon", "quarter", "later"];
export const URGENCY_LABEL: Record<Urgency, string> = { overdue: "Overdue", soon: "Within 30 days", quarter: "Within 90 days", later: "Later" };

export function urgencyOf(daysLeft: number): Urgency {
  if (daysLeft < 0) return "overdue";
  if (daysLeft <= 30) return "soon";
  if (daysLeft <= 90) return "quarter";
  return "later";
}

export interface MonthGroup {
  /** YYYY-MM */
  month: string;
  obligations: Obligation[];
}

/** Deadlines in the order they fall due, grouped by the month they fall in. */
export function groupByMonth(obligations: Obligation[]): MonthGroup[] {
  const sorted = [...obligations].sort((a, b) => a.due_date.localeCompare(b.due_date) || a.days_left - b.days_left);
  const groups: MonthGroup[] = [];
  for (const o of sorted) {
    const month = o.due_date.slice(0, 7);
    const last = groups[groups.length - 1];
    if (last && last.month === month) last.obligations.push(o);
    else groups.push({ month, obligations: [o] });
  }
  return groups;
}

/** How many fall in each urgency band. */
export function countByUrgency(obligations: Obligation[]): Record<Urgency, number> {
  const c: Record<Urgency, number> = { overdue: 0, soon: 0, quarter: 0, later: 0 };
  for (const o of obligations) c[urgencyOf(o.days_left)]++;
  return c;
}
