/**
 * A column that says the same thing on every row says nothing: "Conf." at 56%
 * down the whole queue, or "—" in every cell, is noise on a projector. These
 * helpers decide which columns earn their place for the rows on screen.
 */

export interface ColumnSpec<T> {
  key: string;
  /** The value the column would show; null/undefined/"" count as empty. */
  get: (row: T) => unknown;
  /** Keep the column whatever the rows say (the title, the amount). */
  always?: boolean;
}

const EMPTY = new Set<unknown>([null, undefined, "", "—"]);
const isEmpty = (v: unknown) => EMPTY.has(v) || (typeof v === "number" && Number.isNaN(v));

/** True when the column is empty on every row, or identical on every row (with 2+ rows). */
export function isUniform<T>(rows: T[], col: ColumnSpec<T>): boolean {
  if (col.always || rows.length === 0) return false;
  const values = rows.map(col.get);
  if (values.every(isEmpty)) return true;
  if (rows.length < 2) return false;
  const first = JSON.stringify(values[0]);
  return values.every((v) => JSON.stringify(v) === first);
}

/** The columns worth showing for these rows, in the order given. */
export function visibleColumns<T>(rows: T[], cols: ColumnSpec<T>[]): ColumnSpec<T>[] {
  return cols.filter((c) => !isUniform(rows, c));
}

/** The keys of the columns that were hidden, for a one-line note under the table. */
export function hiddenColumns<T>(rows: T[], cols: ColumnSpec<T>[]): string[] {
  return cols.filter((c) => isUniform(rows, c)).map((c) => c.key);
}
