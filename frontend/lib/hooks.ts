"use client";

/**
 * Every query and mutation the screens use. Pages and components get data
 * only through these hooks (and `investigate` for the SSE stream), so a
 * redesign can replace any screen without touching how data is fetched.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import {
  approveException,
  getAllowedActions,
  getAudit,
  getChargeChecks,
  getDataSource,
  getDemoActors,
  getDocumentPages,
  getException,
  getExceptions,
  getLeases,
  getMe,
  getSchedule,
  getSummary,
  holdException,
  subscribeDataSource,
  type DataSource,
} from "./api";
import type { ActionResult, ItemAction } from "./types";

export function useDataSource(): DataSource {
  return useSyncExternalStore(subscribeDataSource, getDataSource, () => getDataSource());
}

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: getMe, staleTime: 60_000 });
}

export function useDemoActors() {
  return useQuery({ queryKey: ["demo-actors"], queryFn: getDemoActors, staleTime: 5 * 60_000, retry: false });
}

export function useLeases() {
  return useQuery({ queryKey: ["leases"], queryFn: getLeases });
}

export function useExceptions() {
  return useQuery({ queryKey: ["exceptions"], queryFn: getExceptions });
}

/** Dashboard tiles: active leases, open exceptions, dollars held (over-bills only), liability. */
export function useSummary() {
  return useQuery({ queryKey: ["summary"], queryFn: getSummary });
}

/** Every charge check of the month, held or not, each openable on the money screen. */
export function useChargeChecks(period?: string) {
  return useQuery({ queryKey: ["charge-checks", period ?? null], queryFn: () => getChargeChecks(period) });
}

export function useException(exceptionId: string) {
  return useQuery({ queryKey: ["exception", exceptionId], queryFn: () => getException(exceptionId) });
}

/** What this person may press on this exception, from can() on the server. */
export function useAllowedActions(exceptionId: string) {
  return useQuery({ queryKey: ["allowed-actions", exceptionId], queryFn: () => getAllowedActions(exceptionId) });
}

export function useSchedule(leaseId: string, version?: number, enabled = true) {
  return useQuery({
    queryKey: ["schedule", leaseId, version ?? "active"],
    queryFn: () => getSchedule(leaseId, version),
    enabled,
    retry: false,
  });
}

export function useAudit(leaseId?: string) {
  return useQuery({ queryKey: ["audit", leaseId ?? null], queryFn: () => getAudit(leaseId) });
}

export function useDocumentPages(docId?: string | null) {
  return useQuery({
    queryKey: ["document-pages", docId],
    queryFn: () => getDocumentPages(docId!),
    enabled: !!docId,
    retry: false,
  });
}

/** Everything an approve or hold can change on screen. */
const AFTER_ACTION = ["exception", "exceptions", "summary", "charge-checks", "leases", "audit", "allowed-actions"];

/**
 * Approve or hold one exception. Resolves with the server's answer (status,
 * work state, posting); on settle every affected query refetches, so the
 * audit trail shows the new row — allowed or denied.
 */
export function useExceptionAction(exceptionId: string) {
  const qc = useQueryClient();
  return useMutation<ActionResult, Error, ItemAction>({
    mutationFn: (action) => (action === "approve" ? approveException(exceptionId) : holdException(exceptionId)),
    onSettled: () => {
      for (const k of AFTER_ACTION) void qc.invalidateQueries({ queryKey: [k] });
    },
  });
}
