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

const ACTION_LABEL: Record<string, string> = {
  create: "Created",
  propose: "Proposed",
  propose_hold: "Proposed hold",
  propose_schedule: "Proposed schedule",
  approve: "Approved",
  hold: "Held",
  reject: "Rejected",
  close: "Closed",
  resume: "Resumed",
  post: "Posted to ledger",
  ask: "Asked",
  answer: "Answered",
  confirm: "Confirmed",
  attach_evidence: "Attached evidence",
  create_exception: "Created exception",
  investigate: "Investigated",
  release_batch: "Released batch",
  pay_as_billed: "Paid as billed",
  record_reply: "Recorded reply",
  demo_reset: "Reset the demo",
};

/** approve → "Approved"; release_batch → "Released batch". An unknown action reads as words. */
export function actionLabel(action: string | null | undefined): string {
  if (!action) return "—";
  if (ACTION_LABEL[action]) return ACTION_LABEL[action];
  const words = action.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A refused attempt reads as what was tried: "tried to approve". */
export function attemptLabel(action: string | null | undefined): string {
  const l = actionLabel(action);
  const verb: Record<string, string> = { Approved: "approve", Held: "hold", Rejected: "reject", Closed: "close", "Posted to ledger": "post to the ledger", "Released batch": "release the batch", Created: "create", Proposed: "propose" };
  return `tried to ${verb[l] ?? l.toLowerCase()}`;
}

export type ActorKind = "person" | "agent" | "system";

/** Who an actor id is: PER-… people, agent:… agents, system:… the gateway and the engine. */
export function actorKind(actorId: string): ActorKind {
  if (actorId.startsWith("agent:")) return "agent";
  if (actorId.startsWith("system") || actorId === "engine" || actorId === "gateway") return "system";
  return "person";
}
