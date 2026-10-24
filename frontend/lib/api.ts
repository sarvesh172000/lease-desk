/**
 * Typed wrappers for every endpoint in docs/DESIGN.md §16, plus auth.
 *
 * Data source:
 *  - NEXT_PUBLIC_USE_FIXTURES=1  → always fixtures.
 *  - otherwise the API at NEXT_PUBLIC_API_URL (default http://localhost:8000);
 *    if it cannot be reached at all (network error / timeout) the session
 *    switches to fixtures and stays there. HTTP errors are NOT masked: a 403
 *    or 500 from a live API surfaces as an error state.
 */

import type {
  ActionResult,
  Actor,
  AllowedActions,
  AuditResponse,
  DocumentPages,
  ExceptionDetail,
  ExceptionSummary,
  InvestigationEvent,
  ItemAction,
  LeaseSummary,
  Schedule,
  Status,
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
// Data-source state (observable so the header can show a "Fixtures" badge)
// ---------------------------------------------------------------------------

export type DataSource = "api" | "fixtures";
let source: DataSource = FORCE_FIXTURES ? "fixtures" : "api";
const listeners = new Set<() => void>();

export function getDataSource(): DataSource {
  return source;
}
export function subscribeDataSource(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function switchToFixtures(reason: string) {
  if (source === "fixtures") return;
  source = "fixtures";
  if (typeof console !== "undefined") console.warn(`[leasedesk] API unreachable (${reason}); using fixtures`);
  listeners.forEach((fn) => fn());
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

class Unreachable extends Error {}

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
    throw new Unreachable(e instanceof Error ? e.message : String(e));
  } finally {
    clearTimeout(timer);
  }
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

/** Call the API, or the fixture implementation when in / falling back to fixtures mode. */
async function call<T>(live: () => Promise<T>, fixture: () => T | Promise<T>): Promise<T> {
  if (source === "fixtures") return fixture();
  try {
    return await live();
  } catch (e) {
    if (e instanceof Unreachable) {
      switchToFixtures(e.message);
      return fixture();
    }
    throw e;
  }
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
    () => http<ExceptionDetail>(`/api/exceptions/${encodeURIComponent(id)}`),
    () => {
      const d = FIXTURE_EXCEPTION_DETAILS[id];
      if (!d) throw new ApiError(404, `404 exception ${id} not found`);
      return { ...clone(d), status: fxStatus(id, d.status) };
    },
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
 * Any action other than approve: POST /api/items/{item_id}/actions/{action}.
 *
 * There is no /api/exceptions/{id}/hold — holding through that path 404s and
 * leaves the button dead. The queue's own action route takes every human
 * action the state machine has (hold, resume, reject, close), as the same
 * `perform()` the approve route uses, so the answer allowed-actions gave the
 * button is the answer the press gets.
 */
export function performAction(exceptionId: string, action: ItemAction): Promise<ActionResult> {
  return call(
    async () => {
      const res = await http<{ state: string }>(
        `/api/items/${encodeURIComponent(itemIdOf(exceptionId))}/actions/${encodeURIComponent(action)}`,
        { method: "POST" },
      );
      return { exception_id: exceptionId, status: STATUS_BY_STATE[res.state] ?? "pending_review" };
    },
    () => fxAct(exceptionId, action),
  );
}

/** Hold, through the item action route. */
export function holdException(id: string): Promise<ActionResult> {
  return performAction(id, "hold");
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
    switchToFixtures(e instanceof Error ? e.message : String(e));
    return replay();
  }
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

/** EXTENSION: GET /api/documents/{sha}/file — the PDF bytes. */
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
 * The work-item id behind an exception.
 *
 * `/api/exceptions` is keyed by `exc_<n>` and `/api/items` by the integer `n`;
 * they are the same work item. Passing the exception id straight to the items
 * endpoints returns 422 ("Input should be a valid integer") and leaves the
 * Approve button dead, which is the one control the whole screen exists for.
 *
 * The exception payload carries no `item_id`, so the id is derived here rather
 * than at each call site. If the API grows an explicit `item_id`, prefer it.
 */
export function itemIdOf(exceptionId: string): string {
  const match = /^exc_(\d+)$/.exec(exceptionId);
  return match ? match[1] : exceptionId;
}

/** EXTENSION: GET /api/items/{id}/allowed-actions → {"actions": [...]} */
export function getAllowedActions(itemId: string): Promise<AllowedActions> {
  return call(
    () => http<AllowedActions>(`/api/items/${encodeURIComponent(itemIdOf(itemId))}/allowed-actions`),
    () => ({ actions: fxAllowed(itemId) }),
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
