/**
 * Typed wrappers for every endpoint in docs/DESIGN.md §16, plus auth.
 *
 * Data source:
 *  - NEXT_PUBLIC_USE_FIXTURES=1  → always fixtures.
 *  - otherwise the API at NEXT_PUBLIC_API_URL (default http://localhost:8000),
 *    and only the API. If it cannot be reached (network error / timeout) the
 *    call throws ApiUnreachableError and getApiHealth() reports it, so the
 *    shell can say so; fixtures are never a silent fallback. HTTP errors are
 *    not masked either: a 403 or 500 surfaces as an error state.
 */

import type {
  DisputeDetail,
  DisputeList,
  DisputeReply,
  ObligationList,
  ActionResult,
  Actor,
  AllowedActions,
  AuditResponse,
  ChargeCheck,
  DemoResetResult,
  DocumentPages,
  EvidencePackSubject,
  ExceptionDetail,
  ExceptionSummary,
  InvestigationEvent,
  ItemAction,
  ItemSources,
  LeaseSummary,
  LeaseVersion,
  MonthMetricName,
  MonthSummary,
  MonthSummaryRow,
  Questions,
  Schedule,
  Status,
  PairingCode,
  PairingList,
  Summary,
  WhyAnswer,
  BacktestRun,
  PolicyDetail,
  PolicyList,
} from "./types";
import {
  FIXTURE_ACTORS,
  FIXTURE_AUDIT,
  FIXTURE_DOCUMENTS,
  FIXTURE_EMAILS,
  FIXTURE_EXCEPTION_DETAILS,
  FIXTURE_EXCEPTIONS,
  FIXTURE_LEASES,
  FIXTURE_SCHEDULES,
  FIXTURE_SSE,
  fixtureDocumentUrl,
  fixturePageUrl,
} from "./fixtures";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const FORCE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES === "1";
const TIMEOUT_MS = 4000;

// ---------------------------------------------------------------------------
// Data-source state (fixed for the session: fixtures only when asked for)
// ---------------------------------------------------------------------------

export type DataSource = "api" | "fixtures";
const source: DataSource = FORCE_FIXTURES ? "fixtures" : "api";

export function getDataSource(): DataSource {
  return source;
}
/** Kept for useDataSource(); the source never changes after load. */
export function subscribeDataSource(fn: () => void): () => void {
  void fn;
  return () => undefined;
}

// ---------------------------------------------------------------------------
// API health (observable so the shell can show an "API unreachable" banner)
// ---------------------------------------------------------------------------

export type ApiHealth = { reachable: true } | { reachable: false; error: string };
const REACHABLE: ApiHealth = { reachable: true };
let health: ApiHealth = REACHABLE;
const healthListeners = new Set<() => void>();

export function getApiHealth(): ApiHealth {
  return health;
}
export function subscribeApiHealth(fn: () => void): () => void {
  healthListeners.add(fn);
  return () => healthListeners.delete(fn);
}
function setHealth(next: ApiHealth) {
  if (next.reachable === health.reachable && (next.reachable || (!health.reachable && next.error === health.error))) return;
  health = next;
  healthListeners.forEach((fn) => fn());
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The API could not be reached at all (network error or timeout); no HTTP status. */
export class ApiUnreachableError extends Error {
  constructor(message: string) {
    super(`API unreachable at ${API_URL}: ${message}`);
    this.name = "ApiUnreachableError";
  }
}

function unreachable(e: unknown): ApiUnreachableError {
  const err = new ApiUnreachableError(e instanceof Error ? e.message : String(e));
  setHealth({ reachable: false, error: err.message });
  return err;
}

/** A live API answered 401 on a data call: the session is gone, so sign in again. */
function redirectToLogin() {
  if (typeof window === "undefined") return;
  const here = window.location.pathname + window.location.search;
  if (window.location.pathname.startsWith("/login")) return;
  window.location.assign(`/login?next=${encodeURIComponent(here)}`);
}

/**
 * Exception ids vs work item ids. The live API names an exception `exc_<work_item.id>`
 * and the queue (/api/items) takes the bare `<work_item.id>`. Fixture ids
 * (`exc_01_jul_amendment`) are not work items and pass through unchanged.
 */
/** Same as itemIdFor; the name main used for the same fix. */
export const itemIdOf = (exceptionId: string): string => itemIdFor(exceptionId);

export function itemIdFor(exceptionId: string): string {
  const m = /^exc_([1-9][0-9]*)$/.exec(exceptionId);
  return m ? m[1] : exceptionId;
}

export function exceptionIdFor(itemId: number | string): string {
  return `exc_${itemId}`;
}

async function http<T>(path: string, init: RequestInit = {}): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(API_URL + path, {
      credentials: "include",
      ...init,
      headers: { Accept: "application/json", ...(typeof init.body === "string" ? { "Content-Type": "application/json" } : {}), ...init.headers },
      signal: init.signal ?? ctrl.signal,
    });
  } catch (e) {
    throw unreachable(e);
  } finally {
    clearTimeout(timer);
  }
  setHealth(REACHABLE);
  if (res.status === 401 && !path.startsWith("/api/auth/")) redirectToLogin();
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, `${res.status} ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Call the API, or the fixture implementation in fixtures mode. Never one for the other. */
async function call<T>(live: () => Promise<T>, fixture: () => T | Promise<T>): Promise<T> {
  return source === "fixtures" ? fixture() : live();
}

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// Fixtures-mode mutable state (approve/hold change status for the session)
// ---------------------------------------------------------------------------

const fx = {
  status: new Map<string, Status>(),
  audit: clone(FIXTURE_AUDIT),
  actor: FIXTURE_ACTORS[0] as Actor | null,
};

function fxStatus(id: string, original: Status): Status {
  return fx.status.get(id) ?? original;
}

function fxAct(id: string, action: ItemAction): ActionResult {
  const detail = FIXTURE_EXCEPTION_DETAILS[id];
  if (!detail) throw new ApiError(404, `404 exception ${id} not found`);
  const actor = fx.actor;
  if (!actor) throw new ApiError(401, "401 not logged in");
  const allowed = fxAllowed(id).includes(action);
  const last = fx.audit[fx.audit.length - 1];
  fx.audit.push({
    seq: last.seq + 1,
    at: new Date().toISOString(),
    actor_id: actor.id,
    actor_name: actor.name,
    action,
    subject_type: "exception",
    subject_id: id,
    lease_id: detail.lease_id,
    allowed,
    reason: allowed ? (action === "approve" ? "Approved by a human" : "Held for review") : `Role ${actor.role} may not ${action}`,
    human_approved: allowed && action === "approve",
    prev_hash: last.hash ?? null,
    hash: Math.random().toString(16).slice(2, 18).padEnd(16, "0"),
  });
  if (!allowed) throw new ApiError(403, `403 ${actor.role} may not ${action} ${id}`);
  const status: Status = action === "approve" ? "balanced" : "escalated";
  fx.status.set(id, status);
  return { exception_id: id, status };
}

function fxAllowed(id: string): ItemAction[] {
  const detail = FIXTURE_EXCEPTION_DETAILS[id];
  if (!detail || !fx.actor) return [];
  if (fxStatus(id, detail.status) === "balanced") return [];
  // The real list comes from can(); fixtures give approvers both actions.
  return fx.actor.role === "controller" || fx.actor.role === "regional_manager" ? ["approve", "hold"] : [];
}

// ---------------------------------------------------------------------------
// §16 endpoints
// ---------------------------------------------------------------------------

/** 1. GET /api/leases */
export function getLeases(): Promise<LeaseSummary[]> {
  return call(
    () => http<LeaseSummary[]>("/api/leases"),
    () => {
      const leases = clone(FIXTURE_LEASES);
      // a lease whose every fixture exception is approved reads as balanced
      for (const l of leases) {
        const open = FIXTURE_EXCEPTIONS.filter((e) => e.lease_id === l.lease_id && fxStatus(e.exception_id, e.status) !== "balanced");
        if (l.status === "exception" && open.length === 0) l.status = "balanced";
      }
      return leases;
    },
  );
}

/** 2. GET /api/exceptions */
export function getExceptions(): Promise<ExceptionSummary[]> {
  return call(
    () => http<ExceptionSummary[]>("/api/exceptions"),
    () => clone(FIXTURE_EXCEPTIONS).map((e) => ({ ...e, status: fxStatus(e.exception_id, e.status) })),
  );
}

/** 3. GET /api/exceptions/{id} */
export function getException(id: string): Promise<ExceptionDetail> {
  return call(
    async () => normalizeDetail(await http<ExceptionDetail>(`/api/exceptions/${encodeURIComponent(id)}`)),
    () => {
      const d = FIXTURE_EXCEPTION_DETAILS[id];
      if (!d) throw new ApiError(404, `404 exception ${id} not found`);
      return { ...clone(d), status: fxStatus(id, d.status) };
    },
  );
}

/**
 * The live API always sends an `investigation` object, all nulls when nothing
 * has been investigated; the screens read `null` as "not investigated yet".
 */
function normalizeDetail(d: ExceptionDetail): ExceptionDetail {
  const inv = d.investigation;
  const empty = !!inv && inv.root_cause == null && !inv.evidence?.length && !inv.entries?.length && inv.liability_before == null;
  return empty ? { ...d, investigation: null } : d;
}

/** EXTENSION: GET /api/summary — dashboard tiles, every figure summed by the API. */
export function getSummary(): Promise<Summary> {
  return call(
    () => http<Summary>("/api/summary"),
    () => {
      // Offline stand-in only: the fixture rows, in cents. Over-bills only, like the API.
      const open = FIXTURE_EXCEPTIONS.filter((e) => fxStatus(e.exception_id, e.status) !== "balanced");
      const over = open.filter((e) => e.delta > 0);
      return {
        as_of: "2026-07-01",
        active_leases: FIXTURE_LEASES.length,
        open_exceptions: open.length,
        pending_review: open.filter((e) => fxStatus(e.exception_id, e.status) === "pending_review").length,
        held_total: over.reduce((s, e) => s + Math.round(e.delta * 100), 0) / 100,
        held_count: over.length,
        portfolio_liability: FIXTURE_LEASES.reduce((s, l) => s + Math.round(l.liability * 100), 0) / 100,
      };
    },
  );
}

interface QueueResponse {
  counts: Record<string, number>;
  total: number;
  items: Array<{ id: number; kind: string; state: string; title: string; clinic_id: string | null; period: string | null; amount: number | null; proposal: string | null; reason: string | null }>;
}

/** EXTENSION: every charge check of a month (GET /api/items?kind=CHARGE_CHECK), holds and correct charges alike. */
export function getChargeChecks(period?: string): Promise<ChargeCheck[]> {
  const q = new URLSearchParams({ kind: "CHARGE_CHECK" });
  if (period) q.set("period", period);
  return call<ChargeCheck[]>(
    async () => {
      const res = await http<QueueResponse>(`/api/items?${q.toString()}`);
      return res.items
        .map((i): ChargeCheck => ({
          exception_id: exceptionIdFor(i.id),
          item_id: i.id,
          state: i.state,
          title: i.title,
          clinic_id: i.clinic_id,
          period: i.period,
          amount: i.amount,
          proposal: i.proposal,
          reason: i.reason,
        }))
        .sort((a, b) => (a.item_id ?? 0) - (b.item_id ?? 0));
    },
    () =>
      FIXTURE_EXCEPTIONS.map((e) => ({
        exception_id: e.exception_id,
        item_id: null,
        state: fxStatus(e.exception_id, e.status) === "balanced" ? "APPROVED" : "PROPOSED",
        title: `${e.clinic_id} ${e.charge_type}`,
        clinic_id: e.clinic_id,
        period: e.period,
        amount: e.actual,
        proposal: "hold",
        reason: null,
      })),
  );
}

/** 4. POST /api/exceptions/{id}/approve */
export function approveException(id: string): Promise<ActionResult> {
  return call(
    () => http<ActionResult>(`/api/exceptions/${encodeURIComponent(id)}/approve`, { method: "POST" }),
    () => fxAct(id, "approve"),
  );
}

/**
 * Work states to the four statuses the exception screen knows.
 *
 * Mirrors STATUS_BY_STATE in the exceptions router. The item action route
 * answers with the work state; §16's approve route already maps it.
 */
const STATUS_BY_STATE: Record<string, Status> = {
  NEW: "exception",
  PROPOSED: "pending_review",
  NEEDS_INFO: "escalated",
  HELD: "escalated",
  APPROVED: "balanced",
  POSTED: "balanced",
  CLOSED: "balanced",
  REJECTED: "balanced",
};

/**
 * Any other action: POST /api/items/{item_id}/actions/{action}.
 *
 * The queue's own action route takes every human action the state machine has
 * (resume, reject, close, ...), as the same `perform()` the approve route
 * uses, so the answer allowed-actions gave the button is the answer the press
 * gets. Approve, hold and pay-as-billed have exception routes of their own,
 * which also answer with the work state and the posting.
 */
export function performAction(exceptionId: string, action: ItemAction): Promise<ActionResult> {
  return call(
    async (): Promise<ActionResult> => {
      const res = await http<{ state: string }>(
        `/api/items/${encodeURIComponent(itemIdOf(exceptionId))}/actions/${encodeURIComponent(action)}`,
        { method: "POST" },
      );
      return { exception_id: exceptionId, status: STATUS_BY_STATE[res.state] ?? "pending_review", state: res.state };
    },
    () => fxAct(exceptionId, action),
  );
}

/** EXTENSION: POST /api/exceptions/{id}/hold — not in §16; the queue's hold, answered with the work state. */
export function holdException(id: string): Promise<ActionResult> {
  return call(
    () => http<ActionResult>(`/api/exceptions/${encodeURIComponent(id)}/hold`, { method: "POST" }),
    () => fxAct(id, "hold"),
  );
}

/**
 * EXTENSION: POST /api/exceptions/{id}/pay-as-billed {reason}, the controller's
 * override: approve a held charge and pay the billed amount anyway. Anyone
 * else gets 403 (and the refusal is on record); no reason is 422.
 */
export function payAsBilledException(id: string, reason: string): Promise<ActionResult> {
  return call(
    () =>
      http<ActionResult>(`/api/exceptions/${encodeURIComponent(id)}/pay-as-billed`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
    () => {
      if (!reason.trim()) throw new ApiError(422, "422 paying a disputed charge as billed needs a reason");
      // Not a controller: fxAct records the refusal and throws 403.
      return fxAct(id, fx.actor?.role === "controller" ? "approve" : "pay_as_billed");
    },
  );
}

/**
 * 5. POST /api/exceptions/{id}/investigate — SSE.
 * EventSource cannot POST, so this reads the response body as a stream and
 * parses `data:` lines. Resolves when the stream ends.
 */
export async function investigate(
  id: string,
  onEvent: (e: InvestigationEvent) => void,
  signal?: AbortSignal,
  replayDelayMs = 650,
): Promise<void> {
  const replay = async () => {
    const events = FIXTURE_SSE[id];
    if (!events) throw new ApiError(404, `404 no investigation stream for ${id}`);
    for (const ev of events) {
      await sleep(replayDelayMs);
      if (signal?.aborted) return;
      onEvent(clone(ev));
    }
  };
  if (source === "fixtures") return replay();

  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/exceptions/${encodeURIComponent(id)}/investigate`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "text/event-stream" },
      signal,
    });
  } catch (e) {
    if (signal?.aborted) return;
    throw unreachable(e);
  }
  setHealth(REACHABLE);
  if (!res.ok || !res.body) throw new ApiError(res.status, `${res.status} ${res.statusText}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const ev = parseSseChunk(chunk);
      if (ev) onEvent(ev);
    }
  }
  const tail = parseSseChunk(buf);
  if (tail) onEvent(tail);
}

/** Parse one SSE frame (lines separated by \n); returns null for comments/empty frames. */
export function parseSseChunk(chunk: string): InvestigationEvent | null {
  const data = chunk
    .split(/\r?\n/)
    .filter((l) => l.startsWith("data:"))
    .map((l) => l.slice(5).trimStart())
    .join("\n");
  if (!data) return null;
  try {
    return JSON.parse(data) as InvestigationEvent;
  } catch {
    return null;
  }
}

/** 6. GET /api/leases/{id}/schedule?version= */
export function getSchedule(leaseId: string, version?: number): Promise<Schedule> {
  const q = version != null ? `?version=${version}` : "";
  return call(
    () => http<Schedule>(`/api/leases/${encodeURIComponent(leaseId)}/schedule${q}`),
    () => {
      const versions = FIXTURE_SCHEDULES[leaseId];
      if (!versions) throw new ApiError(404, `404 no schedule for ${leaseId}`);
      const v = version != null ? String(version) : Object.values(versions).find((s) => s.active)?.version.toString() ?? "1";
      const s = versions[v];
      if (!s) throw new ApiError(404, `404 ${leaseId} has no schedule v${v}`);
      return clone(s);
    },
  );
}

/**
 * EXTENSION: GET /api/leases/{id}/versions — each version's abstracted terms
 * (page, box, quote, confidence) and who confirmed it. The fixtures carry no
 * abstraction, so fixtures mode has none.
 */
export function getLeaseVersions(leaseId: string): Promise<LeaseVersion[]> {
  return call(
    () => http<LeaseVersion[]>(`/api/leases/${encodeURIComponent(leaseId)}/versions`),
    () => [],
  );
}

/**
 * EXTENSION: confirm a lease version = approve its LEASE_ABSTRACTION work item
 * (POST /api/items/{id}/actions/approve). The server's can() decides.
 */
export function confirmLeaseVersion(itemId: number): Promise<{ state: string }> {
  return call(
    () => http<{ state: string }>(`/api/items/${itemId}/actions/approve`, { method: "POST" }),
    () => {
      throw new ApiError(409, "409 lease versions cannot be confirmed in fixtures mode");
    },
  );
}

/** 7. GET /api/audit?lease_id= */
export function getAudit(leaseId?: string): Promise<AuditResponse> {
  const q = leaseId ? `?lease_id=${encodeURIComponent(leaseId)}` : "";
  return call(
    () => http<AuditResponse>(`/api/audit${q}`),
    () => ({
      events: clone(fx.audit).filter((e) => !leaseId || e.lease_id === leaseId),
      chain_verified: true,
      broken_at: null,
    }),
  );
}

/** 8. POST /api/ingest/payment */
export function ingestPayment(payment: Record<string, unknown>): Promise<unknown> {
  return call(
    () => http<unknown>("/api/ingest/payment", { method: "POST", body: JSON.stringify(payment) }),
    () => {
      throw new ApiError(501, "501 payment ingest needs the live API");
    },
  );
}

/** 9. POST /api/ingest/document (multipart) */
export function ingestDocument(file: File): Promise<unknown> {
  const form = new FormData();
  form.append("file", file);
  return call(
    () => http<unknown>("/api/ingest/document", { method: "POST", body: form }),
    () => {
      throw new ApiError(501, "501 document ingest needs the live API");
    },
  );
}

/** GET /api/documents/{sha}/pages (named in §16 for box scaling). */
/**
 * The wire shape of GET /api/documents/{sha}/pages.
 *
 * It numbers each page `number` and names the document `sha256`; everything on
 * this side calls those `page` and `doc_id`. The two were not the same shape,
 * so the page lookup in the viewer never matched and no citation box could
 * draw. Normalising here keeps that mismatch in one place.
 */
interface WireDocumentPages {
  sha256: string;
  page_count: number;
  pages: Array<{ number: number; width: number; height: number }>;
}

export function getDocumentPages(docId: string): Promise<DocumentPages> {
  return call(
    async () => {
      const wire = await http<WireDocumentPages>(`/api/documents/${encodeURIComponent(docId)}/pages`);
      return {
        doc_id: wire.sha256,
        pages: (wire.pages ?? []).map((p) => ({ page: p.number, width: p.width, height: p.height })),
      };
    },
    () => {
      const d = FIXTURE_DOCUMENTS[docId];
      if (!d) throw new ApiError(404, `404 document ${docId} not in fixtures`);
      return clone(d);
    },
  );
}

/** EXTENSION: GET /api/documents/{doc_id}/file — the PDF bytes (doc_id: sha256 or source_document id). */
export function documentUrl(docId: string): string {
  return source === "fixtures" ? fixtureDocumentUrl(docId) : `${API_URL}/api/documents/${encodeURIComponent(docId)}/file`;
}

/**
 * One rendered page: GET /api/documents/{sha}/pages/{n}.png.
 *
 * The viewer draws these rather than the PDF itself. The server already
 * rasterizes with PyMuPDF and serves the result immutable (the sha names the
 * bytes), so the browser needs no PDF engine, no worker, and no second copy of
 * the document. Citation boxes are positioned as percentages of the page, so
 * the render DPI never enters the arithmetic.
 */
export function pageImageUrl(docId: string, page: number): string {
  if (source === "fixtures") return fixturePageUrl(docId, page);
  return `${API_URL}/api/documents/${encodeURIComponent(docId)}/pages/${page}.png`;
}

/**
 * EXTENSION: GET /api/items/{id}/allowed-actions → {"actions": [...]}.
 * Takes the exception id the screens hold (`exc_42`) and asks for work item `42`.
 */
export function getAllowedActions(exceptionId: string): Promise<AllowedActions> {
  return call(
    () => http<AllowedActions>(`/api/items/${encodeURIComponent(itemIdFor(exceptionId))}/allowed-actions`),
    () => ({ actions: fxAllowed(exceptionId) }),
  );
}

// ---------------------------------------------------------------------------
// EXTENSION: the resolver
// ---------------------------------------------------------------------------

/**
 * GET /api/items/{id}/sources → the sources weighed, the trust decision and its
 * explanation, confidence with its reasons, the route and any open question.
 * Takes a work item id or an exception id (`exc_42`). Fixtures carry no sources.
 */
export function getItemSources(itemOrExceptionId: number | string): Promise<ItemSources> {
  const id = itemIdFor(String(itemOrExceptionId));
  return call(
    () => http<ItemSources>(`/api/items/${encodeURIComponent(id)}/sources`),
    () => ({
      item_id: Number(id) || 0,
      kind: "CHARGE_CHECK",
      state: "PROPOSED",
      sources: [],
      decision: null,
      explanation: null,
      confidence: null,
      confidence_reasons: [],
      route: null,
      asked_to: null,
      payment_due: null,
      question: null,
      computed: false,
    }),
  );
}

/** GET /api/questions[?mine=1] → open questions with due dates and dollars at stake (Today screen). */
export function getQuestions(mine = true): Promise<Questions> {
  return call(
    () => http<Questions>(`/api/questions${mine ? "?mine=1" : ""}`),
    () => ({ business_date: new Date().toISOString().slice(0, 10), total: 0, questions: [] }),
  );
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

/** GET /api/auth/me → actor, or null when not logged in (401). */
export function getMe(): Promise<Actor | null> {
  return call(
    async () => {
      try {
        return await http<Actor>("/api/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    () => clone(fx.actor),
  );
}

/** POST /api/auth/login {email, password} → actor */
export function login(email: string, password: string): Promise<Actor> {
  return call(
    () => http<Actor>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
    () => {
      const id = FIXTURE_EMAILS[email.trim().toLowerCase()] ?? "PER-CTRL";
      fx.actor = FIXTURE_ACTORS.find((a) => a.id === id) ?? FIXTURE_ACTORS[0];
      return clone(fx.actor);
    },
  );
}

/** EXTENSION: POST /api/auth/logout */
export function logout(): Promise<void> {
  return call(
    () => http<void>("/api/auth/logout", { method: "POST" }),
    () => {
      fx.actor = null;
    },
  );
}

/** GET /api/auth/demo-actors → actors, or [] when demo mode is off (404/403). */
export function getDemoActors(): Promise<Actor[]> {
  return call(
    async () => {
      try {
        return await http<Actor[]>("/api/auth/demo-actors");
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 403)) return [];
        throw e;
      }
    },
    () => clone(FIXTURE_ACTORS),
  );
}

/** POST /api/auth/demo-switch {actor_id} → actor */
export function demoSwitch(actorId: string): Promise<Actor> {
  return call(
    () => http<Actor>("/api/auth/demo-switch", { method: "POST", body: JSON.stringify({ actor_id: actorId }) }),
    () => {
      const a = FIXTURE_ACTORS.find((x) => x.id === actorId);
      if (!a) throw new ApiError(404, `404 actor ${actorId}`);
      fx.actor = a;
      return clone(a);
    },
  );
}

// ---------------------------------------------------------------------------
// Demo: run summary and reset (C2)
// ---------------------------------------------------------------------------

/**
 * EXTENSION: GET /api/summary/month?period=YYYY-MM&entity= — the month's run
 * summary ("January 2026, ...: 5 clinics, 12 charges checked, ..."), every
 * number with its drill-down. Blank entity = every entity. Live API only.
 */
export function getMonthSummary(period: string, entity?: string): Promise<MonthSummary> {
  const q = new URLSearchParams({ period, entity: entity ?? "" });
  return call(
    () => http<MonthSummary>(`/api/summary/month?${q.toString()}`),
    () => {
      throw new ApiError(501, "501 the month summary needs the live API");
    },
  );
}

/** EXTENSION: GET /api/summary/month/items — exactly the rows behind one number of the month summary. */
export function getMonthSummaryItems(period: string, metric: MonthMetricName, entity?: string): Promise<MonthSummaryRow[]> {
  const q = new URLSearchParams({ period, metric, entity: entity ?? "" });
  return call(
    () => http<MonthSummaryRow[]>(`/api/summary/month/items?${q.toString()}`),
    () => [],
  );
}

/**
 * EXTENSION: POST /api/demo/reset — restore the demo snapshot (controller
 * only; 403 for anyone else, recorded as a denied event; 404 when demo mode
 * is off). Replaces the audit trail with the snapshot's.
 */
export function resetDemo(): Promise<DemoResetResult> {
  return call(
    () => http<DemoResetResult>("/api/demo/reset", { method: "POST" }),
    () => {
      throw new ApiError(501, "501 demo reset needs the live API");
    },
  );
}

/** EXTENSION (B9): POST /api/items/{id}/why — two or three sentences plus the rows used. */
export function askWhy(itemId: number | string, question?: string): Promise<WhyAnswer> {
  return call(
    () =>
      http<WhyAnswer>(`/api/items/${encodeURIComponent(String(itemId))}/why`, {
        method: "POST",
        body: JSON.stringify(question ? { question } : {}),
      }),
    () => {
      throw new ApiError(501, "501 Why? needs the live API");
    },
  );
}

/**
 * EXTENSION (C8): POST /api/pairing/codes — a one-time code (ten minutes, works
 * once) that pairs an ASI:One chat with the signed-in person. Show it on Today;
 * they send "pair <code>" to the Northbay Lease Desk agent.
 */
export function createPairingCode(): Promise<PairingCode> {
  return call(
    () => http<PairingCode>("/api/pairing/codes", { method: "POST" }),
    () => {
      throw new ApiError(501, "501 pairing needs the live API");
    },
  );
}

/** EXTENSION (C8): GET /api/pairing — the signed-in person's live chat pairings. */
export function getPairings(): Promise<PairingList> {
  return call(
    () => http<PairingList>("/api/pairing"),
    () => ({ pairings: [] }),
  );
}

/** EXTENSION (C8): POST /api/pairing/{id}/revoke — unpair one of your chats (204). */
export function revokePairing(pairingId: number): Promise<void> {
  return call(
    () => http<void>(`/api/pairing/${encodeURIComponent(String(pairingId))}/revoke`, { method: "POST" }),
    () => {
      throw new ApiError(501, "501 pairing needs the live API");
    },
  );
}

/** EXTENSION (B9): POST /api/evidence-packs — the PDF (auditor or controller). */
export async function requestEvidencePack(
  subject: EvidencePackSubject,
): Promise<{ pdf: Blob; chainVerified: boolean | null; brokenSeq: number | null }> {
  if (source === "fixtures") throw new ApiError(501, "501 evidence packs need the live API");
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/evidence-packs`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/pdf", "Content-Type": "application/json" },
      body: JSON.stringify({ subject }),
    });
  } catch (e) {
    throw unreachable(e);
  }
  setHealth(REACHABLE);
  if (res.status === 401) redirectToLogin();
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, `${res.status} ${detail}`);
  }
  // The stamp is always in the PDF; these headers are only readable cross-origin
  // if the API exposes them (CORS expose_headers), so null means "see the PDF".
  const verified = res.headers.get("X-Chain-Verified");
  const broken = res.headers.get("X-Chain-Broken-Seq");
  return {
    pdf: await res.blob(),
    chainVerified: verified === null ? null : verified === "true",
    brokenSeq: broken ? Number(broken) : null,
  };
}

/** The live API's PDF route needs the session cookie; fixtures are static files. */
export function documentNeedsCredentials(): boolean {
  return source === "api";
}

// ---------------------------------------------------------------------------
// Disputes and obligations (backend/app/api/disputes.py, obligations.py).
// No fixtures yet: in fixtures mode the register and the calendar are empty
// and a dispute read or write is a 404.
// ---------------------------------------------------------------------------

const EMPTY_DISPUTES: DisputeList = {
  counts: { drafted: 0, sent: 0, acknowledged: 0, credited: 0, partially_credited: 0, refused: 0 },
  total: 0,
  disputes: [],
};

function noFixture(what: string): never {
  throw new ApiError(404, `404 ${what} is not available in fixtures mode`);
}

function query(params: Record<string, string | number | undefined>): string {
  const qs = new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== "")
      .map(([k, v]) => [k, String(v)]),
  ).toString();
  return qs ? `?${qs}` : "";
}

/** GET /api/disputes?status=&clinic_id= → the dispute register */
export function getDisputes(params: { status?: string; clinic_id?: string } = {}): Promise<DisputeList> {
  return call(
    () => http<DisputeList>(`/api/disputes${query(params)}`),
    () => clone(EMPTY_DISPUTES),
  );
}

/** GET /api/disputes/{id} → letter, status history, receivable */
export function getDispute(disputeId: string): Promise<DisputeDetail> {
  return call(
    () => http<DisputeDetail>(`/api/disputes/${encodeURIComponent(disputeId)}`),
    () => noFixture(`dispute ${disputeId}`),
  );
}

/** POST /api/disputes/{id}/approve {reason?} → the regional manager approves the letter; the gateway sends it */
export function approveDisputeLetter(disputeId: string, reason?: string): Promise<DisputeDetail> {
  return call(
    () =>
      http<DisputeDetail>(`/api/disputes/${encodeURIComponent(disputeId)}/approve`, {
        method: "POST",
        body: JSON.stringify(reason ? { reason } : {}),
      }),
    () => noFixture(`dispute ${disputeId}`),
  );
}

/** POST /api/disputes/{id}/receivable/approve {reason?} → controller only: recognise the landlord receivable */
export function approveDisputeReceivable(disputeId: string, reason?: string): Promise<DisputeDetail> {
  return call(
    () =>
      http<DisputeDetail>(`/api/disputes/${encodeURIComponent(disputeId)}/receivable/approve`, {
        method: "POST",
        body: JSON.stringify(reason ? { reason } : {}),
      }),
    () => noFixture(`dispute ${disputeId}`),
  );
}

/** POST /api/disputes/{id}/reply → record the landlord's reply (AP clerk or controller) */
export function recordDisputeReply(disputeId: string, reply: DisputeReply): Promise<DisputeDetail> {
  return call(
    () =>
      http<DisputeDetail>(`/api/disputes/${encodeURIComponent(disputeId)}/reply`, {
        method: "POST",
        body: JSON.stringify(reply),
      }),
    () => noFixture(`dispute ${disputeId}`),
  );
}

/** GET /api/obligations?within_days=&lease_id=&kind= → critical dates from the business date */
export function getObligations(
  params: { within_days?: number; lease_id?: string; kind?: string } = {},
): Promise<ObligationList> {
  return call(
    () => http<ObligationList>(`/api/obligations${query(params)}`),
    () => ({
      today: new Date().toISOString().slice(0, 10),
      within_days: params.within_days ?? 365,
      total: 0,
      obligations: [],
    }),
  );
}

/** GET /api/policies */
export function getPolicies(): Promise<PolicyList> {
  return call(
    () => http<PolicyList>("/api/policies"),
    () => ({ counts: { proposed: 0, approved: 0, rejected: 0, retired: 0 }, policies: [] }),
  );
}

/** GET /api/policies/{id} */
export function getPolicy(id: number): Promise<PolicyDetail> {
  return call(
    () => http<PolicyDetail>(`/api/policies/${id}`),
    () => {
      throw new ApiError(404, `404 no policy ${id} in fixtures mode`);
    },
  );
}

/** POST /api/policies/{id}/backtest */
export function backtestPolicy(id: number): Promise<BacktestRun> {
  return call(
    () => http<BacktestRun>(`/api/policies/${id}/backtest`, { method: "POST" }),
    () => {
      throw new ApiError(409, "409 backtests need the live API");
    },
  );
}

/** Approve or reject a policy = that action on its POLICY work item; can() decides. */
export function decidePolicy(workItemId: number, action: "approve" | "reject", reason?: string): Promise<{ state: string }> {
  return call(
    () =>
      http<{ state: string }>(`/api/items/${workItemId}/actions/${action}`, {
        method: "POST",
        body: JSON.stringify(reason ? { reason } : {}),
      }),
    () => {
      throw new ApiError(409, "409 policies cannot be decided in fixtures mode");
    },
  );
}

/** POST /api/policies/onboard (controller): queue the learner over a year's history. */
export function onboardPolicies(entityId: string, year = 2025): Promise<{ job_id: number; entity_id: string; year: number }> {
  return call(
    () =>
      http<{ job_id: number; entity_id: string; year: number }>("/api/policies/onboard", {
        method: "POST",
        body: JSON.stringify({ entity_id: entityId, year }),
      }),
    () => {
      throw new ApiError(409, "409 onboarding needs the live API");
    },
  );
}
