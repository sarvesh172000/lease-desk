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
  getDispute,
  getDisputes,
  getObligations,
  recordDisputeReply,
  approveException,
  askWhy,
  backtestPolicy,
  decidePolicy,
  getPolicies,
  getPolicy,
  onboardPolicies,
  confirmLeaseVersion,
  getAllowedActions,
  getApiHealth,
  getAudit,
  getChargeChecks,
  getDataSource,
  getDemoActors,
  getDocumentPages,
  getException,
  getExceptions,
  getItemSources,
  getLeaseVersions,
  getLeases,
  getMe,
  getMonthSummary,
  getMonthSummaryItems,
  getQuestions,
  getSchedule,
  getSummary,
  holdException,
  payAsBilledException,
  performAction,
  requestEvidencePack,
  resetDemo,
  subscribeApiHealth,
  subscribeDataSource,
  type ApiHealth,
  type DataSource,
} from "./api";
import type {
  DisputeDetail,
  DisputeReply, ActionResult, DemoResetResult, BacktestRun, EvidencePackSubject, ItemAction, MonthMetricName, WhyAnswer } from "./types";

export function useDataSource(): DataSource {
  return useSyncExternalStore(subscribeDataSource, getDataSource, () => getDataSource());
}

/** Whether the live API answered the last call; drives the shell's "API unreachable" banner. */
export function useApiHealth(): ApiHealth {
  return useSyncExternalStore(subscribeApiHealth, getApiHealth, getApiHealth);
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
    mutationFn: (action) =>
      action === "approve"
        ? approveException(exceptionId)
        : action === "hold"
          ? holdException(exceptionId)
          : performAction(exceptionId, action),
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

/** The month's run summary for the guided stepper; every number has a drill-down. */
export function useMonthSummary(period: string, entity?: string) {
  return useQuery({ queryKey: ["month-summary", period, entity ?? ""], queryFn: () => getMonthSummary(period, entity) });
}

/** The rows behind one number of the month summary (enabled once a metric is picked). */
export function useMonthSummaryItems(period: string, metric: MonthMetricName | null, entity?: string) {
  return useQuery({
    queryKey: ["month-summary-items", period, metric, entity ?? ""],
    queryFn: () => getMonthSummaryItems(period, metric!, entity),
    enabled: !!metric,
  });
}

/** The controller's demo reset; afterwards every query refetches, since every table changed. */
export function useDemoReset() {
  const qc = useQueryClient();
  return useMutation<DemoResetResult, Error, void>({
    mutationFn: () => resetDemo(),
    onSettled: () => void qc.invalidateQueries(),
  });
}

/** The resolver's view of one item: sources, trust explanation, confidence, route. */
export function useItemSources(itemOrExceptionId?: number | string | null) {
  return useQuery({
    queryKey: ["item-sources", itemOrExceptionId ?? null],
    queryFn: () => getItemSources(itemOrExceptionId!),
    enabled: itemOrExceptionId != null && itemOrExceptionId !== "",
  });
}

/** Open questions waiting on me (or, mine=false, everything in my scope). */
export function useQuestions(mine = true) {
  return useQuery({ queryKey: ["questions", mine], queryFn: () => getQuestions(mine) });
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

/** Every policy with status, version, precedent count and backtest summary. */
export function usePolicies() {
  return useQuery({ queryKey: ["policies"], queryFn: getPolicies });
}

/** One policy: rule, versions, evidence, stored backtest, rejection, citations. */
export function usePolicy(id: number | null | undefined) {
  return useQuery({ queryKey: ["policy", id], queryFn: () => getPolicy(id as number), enabled: id != null, retry: false });
}

/** Run a policy's backtest now; refetches the policy so a refreshed result shows. */
export function useBacktestPolicy(id: number) {
  const qc = useQueryClient();
  return useMutation<BacktestRun, Error, void>({
    mutationFn: () => backtestPolicy(id),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["policy", id] }),
  });
}

/** Approve or reject a policy through its work item. */
export function useDecidePolicy() {
  const qc = useQueryClient();
  return useMutation<{ state: string }, Error, { workItemId: number; action: "approve" | "reject"; reason?: string }>({
    mutationFn: ({ workItemId, action, reason }) => decidePolicy(workItemId, action, reason),
    onSettled: () => {
      for (const k of ["policies", "policy", "audit"]) void qc.invalidateQueries({ queryKey: [k] });
    },
  });
}

/** Controller: queue onboarding over a year's history. */
export function useOnboardPolicies() {
  const qc = useQueryClient();
  return useMutation<{ job_id: number; entity_id: string; year: number }, Error, { entityId: string; year?: number }>({
    mutationFn: ({ entityId, year }) => onboardPolicies(entityId, year),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["policies"] }),
  });
}

/** "Why?" on one item: a 2-3 sentence answer and the rows it rests on (POST /api/items/{id}/why). */
export function useAskWhy(itemId: number | string | null | undefined) {
  return useMutation<WhyAnswer, Error, string | undefined>({
    mutationFn: (question) => askWhy(itemId!, question),
  });
}

/** What an evidence pack download resolves with: the file is already saved. */
export interface EvidencePackResult {
  filename: string;
  bytes: number;
  chainVerified: boolean | null;
  brokenSeq: number | null;
}

/**
 * Download an evidence pack (PDF) and report the chain stamp from the
 * response headers; null when the API does not expose them (see the PDF).
 */
export function useEvidencePack() {
  return useMutation<EvidencePackResult, Error, { subject: EvidencePackSubject; filename: string }>({
    mutationFn: async ({ subject, filename }) => {
      const { pdf, chainVerified, brokenSeq } = await requestEvidencePack(subject);
      const url = URL.createObjectURL(pdf);
      try {
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
      } finally {
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
      return { filename, bytes: pdf.size, chainVerified, brokenSeq };
    },
  });
}
