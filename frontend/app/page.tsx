"use client";

import { ChainVerdict } from "@/components/data/HashChain";
import { BatchPanel } from "@/components/month/BatchPanel";
import { ActivityFeed } from "@/components/today/ActivityFeed";
import { HeroCard, pickHero } from "@/components/today/HeroCard";
import { QueueTable, toQueueRows } from "@/components/today/QueueTable";
import { Tiles } from "@/components/today/Tiles";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/States";
import { ApiError, exceptionIdFor } from "@/lib/api";
import { day, humanize, money, timestamp } from "@/lib/format";
import { useAudit, useChargeChecks, useExceptions, useLeases, useMe, useMonthSummary, useQuestions, useSummary } from "@/lib/hooks";
import { attemptLabel, monthLong } from "@/lib/labels";
import type { AuditEvent } from "@/lib/types";
import Link from "next/link";
import { useMemo } from "react";

const OPEN_STATES = new Set(["NEW", "PROPOSED", "NEEDS_INFO", "HELD"]);

export default function TodayPage() {
  const me = useMe();
  const summary = useSummary();
  const exceptions = useExceptions();
  const leases = useLeases();
  const checks = useChargeChecks();
  const role = me.data?.role ?? "controller";
  const asOf = summary.data?.as_of ?? null;

  const rows = useMemo(() => toQueueRows((exceptions.data ?? []).filter((e) => e.status !== "balanced"), leases.data), [exceptions.data, leases.data]);
  const leasesWithIssues = (leases.data ?? []).filter((l) => l.status !== "balanced").length;

  // A regional manager sees their own region's holds; an item with no region on record stays in view rather than vanishing.
  const regionRows = useMemo(() => {
    if (role !== "regional_manager" || !me.data?.region_id) return rows;
    const mine = new Set(
      (checks.data ?? []).filter((c) => OPEN_STATES.has(c.state) && (c.region_id == null || c.region_id === me.data!.region_id)).map((c) => c.exception_id),
    );
    return checks.data ? rows.filter((r) => mine.has(r.exception_id)) : rows;
  }, [role, me.data, rows, checks.data]);

  const hero = pickHero(regionRows, asOf);
  const heroLease = hero ? leases.data?.find((l) => l.lease_id === hero.lease_id) : undefined;
  const queueRows = role === "regional_manager" ? regionRows : rows;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow">
            {humanize(role)} · as of {asOf ? monthLong(asOf) : "…"}
          </div>
          <h1 className="text-2xl font-semibold">Today</h1>
        </div>
        <p className="max-w-md text-sm text-ink-muted md:text-right">The model reads, the code calculates. Every figure below comes from the engine.</p>
      </div>

      {role === "ap_clerk" ? (
        <ApHero asOf={asOf} />
      ) : role === "auditor" ? (
        <AuditorHero />
      ) : exceptions.isLoading ? (
        <LoadingBlock rows={2} label="Loading today's item" className="min-h-[11rem] rounded-md border border-line bg-surface p-6" />
      ) : hero ? (
        <HeroCard ex={hero} lease={heroLease} eyebrow={role === "regional_manager" ? "Your region · needs a decision" : "Needs you first"} />
      ) : exceptions.isSuccess ? (
        <EmptyState title="Nothing waits on you.">Every charge this month matched its lease, or has been decided.</EmptyState>
      ) : null}

      <Tiles summary={summary.data} loading={summary.isLoading} error={summary.isError} leasesNeedingAttention={leases.data ? leasesWithIssues : undefined} />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Card>
          <CardHeader
            eyebrow={role === "regional_manager" ? `Queue · ${me.data?.region_id ?? "your region"}` : "Queue"}
            title={role === "auditor" ? "Open exceptions (read only)" : "Exceptions"}
            actions={
              <Link href="/exceptions" className="text-sm text-ink-muted hover:text-accent">
                {exceptions.data ? `${queueRows.length} open · all` : "All"} →
              </Link>
            }
          />
          {exceptions.isLoading ? (
            <CardBody>
              <LoadingBlock rows={3} label="Loading exceptions" className="min-h-[19rem]" />
            </CardBody>
          ) : exceptions.isError ? (
            <CardBody>
              <ErrorState title="Could not load exceptions" error={exceptions.error} onRetry={() => exceptions.refetch()} />
            </CardBody>
          ) : !queueRows.length ? (
            <CardBody>
              <EmptyState title="No open exceptions.">Every payment matched its schedule.</EmptyState>
            </CardBody>
          ) : (
            <QueueTable rows={queueRows} compact dense />
          )}
        </Card>

        <div className="space-y-5">
          {role === "regional_manager" ? <QuestionsPanel /> : null}
          {role === "auditor" ? <RefusedPanel /> : null}
          <Card>
            <CardHeader eyebrow="Agents" title="Latest activity" />
            <CardBody>
              <ActivityFeed />
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}

/** The AP clerk's first question: can the month go out? */
function ApHero({ asOf }: { asOf: string | null }) {
  const period = asOf?.slice(0, 7) ?? "";
  const month = useMonthSummary(period);
  const notLive = month.error instanceof ApiError && month.error.status === 501;
  return (
    <Card data-testid="ap-hero">
      <CardHeader
        eyebrow="Batch readiness"
        title={asOf ? `${monthLong(asOf)} payment batch` : "Payment batch"}
        actions={
          <Link href="/month" className="text-sm text-ink-muted hover:text-accent">
            Month run →
          </Link>
        }
      />
      <CardBody>
        {!period || month.isLoading ? (
          <LoadingBlock rows={2} label="Loading the batch" className="min-h-[7rem]" />
        ) : notLive ? (
          <EmptyState title="Batch readiness needs the live API.">The offline demo has no month run to report on.</EmptyState>
        ) : month.isError ? (
          <ErrorState title="Could not load the batch" error={month.error} onRetry={() => month.refetch()} />
        ) : month.data ? (
          <BatchPanel summary={month.data} compact />
        ) : null}
      </CardBody>
    </Card>
  );
}

/** The auditor's first question: does the chain still verify? */
function AuditorHero() {
  const audit = useAudit();
  const refused = (audit.data?.events ?? []).filter((e) => !e.allowed).length;
  return (
    <Card data-testid="auditor-hero">
      <CardHeader
        eyebrow="Trust"
        title="The audit trail"
        actions={
          <Link href="/audit" className="text-sm text-ink-muted hover:text-accent">
            Open →
          </Link>
        }
      />
      <CardBody className="flex items-center justify-between gap-6">
        {audit.isLoading ? (
          <LoadingBlock rows={1} label="Verifying the chain" />
        ) : audit.isError ? (
          <ErrorState title="Could not read the audit trail" error={audit.error} onRetry={() => audit.refetch()} className="flex-1" />
        ) : audit.data ? (
          <>
            <ChainVerdict verified={audit.data.chain_verified} brokenAt={audit.data.broken_at ?? audit.data.broken_seq} count={audit.data.events.length} />
            <div className="text-right">
              <div className="num text-3xl font-semibold">{refused}</div>
              <div className="text-sm text-ink-muted">refused attempt{refused === 1 ? "" : "s"}, kept in the chain</div>
            </div>
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}

/** Questions the agents asked this person. */
function QuestionsPanel() {
  const q = useQuestions(true);
  return (
    <Card>
      <CardHeader
        eyebrow="Asked of you"
        title="Open questions"
        actions={
          <Link href="/questions" className="text-sm text-ink-muted hover:text-accent">
            All →
          </Link>
        }
      />
      <CardBody>
        {q.isLoading ? (
          <LoadingBlock rows={2} label="Loading questions" className="min-h-[7rem]" />
        ) : q.isError ? (
          <ErrorState title="Questions unavailable" error={q.error} onRetry={() => q.refetch()} />
        ) : !q.data?.questions.length ? (
          <EmptyState title="No open questions.">The agents have nothing they need you to settle.</EmptyState>
        ) : (
          <ul className="divide-y divide-line">
            {q.data.questions.slice(0, 5).map((it) => (
              <li key={it.id} className="py-2.5 first:pt-0 last:pb-0">
                <Link href={`/exceptions/${exceptionIdFor(it.work_item_id)}`} className="text-sm font-medium hover:text-accent">
                  {it.title}
                </Link>
                <p className="line-clamp-2 text-sm text-ink-soft">{it.body}</p>
                <div className="mt-0.5 text-xs text-ink-muted">
                  {it.amount_at_stake != null ? <span className="num">{money(it.amount_at_stake)} at stake · </span> : null}
                  {it.due_on ? `due ${day(it.due_on)}` : `asked ${day(it.asked_at)}`}
                  {it.overdue ? <span className="text-bad"> · overdue</span> : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

/** Attempts the database refused: first-class rows, not errors. */
function RefusedPanel() {
  const audit = useAudit();
  const refused = (audit.data?.events ?? [])
    .filter((e) => !e.allowed)
    .sort((a, b) => b.seq - a.seq)
    .slice(0, 5);
  return (
    <Card>
      <CardHeader
        eyebrow="Refused"
        title="Attempts the system refused"
        actions={
          <Link href="/audit" className="text-sm text-ink-muted hover:text-accent">
            Audit →
          </Link>
        }
      />
      <CardBody>
        {audit.isLoading ? (
          <LoadingBlock rows={2} label="Loading activity" className="min-h-[14rem]" />
        ) : !refused.length ? (
          <EmptyState title="Nothing refused yet.">Every attempt so far was within its role.</EmptyState>
        ) : (
          <ul className="divide-y divide-line">
            {refused.map((e: AuditEvent) => (
              <li key={e.seq} className="py-2.5 first:pt-0 last:pb-0">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-medium">{e.actor_name ?? e.actor_id}</span>
                  <span className="rounded-xs bg-bad-soft px-1.5 text-2xs font-semibold uppercase text-bad">Refused</span>
                </div>
                <div className="text-sm text-ink-soft">
                  {attemptLabel(e.action)} <span className="text-ink-muted">{e.subject_type.replace(/_/g, " ")}</span>{" "}
                  <span className="font-mono text-xs text-ink-muted">{e.subject_id}</span>
                </div>
                {e.reason ? <div className="text-xs text-ink-muted">{e.reason}</div> : null}
                <div className="mt-0.5 text-2xs text-ink-faint">{timestamp(e.at)}</div>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
