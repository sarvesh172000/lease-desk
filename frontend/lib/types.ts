/**
 * Types for the API contract in docs/DESIGN.md §16 (frozen).
 *
 * Fields marked EXTENSION are not in §16; the UI renders without them and the
 * backend can add them later. They are listed in frontend/README.md.
 */

export type Status = "balanced" | "exception" | "pending_review" | "escalated";

/** GET /api/leases */
export interface LeaseSummary {
  lease_id: string;
  clinic_id: string;
  location: string;
  lessor: string;
  status: Status;
  monthly_rent: number;
  liability: number;
  end: string;
}

/** GET /api/exceptions */
export interface ExceptionSummary {
  exception_id: string;
  lease_id: string;
  clinic_id: string;
  period: string;
  charge_type: string;
  expected: number;
  actual: number;
  delta: number;
  status: Status;
  confidence: number;
}

/** [x0, y0, x1, y1] in PDF points, origin top-left. */
export type Box = [number, number, number, number];

export interface Evidence {
  doc_id: string;
  date: string;
  source: string;
  trust_rank: number;
  quote: string;
  page: number;
  box: Box;
}

export interface JournalLine {
  account: string;
  debit: number;
  credit: number;
}

export interface Investigation {
  root_cause: string;
  confidence: number;
  explains_variance: boolean;
  evidence: Evidence[];
  liability_before: number | null;
  liability_after: number | null;
  rou_before: number | null;
  rou_after: number | null;
  entries: JournalLine[];
  balanced: boolean;
  /** EXTENSION: deltas as computed by the engine (the SSE `remeasured` event carries them today). */
  liability_delta?: number;
  rou_delta?: number;
}

/** EXTENSION: a boxed region on a stored document page. */
export interface DocCitation {
  doc_id: string;
  page: number;
  box: Box;
}

/** EXTENSION: the billed invoice line under review. */
export interface InvoiceLine extends DocCitation {
  description: string;
  amount: number;
}

/** EXTENSION: the lease clause the expected amount comes from. */
export interface LeaseCitation extends DocCitation {
  label: string;
  quote: string;
  /** How well the cited quote matched the printed words (docs.citations), 0..1. */
  match_score?: number | null;
}

/** GET /api/exceptions/{id} — the money screen. */
export interface ExceptionDetail {
  exception_id: string;
  lease_id: string;
  period: string;
  expected: number;
  actual: number;
  delta: number;
  status: Status;
  investigation: Investigation | null;
  /** EXTENSION (present on the list shape, absent from the §16 detail shape). */
  clinic_id?: string | null;
  charge_type?: string | null;
  /** EXTENSION: null when the billed line cannot be located on the invoice (never a made-up box). */
  invoice_line?: InvoiceLine | null;
  /** EXTENSION: null when the cited clause cannot be located on the lease. */
  lease_citation?: LeaseCitation | null;
  /** EXTENSION: the work item behind `exc_<item_id>`. */
  item_id?: number | null;
  /** EXTENSION: the work state behind `status` (PROPOSED, HELD, APPROVED, POSTED, ...). */
  state?: string | null;
  /** EXTENSION: what the checker proposed ("hold" | "approve"), why in words, and the rule. */
  proposal?: string | null;
  reason?: string | null;
  rule?: string | null;
  confidence?: number | null;
}

/** EXTENSION: what the gateway did after an approval. */
export interface Posting {
  status: "posted" | "pending";
  journal_entry_id?: number | null;
  error?: string | null;
}

/** POST /api/exceptions/{id}/approve (and EXTENSION /hold) */
export interface ActionResult {
  exception_id: string;
  status: Status;
  /** EXTENSION: the work state after the action (APPROVED, POSTED, HELD). */
  state?: string | null;
  /** EXTENSION: present after approving a postable charge. */
  posting?: Posting | null;
}

/**
 * SSE events from POST /api/exceptions/{id}/investigate. The live API adds
 * `not_found` and a few fields to the §16 four; `confidence`, `doc_id` and
 * `balanced` are null where nothing on record says (a charge check states no
 * confidence and proposes no entries).
 */
export type InvestigationEvent =
  | { stage: "searching"; message: string }
  | {
      stage: "found";
      doc_id: string | null;
      quote: string;
      confidence: number | null;
      source?: string | null;
      trust_rank?: number | null;
      page?: number | null;
      box?: Box | null;
    }
  | { stage: "not_found"; message: string }
  | { stage: "remeasured"; liability_delta: number; rou_delta: number | null }
  | { stage: "complete"; entries: number; balanced: boolean | null; message?: string };

/** EXTENSION shape for GET /api/leases/{id}/schedule?version= (§16 says only "Schedule rows"). */
export interface ScheduleRow {
  index: number;
  period: string;
  payment: number;
  interest: number;
  liability_open: number;
  liability_close: number;
  rou_open: number;
  rou_amortization: number;
  rou_close: number;
  straight_line_cost: number;
}

export interface Schedule {
  lease_id: string;
  version: number;
  effective_from: string;
  active: boolean;
  /** EXTENSION (live API): every version the lease has, and whether this one is confirmed by a person. */
  versions?: number[];
  confirmed?: boolean;
  opening_liability: number;
  opening_rou: number;
  rows: ScheduleRow[];
}

/** EXTENSION shape for GET /api/audit?lease_id= (§16 says only "Audit events"). */
export interface AuditEvent {
  seq: number;
  at: string;
  actor_id: string;
  actor_name?: string;
  action: string;
  subject_type: string;
  subject_id: string;
  lease_id?: string | null;
  allowed: boolean;
  reason?: string | null;
  human_approved?: boolean;
  hash?: string;
  prev_hash?: string | null;
}

export interface AuditResponse {
  events: AuditEvent[];
  chain_verified: boolean;
  /** EXTENSION: first broken sequence number when chain_verified is false. */
  broken_at?: number | null;
  broken_seq?: number | null;
}

/** EXTENSION: GET /api/documents/{sha}/pages (§16 names the endpoint; this is the assumed shape). */
export interface DocumentPage {
  page: number;
  width: number;
  height: number;
}

export interface DocumentPages {
  doc_id: string;
  kind?: string;
  title?: string;
  pages: DocumentPage[];
}

export type Role = "controller" | "regional_manager" | "ap_clerk" | "auditor" | string;

/** /api/auth/* */
export interface Actor {
  id: string;
  name: string;
  role: Role;
  region_id: string | null;
  entity_id: string | null;
}

export type ItemAction = "approve" | "hold" | string;

export interface AllowedActions {
  actions: ItemAction[];
}

/** EXTENSION: GET /api/summary — the dashboard tiles, summed by the API. */
export interface Summary {
  as_of: string;
  active_leases: number;
  open_exceptions: number;
  pending_review: number;
  /** Over-bills held: positive variances of open holds only. */
  held_total: number;
  held_count: number;
  portfolio_liability: number;
}

/** EXTENSION: one charge check (GET /api/items?kind=CHARGE_CHECK), keyed for the money screen. */
export interface ChargeCheck {
  exception_id: string;
  item_id: number | null;
  state: string;
  title: string;
  clinic_id: string | null;
  period: string | null;
  amount: number | null;
  proposal: string | null;
  reason: string | null;
}
