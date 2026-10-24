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
  /**
   * EXTENSION: what approving does with the money. On a hold, `payable` is the
   * undisputed amount approving ("Uphold hold") posts and `disputed` what stays
   * out of the ledger; on an approve proposal, `payable` is the billed amount.
   */
  payable?: number | null;
  disputed?: number | null;
  /** EXTENSION: once decided: "upheld", or "pay_as_billed" (the controller's override). */
  resolution?: "upheld" | "pay_as_billed" | string | null;
  resolved_by?: string | null;
  override_reason?: string | null;
}

/** EXTENSION: what the gateway did after an approval. */
export interface Posting {
  /** closed: a hold upheld on a charge nothing supports; nothing owed, nothing posted. */
  status: "posted" | "closed" | "pending";
  journal_entry_id?: number | null;
  error?: string | null;
  /** What the entry put on accounts payable, and what stayed out of the ledger. */
  amount?: number | null;
  disputed?: number | null;
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

/** EXTENSION: one abstracted term of a lease version (GET /api/leases/{id}/versions). */
export interface LeaseTerm {
  field: string;
  value: unknown;
  /** Null when the quote could not be located: then bbox and document_id are null too. */
  page: number | null;
  bbox: Box | null;
  quote: string | null;
  /** The citation match score: 1 exact, lower partial, 0 not found. */
  confidence: number | null;
  document_id: string | null;
  extracted_by: {
    run_id: number | null;
    /** "abstraction:llm" or "abstraction:generator": which path read the term. */
    agent: string | null;
    prompt_id: string | null;
    prompt_version: string | null;
    model: string | null;
  } | null;
}

/** EXTENSION: a lease version, who confirmed it, and its confirmation work item. */
export interface LeaseVersion {
  lease_id: string;
  version: number;
  lease_version_id: number;
  effective_from: string;
  confirmed: boolean;
  confirmed_by: string | null;
  confirmed_at: string | null;
  work_item: { id: number; state: string; proposal: string | null; allowed_actions: string[] } | null;
  terms: LeaseTerm[];
}

// ---------------------------------------------------------------------------
// Disputes and obligations (PHASE_2.md groups 11-12; backend/app/api/disputes.py,
// backend/app/api/obligations.py). No §16 fixture: shapes documented there.
// ---------------------------------------------------------------------------

export type DisputeStatus = "drafted" | "sent" | "acknowledged" | "credited" | "partially_credited" | "refused";

export type DisputeReplyOutcome = "acknowledged" | "queried" | "full_credit" | "partial_credit" | "refused";

export interface DisputeSummary {
  id: string;
  status: DisputeStatus;
  landlord_id: string;
  landlord_name: string;
  lease_id: string;
  clinic_id: string;
  region_id: string | null;
  entity_id: string;
  period: string;
  charge_type: string;
  invoice_id: string;
  billed: number;
  supported: number;
  amount: number;
  credited_amount: number;
  open_receivable: number;
  work_item_id: number;
  work_item_state: string;
  sent_at: string | null;
  updated_at: string;
}

export interface DisputeList {
  counts: Record<DisputeStatus, number>;
  total: number;
  disputes: DisputeSummary[];
}

export interface DisputeHistoryEvent {
  seq: number;
  at: string;
  actor_id: string;
  action: string;
  allowed: boolean;
  reason: string | null;
  from_status: string | null;
  to_status: string | null;
  evidence: Record<string, unknown> | null;
}

export interface DisputeReceivable {
  recognized: number;
  cleared: number;
  open: number;
  entries: { journal_entry_id: number; key: string; date: string; debit: number; credit: number }[];
}

export interface DisputeOutboxMessage {
  id: number;
  key: string;
  status: "pending" | "sent" | "failed";
  round: number | null;
  to: string | null;
  subject: string | null;
  sent_at: string | null;
}

export interface DisputeWorkItemRef {
  id: number;
  state: string;
  proposal: string | null;
  reason: string | null;
  updated_at: string;
}

export interface DisputeDetail {
  dispute: DisputeSummary;
  letter: string;
  notice_to: { landlord_id: string; name: string; attn: string; address: string; email: string };
  facts: Record<string, unknown>;
  credits: { credit_memo_ref: string; amount: string; received_on: string }[];
  refusal_reason: string | null;
  history: DisputeHistoryEvent[];
  items: { letter: DisputeWorkItemRef | null; receivable: DisputeWorkItemRef | null };
  receivable: DisputeReceivable;
  outbox: DisputeOutboxMessage[];
  reply_outcomes: DisputeReplyOutcome[];
  gateway_error: string | null;
}

export interface DisputeReply {
  outcome: DisputeReplyOutcome;
  granted?: number;
  credit_memo_ref?: string;
  reason?: string;
  received_on?: string;
  sender?: string;
  message_id?: string;
  body?: string;
}

export type ObligationKind = "renewal_notice" | "cam_audit_window" | "deposit_return" | "expiration";

export interface ObligationCitation {
  section: string | null;
  page: number | null;
  quote: string | null;
  document_id: string | null;
  field: string | null;
  lease_version_id: number | null;
  also?: Record<string, unknown>[];
  assumption?: string;
}

export interface Obligation {
  id: number;
  lease_id: string;
  clinic_id: string;
  region_id: string | null;
  entity_id: string;
  kind: ObligationKind;
  key: string;
  due_date: string;
  days_left: number;
  action: string;
  citation: ObligationCitation;
  source: "lease_term" | "generator";
  lease_version_id: number | null;
  details: Record<string, unknown>;
  alert_dates: Record<"90" | "60" | "30", string>;
  alerts: (DisputeWorkItemRef & { title: string })[];
}

export interface ObligationList {
  today: string;
  within_days: number;
  total: number;
  obligations: Obligation[];
}
