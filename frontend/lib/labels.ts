/**
 * Readable names for the API's keys, in one place, so every screen says
 * "CAM estimate" and "Daly City, Suite 210" rather than `cam_estimate` and
 * `CLINIC-01`. Ids stay available as secondary text; these never replace them
 * in data, only on screen.
 */

const CHARGE_LABEL: Record<string, string> = {
  base_rent: "Base rent",
  cam_estimate: "CAM estimate",
  cam_reconciliation: "CAM reconciliation",
  operating_expense: "Operating expenses",
  property_tax: "Property tax",
  tax: "Property tax",
  insurance: "Insurance",
  utilities: "Utilities",
  janitorial: "Janitorial",
  late_fee: "Late fee",
  security_deposit: "Security deposit",
  landlord_charge: "Landlord charge",
};

/** base_rent → "Base rent"; an unknown code reads as words, never as a key. */
export function chargeLabel(code: string | null | undefined): string {
  if (!code) return "Charge";
  if (CHARGE_LABEL[code]) return CHARGE_LABEL[code];
  const words = code.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Charge";
}

const ROOT_CAUSE_LABEL: Record<string, string> = {
  amendment: "Executed amendment",
  unexplained: "Unexplained",
  duplicate: "Billed twice",
  escalation: "Escalation",
  wrong_suite: "Suite not leased",
};

/** amendment → "Executed amendment" */
export function rootCauseLabel(code: string | null | undefined): string {
  if (!code) return "—";
  return ROOT_CAUSE_LABEL[code] ?? chargeLabel(code);
}

const BRAND = /^Northbay(?: Physical Therapy| PT)\s*[—–-]\s*/i;

/**
 * "Northbay PT — Daly City — Suite 210" → "Daly City, Suite 210".
 * The brand is the same on every clinic, so only the place tells them apart.
 */
export function placeLabel(location: string | null | undefined): string | null {
  if (!location) return null;
  const parts = location
    .replace(BRAND, "")
    .split(/\s+[—–]\s+/)
    .map((p) => p.trim())
    .filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}

/** A clinic in words, falling back to its id when the location is unknown. */
export function clinicLabel(location: string | null | undefined, clinicId?: string | null): string {
  const place = placeLabel(location);
  return place ? `Northbay PT ${place}` : clinicId ?? "Unknown clinic";
}

const monthLongFmt = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" });

/** 2026-07-01 → "July 2026" */
export function monthLong(d: string | null | undefined): string {
  if (!d) return "—";
  const t = Date.parse(d.length === 10 ? `${d}T00:00:00Z` : d.length === 7 ? `${d}-01T00:00:00Z` : d);
  return Number.isNaN(t) ? d : monthLongFmt.format(new Date(t));
}

/** Trust ranks as defined in backend/app/agents/trust.py (1 = most authoritative). */
export const TRUST_RANKS: { rank: number; short: string; long: string }[] = [
  { rank: 1, short: "Executed amendment", long: "Executed amendment signed by both parties" },
  { rank: 2, short: "Original lease", long: "Original executed lease" },
  { rank: 3, short: "Authorized rep", long: "Authorized representative, in writing" },
  { rank: 4, short: "Property manager", long: "Property management, no stated authority" },
  { rank: 5, short: "Invoice", long: "Landlord invoice or statement" },
  { rank: 6, short: "Payment history", long: "Payment history" },
];
