import type { Status } from "./types";

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usd0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const num2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** $1,234.56; negatives as ($1,234.56), the accounting convention. */
export function money(v: number | null | undefined, opts: { parens?: boolean; whole?: boolean } = {}): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const f = opts.whole ? usd0 : usd;
  if (v < 0 && opts.parens !== false) return `(${f.format(-v)})`;
  return f.format(v);
}

/** Signed change: +$516.66 / −$2,226.65 */
export function signedMoney(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v === 0) return usd.format(0);
  return `${v > 0 ? "+" : "−"}${usd.format(Math.abs(v))}`;
}

/** Ledger cell: blank for zero, 1,234.56 otherwise (no currency symbol). */
export function ledger(v: number): string {
  return v === 0 ? "" : num2.format(v);
}

export function pct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${Math.round(v * 100)}%`;
}

const monthFmt = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
const dayFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const tsFmt = new Intl.DateTimeFormat("en-US", {
  month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: "UTC",
});

function parse(d: string): Date | null {
  const t = Date.parse(d.length === 10 ? `${d}T00:00:00Z` : d);
  return Number.isNaN(t) ? null : new Date(t);
}

/** 2026-07-01 → Jul 2026 */
export function period(d: string | null | undefined): string {
  const p = d ? parse(d) : null;
  return p ? monthFmt.format(p) : d ?? "—";
}
/** 2026-06-18 → Jun 18, 2026 */
export function day(d: string | null | undefined): string {
  const p = d ? parse(d) : null;
  return p ? dayFmt.format(p) : d ?? "—";
}
export function timestamp(d: string | null | undefined): string {
  const p = d ? parse(d) : null;
  return p ? `${tsFmt.format(p)} UTC` : d ?? "—";
}

export const STATUS_LABEL: Record<Status, string> = {
  balanced: "Balanced",
  exception: "Exception",
  pending_review: "Pending review",
  escalated: "Escalated",
};

/** cam_estimate → CAM estimate */
export function humanize(code: string | null | undefined): string {
  if (!code) return "—";
  const special: Record<string, string> = {
    cam_estimate: "CAM estimate",
    base_rent: "Base rent",
    amendment: "Amendment",
    unexplained: "Unexplained",
    regional_manager: "Regional manager",
    ap_clerk: "AP clerk",
    controller: "Controller",
    auditor: "Auditor",
  };
  if (special[code]) return special[code];
  const s = code.replace(/[_-]+/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
