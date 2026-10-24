"use client";

/**
 * The live mirror (SpacetimeDB module `leasedesk-live`, spacetime/).
 *
 * The backend publishes every committed change to a charge check into
 * `desk_status` (backend/app/work/live.py). This file only listens: on any
 * insert or update it invalidates the queries an approval can change, so the
 * screens refetch from the API. Nothing here is shown or trusted as data —
 * the API (Postgres) stays the only source of truth, and the mirror is just
 * the doorbell that says "ask again".
 *
 * Off unless NEXT_PUBLIC_SPACETIME_URI and NEXT_PUBLIC_SPACETIME_DB are set:
 * no connection, no error, fixtures mode untouched. A connection failure is
 * a console warning; the app works exactly as it does without the mirror.
 *
 * One WebSocket per tab, shared by every hook that listens. The SDK and the
 * generated bindings are loaded on first use, so a build without the env
 * ships them in a chunk nobody downloads.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, useSyncExternalStore } from "react";
import type { DbConnection } from "./spacetime";
import type { AgentStep } from "./spacetime/types";

/** Every query an approve, hold or posting can change (hooks.ts AFTER_ACTION, plus the month view). */
export const LIVE_QUERY_KEYS = [
  "exceptions",
  "summary",
  "exception",
  "audit",
  "charge-checks",
  "allowed-actions",
  "leases",
  "month-summary",
  "month-summary-items",
];

export interface LiveConfig {
  uri: string;
  database: string;
}

/** The env, read as literals so Next inlines them at build time. */
export function liveConfig(): LiveConfig | null {
  const uri = process.env.NEXT_PUBLIC_SPACETIME_URI;
  const database = process.env.NEXT_PUBLIC_SPACETIME_DB;
  return uri && database ? { uri, database } : null;
}

/**
 * The mirror's connection, for the shell's live indicator.
 * - off: no env, so no mirror. A normal state, not an error.
 * - connecting: first connection, not subscribed yet.
 * - connected: subscribed; changes arrive as they commit.
 * - reconnecting: the connection dropped and the SDK is retrying.
 * - lost: could not connect, or gave up; screens refresh as usual.
 */
export type LiveState = "off" | "connecting" | "connected" | "reconnecting" | "lost";

let liveState: LiveState = "off";
const stateListeners = new Set<() => void>();

function setLiveState(next: LiveState) {
  if (next === liveState) return;
  liveState = next;
  stateListeners.forEach((fn) => fn());
}

function subscribeLiveState(fn: () => void): () => void {
  stateListeners.add(fn);
  return () => stateListeners.delete(fn);
}

/** Read the connection state without joining it (the indicator; useLiveStatus does the joining). */
export function useLiveConnection(): LiveState {
  return useSyncExternalStore(subscribeLiveState, () => liveState, () => "off");
}

interface Listener {
  onStatus?: () => void;
  onSteps?: (steps: AgentStep[]) => void;
}

interface Shared {
  conn: DbConnection | null;
  listeners: Set<Listener>;
  ready: boolean;
  closed: boolean;
}

let shared: Shared | null = null;

function steps(conn: DbConnection): AgentStep[] {
  return Array.from(conn.db.agentStep.iter()).sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

async function connect(cfg: LiveConfig, s: Shared): Promise<void> {
  const { DbConnection, tables } = await import("./spacetime");
  if (s.closed) return;
  const status = () => {
    // The rows that arrive with the subscription itself are history, not news.
    if (s.ready) for (const l of s.listeners) l.onStatus?.();
  };
  let wired = false;
  s.conn = DbConnection.builder()
    .withUri(cfg.uri)
    .withDatabaseName(cfg.database)
    .withAutomaticReconnect()
    .onConnect((conn) => {
      if (s.closed) return;
      // A reconnect keeps the SDK's handles and subscription; wire once.
      if (wired) {
        setLiveState("connected");
        return;
      }
      wired = true;
      conn.db.deskStatus.onInsert(status);
      conn.db.deskStatus.onUpdate(status);
      conn.db.agentStep.onInsert(() => {
        if (s.ready) for (const l of s.listeners) l.onSteps?.(steps(conn));
      });
      conn
        .subscriptionBuilder()
        .onApplied(() => {
          s.ready = true;
          setLiveState("connected");
          for (const l of s.listeners) l.onSteps?.(steps(conn));
        })
        .onError(() => {
          setLiveState("lost");
          console.warn("live mirror: subscription failed; screens refresh as usual");
        })
        .subscribe([tables.deskStatus, tables.agentStep]);
    })
    .onConnectError((_ctx, err, nextAttempt) => {
      if (s.closed) return;
      setLiveState(nextAttempt === undefined ? "lost" : "reconnecting");
      console.warn("live mirror: could not connect", err);
    })
    .onDisconnect((_ctx, _err, nextAttempt) => {
      if (s.closed) return;
      setLiveState(nextAttempt === undefined ? "lost" : "reconnecting");
    })
    .build();
}

/** Join the tab's connection (opening it on first use); returns leave(). */
function join(cfg: LiveConfig, listener: Listener): () => void {
  if (!shared) {
    const s: Shared = { conn: null, listeners: new Set(), ready: false, closed: false };
    setLiveState("connecting");
    connect(cfg, s).catch((err) => {
      if (!s.closed) setLiveState("lost");
      console.warn("live mirror: could not start", err);
    });
    shared = s;
  }
  const s = shared;
  s.listeners.add(listener);
  if (s.ready && s.conn) listener.onSteps?.(steps(s.conn));
  return () => {
    s.listeners.delete(listener);
    if (s.listeners.size === 0 && shared === s) {
      shared = null;
      s.closed = true;
      s.conn?.disconnect();
      setLiveState("off");
    }
  };
}

/**
 * Mount once (app/providers.tsx): while mounted, any change another window,
 * the agent or the gateway commits makes this window's queue, tiles and
 * detail refetch. Coalesced, so a burst of postings is one refetch.
 * Returns the connection state ("off" when the mirror is not configured).
 */
export function useLiveStatus(): LiveState {
  const qc = useQueryClient();
  const state = useLiveConnection();
  useEffect(() => {
    const cfg = liveConfig();
    if (!cfg) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const leave = join(cfg, {
      onStatus: () => {
        clearTimeout(timer);
        timer = setTimeout(() => {
          for (const k of LIVE_QUERY_KEYS) void qc.invalidateQueries({ queryKey: [k] });
        }, 150);
      },
    });
    return () => {
      clearTimeout(timer);
      leave();
    };
  }, [qc]);
  return state;
}

/** The most recent agent steps (oldest first), live; [] when the mirror is off. */
export function useAgentSteps(limit = 50): AgentStep[] {
  const [rows, setRows] = useState<AgentStep[]>([]);
  useEffect(() => {
    const cfg = liveConfig();
    if (!cfg) return;
    return join(cfg, { onSteps: (all) => setRows(all.slice(-limit)) });
  }, [limit]);
  return rows;
}
