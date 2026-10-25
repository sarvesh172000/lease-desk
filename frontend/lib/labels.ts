import type { Actor } from "./types";
/**
 * Readable names for the API's keys, in one place, so every screen says
 * "CAM estimate" and "Daly City, Suite 210" rather than `cam_estimate` and
 * `STORE-01`. Ids stay available as secondary text; these never replace them
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

const BRAND = /^Northbay(?: Coffee| Physical Therapy| PT)\s*[—–-]\s*/i;

/**
 * "Northbay Coffee — Daly City — Suite 210" → "Daly City, Suite 210".
 * The brand is the same on every store, so only the place tells them apart.
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

/** A store in words, falling back to its id when the location is unknown. */
export function clinicLabel(location: string | null | undefined, clinicId?: string | null): string {
  const place = placeLabel(location);
  return place ? `Northbay Coffee ${place}` : clinicId ?? "Unknown store";
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

const TERM_LABEL: Record<string, string> = {
  commencement: "Commencement",
  expiration: "Expiration",
  rentable_sf: "Rentable area",
  proportionate_share_pct: "Proportionate share",
  base_rent_monthly: "Base rent, monthly",
  escalation_kind: "Escalation",
  escalation_amount: "Escalation amount",
  cam_estimate_psf_annual: "CAM estimate, per sf a year",
  cam_cap: "CAM cap",
  security_deposit: "Security deposit",
  renewal_count: "Renewal options",
  renewal_years: "Renewal term",
  renewal_notice_days: "Renewal notice",
  authorized_representative: "Authorized representative",
  cam_audit_window: "CAM audit window",
  late_fee: "Late fee",
};

/** base_rent_monthly → "Base rent, monthly" */
export function termLabel(field: string | null | undefined): string {
  if (!field) return "—";
  return TERM_LABEL[field] ?? chargeLabel(field);
}

const REGION_LABEL: Record<string, string> = { "REG-BAY": "Bay Area", "REG-SOCAL": "SoCal", "REG-DESERT": "Desert" };

/** REG-BAY → "Bay Area"; an unknown region reads as its id. */
export function regionLabel(regionId: string | null | undefined): string {
  if (!regionId) return "Unassigned";
  return REGION_LABEL[regionId] ?? regionId.replace(/^REG-/, "");
}

const OBLIGATION_LABEL: Record<string, string> = {
  renewal_notice: "Renewal notice",
  cam_audit_window: "CAM audit window",
  deposit_return: "Deposit return",
  expiration: "Expiration",
};

export function obligationLabel(kind: string | null | undefined): string {
  if (!kind) return "—";
  return OBLIGATION_LABEL[kind] ?? chargeLabel(kind);
}

/** "abstraction:llm" → read by Claude; "abstraction:generator" → the generator's terms. */
export function extractorLabel(agent: string | null | undefined): { short: string; long: string; kind: "llm" | "generator" | "unknown" } {
  if (agent === "abstraction:llm") return { short: "Read by Claude", long: "Read by Claude from the lease PDF (abstraction:llm), each term with its quote and page", kind: "llm" };
  if (agent === "abstraction:generator") return { short: "Generator", long: "Taken from the generated lease terms (abstraction:generator), not read from the PDF", kind: "generator" };
  return { short: "Source unknown", long: "No extraction path recorded for these terms", kind: "unknown" };
}

const DISPUTE_STATUS_LABEL: Record<string, string> = {
  drafted: "Drafted",
  sent: "Sent",
  acknowledged: "Acknowledged",
  credited: "Credited",
  partially_credited: "Partly credited",
  refused: "Refused",
};

export function disputeStatusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  return DISPUTE_STATUS_LABEL[status] ?? chargeLabel(status);
}

const POLICY_STATUS_LABEL: Record<string, string> = { proposed: "Proposed", approved: "Approved", rejected: "Rejected", retired: "Retired" };

export function policyStatusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  return POLICY_STATUS_LABEL[status] ?? chargeLabel(status);
}

/**
 * A policy's title: its description when it has one; otherwise its name
 * read as words ("onboarding:LL-PACIFIC:base_rent:unchanged" → "Base rent ·
 * unchanged · LL-PACIFIC"), never the raw key.
 */
export function policyTitle(p: { name: string; description?: string | null }): string {
  const d = p.description?.trim();
  if (d) return d;
  const parts = p.name.split(":").filter(Boolean);
  if (parts.length >= 4 && parts[0] === "onboarding") {
    const [, landlord, charge, ...rest] = parts;
    return `${chargeLabel(charge)} · ${rest.join(" ").replace(/_/g, " ")} · ${landlord}`;
  }
  return parts.map((x) => x.replace(/[_-]+/g, " ")).join(" · ").replace(/^./, (c) => c.toUpperCase());
}

const POLICY_ACTION_LABEL: Record<string, string> = { approve: "Approve", hold: "Hold", dispute: "Dispute" };

export function policyActionLabel(action: string | null | undefined): string {
  if (!action) return "No action";
  return POLICY_ACTION_LABEL[action] ?? chargeLabel(action);
}

const CHECKER_RULE_LABEL: Record<string, string> = {
  amount: "the amount against the schedule",
  operating_expense: "the operating expense estimate against the lease",
  duplicate: "a duplicate invoice",
  escalation: "the escalation step",
  premises: "the premises the lease demises",
};

/** amount → "the amount against the schedule"; the checker's rule names as phrases. */
export function checkerRuleLabel(rule: string): string {
  return CHECKER_RULE_LABEL[rule] ?? rule.replace(/[_-]+/g, " ");
}

/**
 * A landlord's name from an id, when something on screen has told us it
 * (a dispute's landlord_name, a policy's own description); the id otherwise.
 */
export function landlordName(id: string | null | undefined, names: Record<string, string>): string {
  if (!id) return "any landlord";
  return names[id] ?? id;
}

/** "Pay base rent from Pacific Crest Properties LLC as billed …" → { "LL-PACIFIC": "Pacific Crest Properties LLC" } */
export function landlordNamesFromDescription(landlordId: string | null | undefined, description: string | null | undefined): Record<string, string> {
  if (!landlordId || !description) return {};
  // the name runs up to its legal suffix; "Properties" and "Partners" are part of names, not suffixes
  const m = /\bfrom ([A-Z][^,.]*?(?:LLC|L\.P\.|LP|Inc\.?|Ltd\.?|Trust|Company|Co\.))/.exec(description);
  return m ? { [landlordId]: m[1].trim() } : {};
}

/** Agents and the gateway are actors in the audit trail, never people you can sign in as. */
export function isPerson(a: Actor): boolean {
  return a.role !== "system" && a.role !== "agent" && !a.id.startsWith("system:") && !a.id.startsWith("agent:");
}
