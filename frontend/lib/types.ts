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
 * `not_found`, `error` and a few fields to the §16 four; `confidence`, `doc_id` and
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
  | { stage: "complete"; entries: number; balanced: boolean | null; message?: string }
  /** EXTENSION: the run could not finish. Carries why, and ends the stream. */
  | { stage: "error"; message: string };

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
  /** EXTENSION: the clinic's region, so a regional manager's Today can keep to their own. */
  region_id?: string | null;
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

/** EXTENSION: where one number of the month summary drills down to: `endpoint` + `params` returns exactly its rows. */
export interface MonthSummaryDrill {
  endpoint: string;
  params: { period: string; entity: string; metric: MonthMetricName };
  /** The same set, declaratively (kind, state, proposal, ...), for labels and links. */
  filter: Record<string, unknown>;
}

export type MonthMetricName = "clinics" | "checked" | "approved" | "held" | "disputes" | "questions" | "batch";

export interface MonthMetric {
  value: number | boolean;
  label: string;
  /** Only on `held`: the over-bills held, in dollars. */
  amount?: number;
  drill: MonthSummaryDrill;
}

/** EXTENSION: GET /api/summary/month?period=YYYY-MM&entity= — the stepper's run summary. */
export interface MonthSummary {
  period: string;
  month: string;
  entity_id: string | null;
  entity_name: string;
  headline: string;
  metrics: Record<MonthMetricName, MonthMetric>;
  batch: {
    ready: boolean;
    released: boolean;
    awaiting_decision: number;
    releasable: number;
    releasable_total: number;
  };
}

/** EXTENSION: one row behind a month-summary number (GET /api/summary/month/items); `type` says which kind. */
export type MonthSummaryRow =
  | { type: "charge_check"; item_id: number; exception_id: string; state: string; proposal: string | null; clinic_id: string | null; title: string; amount: number | null; variance: number | null }
  | { type: "clinic"; clinic_id: string; name: string; charges: number }
  | { type: "dispute"; item_id: number; state: string; clinic_id: string | null; title: string; amount: number | null }
  | { type: "question"; question_id: number; item_id: number; exception_id: string | null; kind: string; asked_to: string; asked_by: string; body: string; asked_at: string; due_at: string | null }
  | { type: "payable"; item_id: number; exception_id: string; clinic_id: string; charge_type: string; landlord_name: string; billed: number; amount: number };

/** EXTENSION: POST /api/batches/{period}/release — the AP clerk releases the month's payment batch. */
export interface BatchRelease {
  outbox_id: number;
  idempotency_key: string;
  /** false when this period's batch was already released: the same batch, never a second one. */
  created: boolean;
  period: string;
  item_count: number;
  total: number;
}

/** EXTENSION: POST /api/demo/reset — controller only, demo mode only (404 otherwise). */
export interface DemoResetResult {
  status: "reset";
  database: string;
  seconds: number;
  restore_seconds: number;
  budget_seconds: number;
  within_budget: boolean;
  verified: boolean;
  chain_ok: boolean;
  counts_match: boolean;
  head_match: boolean;
  judge_provided_cleared: number;
  snapshot: { file: string; created_at: string | null; git_sha: string | null; chain_head: { seq: number; hash: string } | null; alembic_version: string | null };
  mismatches: Record<string, unknown>;
  /** The audit event recording who reset the demo. */
  event_seq: number;
}

/** EXTENSION (B9): one row a "Why?" answer rests on. `tool` names the fixed
 *  query that produced it; the other keys depend on the tool (events carry
 *  seq/actor_id/action/allowed/reason, sources carry source/rank/claims). */
export interface WhyRow {
  tool: "timeline_for" | "decisions_by_policy" | "sources_for" | "denied_attempts" | "as_known_on";
  [key: string]: unknown;
}

/** EXTENSION (B9): POST /api/items/{id}/why */
export interface WhyAnswer {
  answer: string;
  rows: WhyRow[];
  tools_used: string[];
  /** "template", or "llm:<model_ref>" when a model phrased the same rows. */
  path: string;
  item_id: number;
  notes: string[];
}

/** EXTENSION (B9): what an evidence pack is for. A string works too:
 *  "work_item:42", "journal_entry:7", "lease:LEASE-01:2026-01". */
export type EvidencePackSubject =
  | string
  | { type: "work_item" | "journal_entry"; id: number }
  | { type: "lease_period"; lease_id: string; period: string };

// ---------------------------------------------------------------------------
// EXTENSION: the resolver (backend/app/api/resolver.py)
// ---------------------------------------------------------------------------

/** 1 executed amendment · 2 original lease · 3 authorized rep · 4 property manager · 5 invoice · 6 payment history */
export type TrustRank = 1 | 2 | 3 | 4 | 5 | 6;

/** One source the resolver weighed, its trust rank, the value it claims and where it says so. */
export interface ResolverSource {
  source_id: string;
  /** lease, invoice, payment_history, amendment, authorized_rep, property_manager, ... */
  kind: string;
  rank: TrustRank;
  rank_name: string;
  label: string;
  /** Dollars when a number, else the text it claims. */
  value: number | string | null;
  claim: string;
  citation: Record<string, unknown>;
  extraction_confidence: number | null;
  read_quality: number | null;
  /** Failed sender verification: set aside, not believed. */
  suspect: boolean;
  note: string;
}

export type ResolverAction = "proceed" | "hold" | "ask";

export interface ResolverDecision {
  action: ResolverAction;
  /** "Trusted the lease … over invoice … because …" */
  explanation: string;
  trusted: string | null;
  agreeing: string[];
  contradicting: string[];
  superseded: string[];
  set_aside: string[];
  trust_gap: number | null;
  policy: { policy_id: string; version: number; then: string; reason: string } | null;
}

export interface ResolverRoute {
  role: "regional_manager" | "controller" | "ap_clerk";
  nature: "landlord_fact" | "accounting_judgement" | "payment_release";
  asked_to: string | null;
  /** The controller, when the amount at stake is over materiality. */
  also_to: string[];
  amount_at_stake: number;
  material: boolean;
  reasons: string[];
}

export interface OpenQuestion {
  id: number;
  asked_to: string;
  body: string;
  asked_at: string;
  due_at: string | null;
  reminders: number;
  last_reminded_at: string | null;
  escalated_to: string | null;
}

/** GET /api/items/{id}/sources */
export interface ItemSources {
  item_id: number;
  kind: string;
  state: string;
  sources: ResolverSource[];
  decision: ResolverDecision | null;
  explanation: string | null;
  confidence: number | null;
  confidence_reasons: string[];
  route: ResolverRoute | null;
  asked_to: string | null;
  payment_due: string | null;
  question: OpenQuestion | null;
  /** True when resolved on the fly for an item proposed before the resolver existed. */
  computed: boolean;
}

/** One open question for the Today screen. */
export interface QuestionItem {
  id: number;
  work_item_id: number;
  kind: string;
  state: string;
  title: string;
  clinic_id: string | null;
  region_id: string | null;
  entity_id: string | null;
  period: string | null;
  asked_to: string;
  asked_by: string;
  body: string;
  asked_at: string;
  due_at: string | null;
  due_on: string | null;
  /** Against the business clock, not the wall clock. */
  overdue: boolean;
  amount_at_stake: number | null;
  confidence: number | null;
  reminders: number;
  last_reminded_at: string | null;
  escalated_to: string | null;
  /** Why it is on my list: asked to me, escalated to me, or copied as material. */
  why: "asked" | "escalated" | "material" | null;
}

/** GET /api/questions?mine=1 */
export interface Questions {
  business_date: string;
  total: number;
  questions: QuestionItem[];
}

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

export type PolicyStatus = "proposed" | "approved" | "rejected" | "retired";
export type PolicyAction = "approve" | "hold" | "dispute";

export interface PolicyScope {
  entity_id: string | null;
  landlord_id: string | null;
  lease_id: string | null;
  clinic_id: string | null;
}

/** The rule as stored (work/policies.py): money bounds are decimal strings. */
export interface PolicyRule {
  name: string;
  version: number;
  description: string;
  origin: "onboarding" | "answer" | "manual";
  scope: PolicyScope;
  when: {
    charge_types: string[];
    same_as_prior_paid: boolean | null;
    matches_lease: boolean | null;
    min_amount: string | null;
    max_amount: string | null;
    min_variance: string | null;
    max_variance: string | null;
    checker_rules: string[];
    description_contains: string | null;
  };
  then: { action: PolicyAction | null; account: string | null; trust_source: string | null };
  effective_from: string | null;
  effective_to: string | null;
  evidence_ids: string[];
}

export interface BacktestChange {
  charge_id: string;
  charge_ref: string;
  period: string;
  lease_id: string | null;
  clinic_id: string | null;
  charge_type: string;
  amount: number;
  current: string;
  decided_by: string | null;
  policy: PolicyAction;
  dollars: number;
  direction: "released" | "withheld" | "none";
}

export interface BacktestConflict {
  policy_id: number;
  version: number;
  name: string;
  action: PolicyAction | null;
  charges: number;
  examples: string[];
  /** Which decides the overlap under evaluation's tie-breaks. */
  winner: "this" | "existing";
}

export interface Backtest {
  policy: { id: number | null; name: string; version: number; fingerprint: string };
  periods: { first: string | null; last: string | null; count: number };
  charges_scanned: number;
  matched: number;
  unknown: number;
  unchanged: number;
  new_decisions: number;
  changed: number;
  dollars: number;
  released: number;
  withheld: number;
  changes: BacktestChange[];
  conflicts: BacktestConflict[];
  effective_dates_ignored: boolean;
  digest: string;
}

export interface BacktestSummary {
  matched: number;
  changed: number;
  dollars: number;
  released: number;
  withheld: number;
  unknown: number;
  digest: string;
  conflicts: number;
}

export interface PolicySummary {
  id: number;
  name: string;
  version: number;
  status: PolicyStatus;
  /** `policy:<id>@v<version>`, as cited in audit events' policy_ref. */
  ref: string;
  origin: string | null;
  description: string | null;
  scope: PolicyScope;
  action: PolicyAction | null;
  charge_types: string[];
  effective_from: string | null;
  effective_to: string | null;
  precedent_count: number | null;
  /** Approve / reject this work item (POST /api/items/{id}/actions/...) to decide the policy. */
  work_item_id: number | null;
  work_item_state: string | null;
  backtest: BacktestSummary | null;
  created_at: string;
}

export interface PolicyList {
  counts: Record<PolicyStatus, number>;
  policies: PolicySummary[];
}

export interface PolicyCitation {
  seq: number;
  at: string;
  actor_id: string;
  action: string;
  subject_type: string;
  subject_id: string;
  reason: string | null;
}

export interface PolicyDetail {
  policy: PolicySummary;
  rule: PolicyRule;
  versions: { id: number; version: number; status: PolicyStatus; created_at: string; work_item_id: number | null }[];
  /** Precedents, linked decisions, the question and answer it came from. */
  evidence: Record<string, unknown>;
  backtest: Backtest | null;
  rejection: { by: string; at: string; reason: string | null } | null;
  cited_by: PolicyCitation[];
}

export interface BacktestRun {
  policy_id: number;
  status: PolicyStatus;
  backtest: Backtest;
  refresh_job_id: number | null;
}

/** EXTENSION (C8): POST /api/pairing/codes. `code` is "XXXX-XXXX". */
export interface PairingCode {
  code: string;
  expires_at: string;
  ttl_seconds: number;
  instructions: string;
}

/** EXTENSION (C8): one live ASI:One chat pairing of the signed-in person. */
export interface Pairing {
  id: number;
  /** The ASI:One user's agent address. */
  chat_user: string;
  claimed_at: string;
  expires_at: string;
}

/** EXTENSION (C8): GET /api/pairing. */
export interface PairingList {
  pairings: Pairing[];
}
