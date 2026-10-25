import type { AuditEvent, AuditResponse } from "./types";
import { actorKind, type ActorKind } from "./labels";

/**
 * The audit trail as a chain: what the API says about it, which rows a
 * reader is looking at, and a client-side picture of how it would crack.
 * The verdict is only ever the API's; a simulation changes nothing and says so.
 */

export type Outcome = "all" | "allowed" | "refused";

export interface AuditFilters {
  outcome: Outcome;
  /** An actor id, or a kind: "person", "agent", "system". */
  actor: string;
  action: string;
  subject: string;
  /** A sequence number ("128", "#128") or a hash prefix. */
  query: string;
}

export const NO_FILTERS: AuditFilters = { outcome: "all", actor: "", action: "", subject: "", query: "" };

const KINDS: ActorKind[] = ["person", "agent", "system"];

/** The rows the filters keep, in the order given. */
export function applyFilters(events: AuditEvent[], f: AuditFilters): AuditEvent[] {
  const raw = f.query.trim().toLowerCase();
  const seqOnly = raw.startsWith("#");
  const q = raw.replace(/^#/, "");
  const seq = /^\d+$/.test(q) ? Number(q) : null;
  return events.filter((e) => {
    if (f.outcome === "allowed" && !e.allowed) return false;
    if (f.outcome === "refused" && e.allowed) return false;
    if (f.actor) {
      if ((KINDS as string[]).includes(f.actor)) {
        if (actorKind(e.actor_id) !== f.actor) return false;
      } else if (e.actor_id !== f.actor) return false;
    }
    if (f.action && e.action !== f.action) return false;
    if (f.subject && e.subject_type !== f.subject) return false;
    if (q) {
      if (seq != null && e.seq === seq) return true;
      if (seqOnly) return false;
      const h = (e.hash ?? "").toLowerCase();
      const p = (e.prev_hash ?? "").toLowerCase();
      if (!h.startsWith(q) && !p.startsWith(q)) return false;
    }
    return true;
  });
}

/** The distinct values a filter can take, for the menus. */
export function filterOptions(events: AuditEvent[]) {
  const actors = new Map<string, string>();
  const actions = new Set<string>();
  const subjects = new Set<string>();
  for (const e of events) {
    actors.set(e.actor_id, e.actor_name ?? e.actor_id);
    actions.add(e.action);
    subjects.add(e.subject_type);
  }
  return { actors: Array.from(actors, ([id, name]) => ({ id, name })), actions: Array.from(actions).sort(), subjects: Array.from(subjects).sort() };
}

export interface ChainState {
  /** The API's verdict. */
  verified: boolean;
  /** Where the API says it broke. */
  brokenSeq: number | null;
  /** A client-side what-if, clearly labelled; null when none is on. */
  simulatedSeq: number | null;
  /** The crack shown: the real one wins over a simulated one. */
  crackSeq: number | null;
  count: number;
}

/** What the strip and the banner draw, from the API's answer and an optional simulation. */
export function chainState(resp: AuditResponse | undefined, simulatedSeq: number | null): ChainState {
  const brokenSeq = resp ? (resp.chain_verified ? null : (resp.broken_seq ?? resp.broken_at ?? null)) : null;
  const verified = resp?.chain_verified ?? true;
  return {
    verified,
    brokenSeq,
    simulatedSeq: verified ? simulatedSeq : null,
    crackSeq: !verified ? brokenSeq : simulatedSeq,
    count: resp?.events.length ?? 0,
  };
}

/** True when the row sits at or after the crack: its seal can no longer be trusted. */
export function afterCrack(seq: number, crackSeq: number | null): boolean {
  return crackSeq != null && seq >= crackSeq;
}

/** Events oldest first, as the chain is built. */
export function ascending(events: AuditEvent[]): AuditEvent[] {
  return [...events].sort((a, b) => a.seq - b.seq);
}

const ZERO = "0".repeat(64);

/**
 * A chain that does not verify, for tests and the fixture screenshot: five
 * events, the fourth's prev_hash no longer the third's hash.
 */
export const BROKEN_CHAIN_FIXTURE: AuditResponse = {
  chain_verified: false,
  broken_seq: 4,
  broken_at: 4,
  events: [
    { seq: 1, at: "2026-07-01T09:12:40Z", actor_id: "agent:reconciliation", actor_name: "Reconciliation", action: "create", subject_type: "work_item", subject_id: "18", allowed: true, reason: null, prev_hash: ZERO, hash: "9f2c1e0a6b7d4c3e5a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f6071" },
    { seq: 2, at: "2026-07-01T09:12:58Z", actor_id: "agent:investigation", actor_name: "Investigation agent", action: "propose", subject_type: "work_item", subject_id: "18", allowed: true, reason: "Found eml_20260618 (trust rank 1)", prev_hash: "9f2c1e0a6b7d4c3e5a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f6071", hash: "4a8b0d2f1c9e7d6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a" },
    { seq: 3, at: "2026-07-01T10:40:19Z", actor_id: "agent:checker", actor_name: "Charge checker", action: "approve", subject_type: "work_item", subject_id: "18", allowed: false, reason: "Role agent may not approve accounting judgments", prev_hash: "4a8b0d2f1c9e7d6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a", hash: "c71e5b3a90d4e2f1a8b6c0d9e7f3a2b14c5d6e7f8091a2b3c4d5e6f708192a3b" },
    { seq: 4, at: "2026-07-01T10:41:02Z", actor_id: "PER-CTRL", actor_name: "Priya Raghunathan", action: "approve", subject_type: "work_item", subject_id: "18", allowed: true, reason: "Approved by a human", human_approved: true, prev_hash: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef", hash: "0be93d7c55e1f2a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b" },
    { seq: 5, at: "2026-07-01T10:41:03Z", actor_id: "system:gateway", actor_name: "Gateway", action: "post", subject_type: "journal_entry", subject_id: "7", allowed: true, reason: null, prev_hash: "0be93d7c55e1f2a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b", hash: "e3f6a2b8d1c0f9e8d7c6b5a4938271605f4e3d2c1b0a9f8e7d6c5b4a39281706" },
  ],
};
