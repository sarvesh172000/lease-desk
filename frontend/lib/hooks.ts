"use client";

/**
 * Every query and mutation the screens use. Pages and components get data
 * only through these hooks (and `investigate` for the SSE stream), so a
 * redesign can replace any screen without touching how data is fetched.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import {
  approveDisputeLetter,
  approveDisputeReceivable,
  approveException,
  confirmLeaseVersion,
  getAllowedActions,
  getAudit,
  getChargeChecks,
  getDataSource,
  getDemoActors,
  getDispute,
  getDisputes,
  getDocumentPages,
  getException,
  getExceptions,
  getLeaseVersions,
  getLeases,
  getMe,
  getObligations,
  getSchedule,
  getSummary,
  holdException,
  payAsBilledException,
  recordDisputeReply,
  subscribeDataSource,
  type DataSource,
} from "./api";
import type { ActionResult, DisputeDetail, DisputeReply, ItemAction } from "./types";

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

/** A lease's versions with their cited terms and confirmation state. */
export function useLeaseVersions(leaseId: string) {
  return useQuery({ queryKey: ["lease-versions", leaseId], queryFn: () => getLeaseVersions(leaseId), retry: false });
}

/** Confirm a lease version by approving its LEASE_ABSTRACTION item; refetches what it changes. */
export function useConfirmLeaseVersion(leaseId: string) {
  const qc = useQueryClient();
  return useMutation<{ state: string }, Error, number>({
    mutationFn: (itemId) => confirmLeaseVersion(itemId),
    onSettled: () => {
      for (const key of [["lease-versions", leaseId], ["audit"], ["leases"]]) void qc.invalidateQueries({ queryKey: key });
    },
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

/**
 * The controller's override on a held charge: pay the billed amount anyway,
 * with a reason that goes on the record. Same refetches as an approve.
 */
export function usePayAsBilled(exceptionId: string) {
  const qc = useQueryClient();
  return useMutation<ActionResult, Error, string>({
    mutationFn: (reason) => payAsBilledException(exceptionId, reason),
    onSettled: () => {
      for (const k of AFTER_ACTION) void qc.invalidateQueries({ queryKey: [k] });
    },
  });
}

// ---------------------------------------------------------------------------
// Disputes and obligations
// ---------------------------------------------------------------------------

export function useDisputes(params: { status?: string; clinic_id?: string } = {}) {
  return useQuery({ queryKey: ["disputes", params], queryFn: () => getDisputes(params) });
}

export function useDispute(disputeId?: string | null) {
  return useQuery({
    queryKey: ["dispute", disputeId],
    queryFn: () => getDispute(disputeId!),
    enabled: !!disputeId,
    retry: false,
  });
}

/** Everything a dispute action can change on screen. */
const AFTER_DISPUTE = ["dispute", "disputes", "summary", "audit"];

function useDisputeMutation<V>(fn: (vars: V) => Promise<DisputeDetail>) {
  const qc = useQueryClient();
  return useMutation<DisputeDetail, Error, V>({
    mutationFn: fn,
    onSettled: () => {
      for (const k of AFTER_DISPUTE) void qc.invalidateQueries({ queryKey: [k] });
    },
  });
}

/** The regional manager approves the letter; the gateway queues it in the outbox. */
export function useApproveDisputeLetter(disputeId: string) {
  return useDisputeMutation<string | undefined>((reason) => approveDisputeLetter(disputeId, reason));
}

/** The controller approves recognising the landlord receivable. */
export function useApproveDisputeReceivable(disputeId: string) {
  return useDisputeMutation<string | undefined>((reason) => approveDisputeReceivable(disputeId, reason));
}

/** Record the landlord's reply: acknowledged, credit (full or partial) or refusal. */
export function useRecordDisputeReply(disputeId: string) {
  return useDisputeMutation<DisputeReply>((reply) => recordDisputeReply(disputeId, reply));
}

export function useObligations(params: { within_days?: number; lease_id?: string; kind?: string } = {}) {
  return useQuery({ queryKey: ["obligations", params], queryFn: () => getObligations(params) });
}
