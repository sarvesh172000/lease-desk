"use client";

import { useRef, useState } from "react";
import { useMotionValueEvent, useReducedMotion, useScroll } from "framer-motion";
import { CountUp } from "@/components/data/CountUp";
import { JournalEntryTable } from "@/components/JournalEntryTable";
import { money, signedMoney } from "@/lib/format";
import { TRUST_RANKS } from "@/lib/labels";
import { fanState, sourceLabel, type FanState } from "@/lib/welcome";
import { DocumentFan } from "./DocumentFan";
import { fanPages } from "./fanPages";
import { IntoTheDesk, Reveal, Section, SourceTag } from "./Section";
import { useAmendmentCase } from "./useAmendmentCase";

const STEP_LABEL: Record<FanState, string> = {
  rest: "scroll to walk the case",
  invoice: "01 · the billed line",
  email: "02 · the sentence it relied on",
  figure: "03 · remeasured under ASC 842",
};

/**
 * Beat 1: the hidden amendment, told by scrolling. The fan on the right walks
 * rest → invoice forward (its line boxed) → amendment forward (its sentence
 * boxed) → the remeasured liability in front, counting up to the engine's
 * figure. Every figure and every box is the exception's own.
 */
export function BeatAmendment() {
  const { id, detail, source, pages } = useAmendmentCase();
  const inv = detail?.investigation ?? null;
  const ev = inv?.evidence[0] ?? null;
  const rank = ev ? TRUST_RANKS[ev.trust_rank - 1] : null;
  const fan = fanPages(detail);

  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 70%", "end 60%"] });
  const [state, setState] = useState<FanState>(reduce ? "figure" : "rest");
  useMotionValueEvent(scrollYProgress, "change", (v) => setState(fanState(v, !!reduce)));

  const figure =
    inv?.liability_before != null && inv.liability_after != null ? (
      <div className="rounded-md bg-accent p-4 text-accent-ink shadow-[0_30px_50px_-20px_rgb(var(--shadow)/0.6)]" data-testid="fan-figure">
        <div className="font-mono text-2xs tracking-[0.1em] text-accent-ink/70">LEASE LIABILITY</div>
        <div className="num mt-1 text-xs text-accent-ink/80">{money(inv.liability_before)} →</div>
        <div className="text-2xl font-semibold tracking-tight">
          <CountUp from={inv.liability_before} value={inv.liability_after} prefix="$" duration={1600} />
        </div>
        {inv.liability_delta != null ? <div className="num mt-1 text-xs font-medium text-accent-ink/90">{signedMoney(inv.liability_delta)}</div> : null}
        <div className="mt-2 font-mono text-2xs text-accent-ink/70">
          {inv.entries.length} entries · {inv.balanced ? "balanced" : "not balanced"}
        </div>
      </div>
    ) : undefined;

  const steps: [FanState, string, string][] = [
    ["invoice", "The invoice", detail?.invoice_line ? `${detail.invoice_line.description} · ${money(detail.invoice_line.amount)} billed` : "the billed line"],
    ["email", "The amendment", ev ? `“${ev.quote}”` : "the sentence it relied on"],
    ["figure", "The remeasurement", inv?.liability_before != null && inv.liability_after != null ? `${money(inv.liability_before)} → ${money(inv.liability_after)}` : "the liability, remeasured"],
  ];

  return (
    <Section id="story" className="py-20 md:py-28">
      <div ref={ref} className="grid gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
        <div className="space-y-6">
          <Reveal>
            <div className="eyebrow mb-3 text-accent">1 · The hidden amendment</div>
            <h2 className="text-headline font-semibold">
              {detail ? (
                <>
                  July rent came in <span className="num text-bad">{money(Math.abs(detail.delta))}</span> under schedule. The schedule
                  was wrong, not the bill.
                </>
              ) : (
                "July rent came in under schedule. The schedule was wrong, not the bill."
              )}
            </h2>
            <p className="mt-5 leading-relaxed text-ink-soft">
              An under-bill is a signal, not a gift. The investigation agent searched the mailbox and found a countersigned
              amendment from the landlord&rsquo;s authorised representative: rent down, term extended three years. Lower-ranked
              sources, a property manager&rsquo;s claim, a forged sender and an injection attempt, were set aside. None can
              modify a lease.
            </p>
            {inv ? (
              <p className="mt-4 text-sm text-ink-muted">
                Root cause <span className="text-ink">{inv.root_cause}</span> · confidence{" "}
                <span className="num text-ink">{Math.round(inv.confidence * 100)}%</span>
                {rank ? (
                  <>
                    {" "}
                    · source trusted <span className="text-ink">{rank.short}</span>
                  </>
                ) : null}
              </p>
            ) : null}
            <div className="mt-4">
              {detail ? (
                <SourceTag live={source.kind === "live"}>
                  {id} · {sourceLabel(source)}
                </SourceTag>
              ) : null}
            </div>
          </Reveal>

          {/* the three steps the fan walks, as words, so the story reads without the motion */}
          <ol className="space-y-3 text-sm" data-testid="fan-steps">
            {steps.map(([key, title, body], i) => (
              <li
                key={key}
                className={`flex gap-3 rounded-sm border px-3 py-2 transition-colors duration-base ${state === key ? "border-accent bg-accent-soft" : "border-line bg-surface"}`}
                aria-current={state === key ? "step" : undefined}
              >
                <span className="font-mono text-2xs text-ink-faint">0{i + 1}</span>
                <span className="min-w-0">
                  <span className="block font-medium">{title}</span>
                  <span className="num block text-ink-muted">{body}</span>
                </span>
              </li>
            ))}
          </ol>

          {inv?.liability_before != null && inv.liability_after != null ? (
            <Reveal delay={0.1}>
              <div className="rounded-md border border-line bg-surface p-5">
                <div className="eyebrow">Lease liability, remeasured</div>
                <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
                  <span className="num text-sm text-ink-muted">{money(inv.liability_before)}</span>
                  <span aria-hidden className="text-ink-faint">→</span>
                  <span className="num text-3xl font-semibold tracking-tight">{money(inv.liability_after)}</span>
                  {inv.liability_delta != null ? <span className="num text-sm font-medium text-accent">{signedMoney(inv.liability_delta)}</span> : null}
                </div>
                {inv.rou_before != null && inv.rou_after != null ? (
                  <div className="num mt-2 text-sm text-ink-muted">
                    Right-of-use asset {money(inv.rou_before)} → {money(inv.rou_after)}
                  </div>
                ) : null}
              </div>
            </Reveal>
          ) : null}

          {inv?.entries.length ? (
            <Reveal delay={0.15}>
              <div className="rounded-md border border-line bg-surface p-5">
                <div className="flex items-baseline justify-between">
                  <span className="eyebrow">Proposed entries</span>
                  <span className="font-mono text-2xs text-ink-muted">waiting for the controller</span>
                </div>
                <div className="mt-3">
                  <JournalEntryTable entries={inv.entries} balanced={inv.balanced} reveal dense />
                </div>
              </div>
            </Reveal>
          ) : null}

          {id ? <IntoTheDesk href={`/exceptions/${id}`}>Open it on the money screen</IntoTheDesk> : null}
        </div>

        <div className="lg:sticky lg:top-24 lg:self-start">
          {fan.length ? (
            <DocumentFan pages={fan} state={state} source={pages} figure={figure} />
          ) : (
            <div className="h-[560px] rounded-sm border border-line bg-surface" aria-hidden />
          )}
          <div className="mt-2 flex items-center justify-between font-mono text-2xs text-ink-muted">
            <span>{STEP_LABEL[state]}</span>
            <span>pages are the API&rsquo;s renders · boxes are its citations</span>
          </div>
        </div>
      </div>
    </Section>
  );
}
