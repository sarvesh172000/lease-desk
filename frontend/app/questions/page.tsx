"use client";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ErrorState, LoadingBlock } from "@/components/ui/States";
import { ApiError, exceptionIdFor } from "@/lib/api";
import { day, humanize, money, timestamp } from "@/lib/format";
import { useAnswerQuestion, useLeases, useMe, useQuestions } from "@/lib/hooks";
import { chargeLabel, placeLabel } from "@/lib/labels";
import type { QuestionItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { MessageSquareText, Send } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

const WHY_LABEL: Record<string, string> = { asked: "asked of you", escalated: "escalated to you", material: "copied to you: material" };

export default function QuestionsPage() {
  const [mine, setMine] = useState(true);
  const q = useQuestions(mine);
  const me = useMe();
  const leases = useLeases();
  const placeOf = useMemo(() => new Map((leases.data ?? []).map((l) => [l.clinic_id, placeLabel(l.location) ?? l.location])), [leases.data]);
  const rows = q.data?.questions ?? [];
  const overdue = rows.filter((r) => r.overdue).length;

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="eyebrow">Work · what the agents could not settle alone</div>
          <h1 className="text-2xl font-semibold">
            Questions
            {q.data ? (
              <span className="num ml-2 text-base font-normal text-ink-muted">
                · {q.data.total} open{overdue ? <span className="text-bad"> · {overdue} overdue</span> : null} · as of {day(q.data.business_date)}
              </span>
            ) : null}
          </h1>
        </div>
        <div className="flex rounded-sm border border-line bg-surface p-0.5" role="group" aria-label="Whose questions">
          {(
            [
              [true, "Asked of me"],
              [false, "Everyone in my scope"],
            ] as const
          ).map(([v, l]) => (
            <button key={String(v)} type="button" aria-pressed={mine === v} onClick={() => setMine(v)} className={cn("h-8 rounded-[4px] px-3 text-sm transition-colors", mine === v ? "bg-accent text-accent-ink" : "text-ink-soft hover:bg-sunken")}>
              {l}
            </button>
          ))}
        </div>
      </div>

      {q.isLoading ? (
        <Card className="p-5">
          <LoadingBlock rows={3} label="Loading questions" />
        </Card>
      ) : q.isError ? (
        <Card className="p-5">
          <ErrorState title="Could not load questions" error={q.error} onRetry={() => q.refetch()} />
        </Card>
      ) : !rows.length ? (
        <Card className="flex flex-col items-center gap-3 px-6 py-14 text-center" data-testid="questions-empty">
          <span className="flex h-14 w-14 items-center justify-center rounded-full border border-line bg-raised text-accent">
            <MessageSquareText aria-hidden className="h-7 w-7" strokeWidth={1.5} />
          </span>
          <h2 className="text-lg font-semibold">No open questions</h2>
          <p className="max-w-md text-sm text-ink-muted">
            {mine ? "Nothing waits on you. " : "Nothing waits on anyone in your scope. "}
            When the documents cannot settle a charge, the resolver asks the person who can: a regional manager for a landlord fact, the controller for an accounting judgement, the AP clerk for a payment release. The question appears here with the item it is about and its due date, and the answer goes on the record.
          </p>
          <Link href="/exceptions" className="text-sm text-accent hover:underline">
            See the open exceptions →
          </Link>
        </Card>
      ) : (
        <ul className="space-y-3" data-testid="questions">
          {rows.map((it) => (
            <QuestionCard key={it.id} it={it} place={placeOf.get(it.clinic_id ?? "")} meId={me.data?.id} />
          ))}
        </ul>
      )}
    </div>
  );
}

function QuestionCard({ it, place, meId }: { it: QuestionItem; place?: string; meId?: string }) {
  const answer = useAnswerQuestion();
  const [text, setText] = useState("");
  const canAnswer = it.asked_to === meId || it.escalated_to === meId;
  const notLive = answer.error instanceof ApiError && answer.error.status === 501;
  return (
    <li>
      <Card className={cn("p-4", it.overdue && "border-bad-line")} data-testid="question">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
              <span className="rounded-xs border border-line px-1.5 py-0.5 font-semibold uppercase tracking-wide">{humanize(it.kind)}</span>
              {it.why ? <span>{WHY_LABEL[it.why] ?? it.why}</span> : null}
              <span>· asked {timestamp(it.asked_at)}</span>
              {it.reminders ? <span>· {it.reminders} reminder{it.reminders === 1 ? "" : "s"}</span> : null}
            </div>
            <Link href={`/exceptions/${exceptionIdFor(it.work_item_id)}`} className="mt-1 block text-[1.02rem] font-semibold hover:text-accent">
              {it.title || chargeLabel(it.kind)}
            </Link>
            <div className="text-xs text-ink-muted">
              {place ?? it.clinic_id} {it.period ? `· ${day(it.period)}` : ""} <span className="font-mono">· item {it.work_item_id}</span>
            </div>
          </div>
          <div className="shrink-0 text-right">
            {it.amount_at_stake != null ? <div className="num text-lg font-semibold">{money(it.amount_at_stake)}</div> : null}
            <div className={cn("num text-xs", it.overdue ? "font-semibold text-bad" : "text-ink-muted")}>
              {it.due_on ? `payment due ${day(it.due_on)}` : it.due_at ? `due ${day(it.due_at)}` : "no due date"}
              {it.overdue ? " · overdue" : ""}
            </div>
          </div>
        </div>
        <blockquote className="mt-3 rounded-sm border-l-[3px] border-accent bg-sunken/60 px-3 py-2 text-sm text-ink">
          {it.body}
          <footer className="mt-1 text-xs text-ink-muted">
            {it.asked_by} asked {it.asked_to}
            {it.escalated_to ? `, escalated to ${it.escalated_to}` : ""}
          </footer>
        </blockquote>
        {canAnswer ? (
          <form
            className="mt-3 flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (text.trim()) answer.mutate({ itemId: it.work_item_id, answer: text.trim() });
            }}
          >
            <label className="min-w-0 flex-1">
              <span className="text-xs font-medium text-ink-soft">Your answer, on the record</span>
              <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} className="mt-1 w-full rounded-xs border border-line-strong bg-surface px-2 py-1.5 text-sm text-ink" placeholder="What is true, and how you know" />
            </label>
            <Button type="submit" variant="primary" icon={<Send aria-hidden className="h-4 w-4" />} loading={answer.isPending} disabled={!text.trim()}>
              Answer
            </Button>
          </form>
        ) : (
          <p className="mt-3 text-xs text-ink-muted">Asked of {it.asked_to}; only they can answer it.</p>
        )}
        {answer.isSuccess ? (
          <p role="status" className="mt-2 text-sm text-ok">
            Answered · the item is now {answer.data.state ?? answer.data.status}
          </p>
        ) : answer.isError ? (
          <p role="alert" className="mt-2 text-sm text-bad">
            {notLive ? "Answering needs the live API." : answer.error.message}
          </p>
        ) : null}
      </Card>
    </li>
  );
}
