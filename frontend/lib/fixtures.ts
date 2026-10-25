/**
 * Fixtures-mode data.
 *
 * The `SECTION_16_*` constants are the JSON fixtures from docs/DESIGN.md §16,
 * copied verbatim. Do not edit them; change the contract first.
 *
 * Everything else is labelled with where it comes from. No number here is
 * computed in TypeScript:
 *  - fixtureSchedules.json / fixturePortfolio.json are dumped from the real
 *    engine (`leasedesk/`) by scripts/build_fixture_engine.py;
 *  - fixtureDocs.json (page sizes, boxes) is located in the real datagen PDFs
 *    by scripts/build_fixture_docs.py.
 */

import type {
  Actor,
  AuditEvent,
  DocumentPages,
  ExceptionDetail,
  ExceptionSummary,
  InvestigationEvent,
  LeaseSummary,
  Schedule,
  InvoiceLine,
  LeaseCitation,
} from "./types";
import fixtureDocs from "./fixtureDocs.json";
import fixturePortfolio from "./fixturePortfolio.json";
import fixtureSchedules from "./fixtureSchedules.json";

// ---------------------------------------------------------------------------
// §16 — verbatim
// ---------------------------------------------------------------------------

/** §16 `GET /api/leases` */
export const SECTION_16_LEASES: LeaseSummary[] = [{"lease_id": "LEASE-01", "clinic_id": "STORE-01",
  "location": "Northbay Coffee — Daly City — Suite 210",
  "lessor": "Serramonte Retail Partners LLC",
  "status": "exception", "monthly_rent": 19626.65,
  "liability": 559665.35, "end": "2028-12-31"}];

/** §16 `GET /api/exceptions` */
export const SECTION_16_EXCEPTIONS: ExceptionSummary[] = [{"exception_id": "exc_01_jan_cam", "lease_id": "LEASE-01",
  "clinic_id": "STORE-01", "period": "2026-01-01",
  "charge_type": "cam_estimate", "expected": 5941.67, "actual": 6458.33,
  "delta": 516.66, "status": "pending_review", "confidence": 0.94}];

/** §16 `GET /api/exceptions/{id}` — the money screen */
export const SECTION_16_EXCEPTION_DETAIL: ExceptionDetail = {"exception_id": "exc_01_jul_amendment", "lease_id": "LEASE-01",
 "period": "2026-07-01", "expected": 19626.65, "actual": 17400.00,
 "delta": -2226.65, "status": "pending_review",
 "investigation": {
   "root_cause": "amendment", "confidence": 0.94, "explains_variance": true,
   "evidence": [{"doc_id": "eml_20260618", "date": "2026-06-18",
     "source": "dana.reyes@serramonteretail.example", "trust_rank": 1,
     "quote": "Base rent reduced to $17,400 per month effective July 1, 2026.",
     "page": 1, "box": [85.0, 125.3, 527.0, 152.1]}],
   "liability_before": 559665.35, "liability_after": 1002921.05,
   "rou_before": 538771.19, "rou_after": 982026.89,
   "entries": [
     {"account": "Lease liability", "debit": 0, "credit": 443255.70},
     {"account": "ROU asset", "debit": 443255.70, "credit": 0},
     {"account": "ROU asset", "debit": 4624.74, "credit": 0},
     {"account": "Rent expense", "debit": 0, "credit": 4624.74}],
   "balanced": true}};

/** §16 SSE event shape */
export const SECTION_16_SSE_EVENTS: InvestigationEvent[] = [
  {"stage": "searching",  "message": "Searching 1,284 documents…"},
  {"stage": "found",      "doc_id": "eml_20260618", "quote": "Base rent reduced to $17,400 per month effective July 1, 2026.", "confidence": 0.94},
  {"stage": "remeasured", "liability_delta": 443255.70, "rou_delta": 443255.70},
  {"stage": "complete",   "entries": 4, "balanced": true},
];

// ---------------------------------------------------------------------------
// Derived / supplementary (not §16)
// ---------------------------------------------------------------------------

/** LEASE-02..05: engine output on the datagen corpus, §16 lease shape. */
export const ENGINE_PORTFOLIO = fixturePortfolio as LeaseSummary[];

export const FIXTURE_LEASES: LeaseSummary[] = [...SECTION_16_LEASES, ...ENGINE_PORTFOLIO];

/**
 * The §16 money-screen exception, restated in the list shape so the dashboard
 * can link to it. Every value is copied from SECTION_16_EXCEPTION_DETAIL
 * (clinic_id from the LEASE-01 row; charge_type is the line it concerns).
 */
const AMENDMENT_SUMMARY: ExceptionSummary = {
  exception_id: SECTION_16_EXCEPTION_DETAIL.exception_id,
  lease_id: SECTION_16_EXCEPTION_DETAIL.lease_id,
  clinic_id: SECTION_16_LEASES[0].clinic_id,
  period: SECTION_16_EXCEPTION_DETAIL.period,
  charge_type: "base_rent",
  expected: SECTION_16_EXCEPTION_DETAIL.expected,
  actual: SECTION_16_EXCEPTION_DETAIL.actual,
  delta: SECTION_16_EXCEPTION_DETAIL.delta,
  status: SECTION_16_EXCEPTION_DETAIL.status,
  confidence: SECTION_16_EXCEPTION_DETAIL.investigation!.confidence,
};

export const FIXTURE_EXCEPTIONS: ExceptionSummary[] = [AMENDMENT_SUMMARY, ...SECTION_16_EXCEPTIONS];

type CitationSet = { invoice_line: InvoiceLine; lease_citation: LeaseCitation };
const CITATIONS = fixtureDocs.citations as unknown as Record<string, CitationSet>;

/** Detail records keyed by exception id. */
export const FIXTURE_EXCEPTION_DETAILS: Record<string, ExceptionDetail> = {
  exc_01_jul_amendment: {
    ...SECTION_16_EXCEPTION_DETAIL,
    clinic_id: AMENDMENT_SUMMARY.clinic_id,
    charge_type: AMENDMENT_SUMMARY.charge_type,
    ...CITATIONS.exc_01_jul_amendment,
  },
  // The §16 list row has no detail fixture. Show it with what the list knows,
  // the boxed documents, and no investigation on record yet.
  exc_01_jan_cam: {
    exception_id: SECTION_16_EXCEPTIONS[0].exception_id,
    lease_id: SECTION_16_EXCEPTIONS[0].lease_id,
    clinic_id: SECTION_16_EXCEPTIONS[0].clinic_id,
    charge_type: SECTION_16_EXCEPTIONS[0].charge_type,
    period: SECTION_16_EXCEPTIONS[0].period,
    expected: SECTION_16_EXCEPTIONS[0].expected,
    actual: SECTION_16_EXCEPTIONS[0].actual,
    delta: SECTION_16_EXCEPTIONS[0].delta,
    status: SECTION_16_EXCEPTIONS[0].status,
    investigation: null,
    ...CITATIONS.exc_01_jan_cam,
  },
};

/** Investigation stream per exception. Only the §16 one has events. */
export const FIXTURE_SSE: Record<string, InvestigationEvent[]> = {
  exc_01_jul_amendment: SECTION_16_SSE_EVENTS,
};

export const FIXTURE_SCHEDULES = fixtureSchedules as unknown as Record<string, Record<string, Schedule>>;

export const FIXTURE_DOCUMENTS = fixtureDocs.documents as unknown as Record<string, DocumentPages>;

export function fixtureDocumentUrl(docId: string): string {
  return `/fixtures/docs/${encodeURIComponent(docId)}.pdf`;
}

/**
 * One rendered page, mirroring GET /api/documents/{sha}/pages/{n}.png.
 *
 * Written by scripts/render_fixture_pages.py with the same renderer and DPI
 * the API uses, so a citation box lands in the same place with or without it.
 */
export function fixturePageUrl(docId: string, page: number): string {
  return `/fixtures/docs/${encodeURIComponent(docId)}/${page}.png`;
}

// ---------------------------------------------------------------------------
// People and audit (shapes assumed; see README)
// ---------------------------------------------------------------------------

/** Names from datagen/company.py's org chart. */
export const FIXTURE_ACTORS: Actor[] = [
  { id: "PER-CTRL", name: "Priya Raghunathan", role: "controller", region_id: null, entity_id: "ENT-CA" },
  { id: "PER-RM-BAY", name: "Dana Whitfield", role: "regional_manager", region_id: "REG-BAY", entity_id: "ENT-CA" },
  { id: "PER-AP", name: "Marcus Oyelaran", role: "ap_clerk", region_id: null, entity_id: "ENT-CA" },
  { id: "PER-AUD", name: "External Auditor", role: "auditor", region_id: null, entity_id: null },
];

export const FIXTURE_EMAILS: Record<string, string> = {
  "priya.raghunathan@northbaypt.example": "PER-CTRL",
  "dana.whitfield@northbaypt.example": "PER-RM-BAY",
  "marcus.oyelaran@northbaypt.example": "PER-AP",
  "audit@brennan-cpa.example": "PER-AUD",
};

export const FIXTURE_AUDIT: AuditEvent[] = [
  { seq: 1, at: "2026-01-02T14:05:11Z", actor_id: "agent:checker", actor_name: "Checker agent", action: "propose_hold",
    subject_type: "exception", subject_id: "exc_01_jan_cam", lease_id: "LEASE-01", allowed: true,
    reason: "Operating expense estimate billed above the lease estimate (§4.1)", human_approved: false,
    prev_hash: null, hash: "9f2c1e0a6b7d4c3e" },
  { seq: 2, at: "2026-07-01T09:12:40Z", actor_id: "agent:reconciliation", actor_name: "Reconciliation", action: "create_exception",
    subject_type: "exception", subject_id: "exc_01_jul_amendment", lease_id: "LEASE-01", allowed: true,
    reason: "Payment does not match schedule v1", human_approved: false,
    prev_hash: "9f2c1e0a6b7d4c3e", hash: "4a8b0d2f1c9e7a65" },
  { seq: 3, at: "2026-07-01T09:12:58Z", actor_id: "agent:investigation", actor_name: "Investigation agent", action: "attach_evidence",
    subject_type: "exception", subject_id: "exc_01_jul_amendment", lease_id: "LEASE-01", allowed: true,
    reason: "Found eml_20260618 (trust rank 1)", human_approved: false,
    prev_hash: "4a8b0d2f1c9e7a65", hash: "c71e5b3a90d24f18" },
  { seq: 4, at: "2026-07-01T09:13:02Z", actor_id: "engine", actor_name: "Accounting engine", action: "propose_schedule",
    subject_type: "schedule", subject_id: "LEASE-01:v2", lease_id: "LEASE-01", allowed: true,
    reason: "Remeasured at 2026-07-01; 4 entries proposed, balanced", human_approved: false,
    prev_hash: "c71e5b3a90d24f18", hash: "0be93d7c55a1f2e4" },
  { seq: 5, at: "2026-07-01T10:40:19Z", actor_id: "PER-AP", actor_name: "Marcus Oyelaran", action: "approve",
    subject_type: "exception", subject_id: "exc_01_jul_amendment", lease_id: "LEASE-01", allowed: false,
    reason: "Role ap_clerk may not approve accounting judgments", human_approved: false,
    prev_hash: "0be93d7c55a1f2e4", hash: "e3f6a2b8d1c04977" },
];
