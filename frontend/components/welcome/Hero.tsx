"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { CountUp } from "@/components/data/CountUp";
import { money, signedMoney } from "@/lib/format";
import { sourceLabel } from "@/lib/welcome";
import { DocumentFan } from "./DocumentFan";
import { fanPages } from "./fanPages";
import { Reveal, SourceTag } from "./Section";
import { liabilityLine, useAmendmentCase } from "./useAmendmentCase";

/** The first screen: the number, the three documents it came from, and the way in. */
export function Hero() {
  const { id, detail, source, pages } = useAmendmentCase();
  const inv = detail?.investigation ?? null;
  const headline = liabilityLine(inv?.entries) ?? inv?.liability_delta ?? null;
  const fan = fanPages(detail);

  return (
    <section className="relative mx-auto w-full max-w-6xl px-6 pb-16 pt-14 md:pt-20">
      <div className="grid grid-cols-1 gap-12 lg:grid-cols-[minmax(0,7fr)_minmax(0,6fr)] lg:gap-10">
        <div>
          <Reveal>
            <div className="font-mono text-2xs uppercase tracking-[0.14em] text-accent">
              The lease accountant&rsquo;s seat, filled by software that cannot sign
            </div>
          </Reveal>
          <Reveal delay={0.05}>
            <h1 className="mt-5 text-display font-semibold text-ink">
              {headline != null ? (
                <CountUp value={headline} prefix="$" className="text-accent" />
              ) : (
                <span className="text-accent" data-testid="headline-pending">$ —</span>
              )}
            </h1>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="mt-6 max-w-2xl font-serif text-2xl leading-snug text-ink md:text-[2rem]">
              The amendment was in the mailbox. The books were still running the old schedule.{" "}
              <em>Lease Desk read both.</em>
            </p>
          </Reveal>
          <Reveal delay={0.15}>
            <p className="mt-6 max-w-xl leading-relaxed text-ink-soft">
              Lease Desk reads every lease a coffee chain holds, checks each landlord bill against what the lease says, and
              holds only what is wrong. It proposes the entries. A controller approves them. A gateway posts them. Every step is
              sealed to a hash chain anyone can verify.
            </p>
          </Reveal>
          <Reveal delay={0.2}>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link
                href="/login"
                className="inline-flex h-12 items-center gap-2 rounded-sm bg-accent px-6 font-medium text-accent-ink shadow-raised transition-all duration-fast ease-out hover:bg-accent-strong hover:shadow-glow active:translate-y-px"
              >
                Open the desk <ArrowRight className="h-4 w-4" aria-hidden />
              </Link>
              <a
                href="#story"
                className="inline-flex h-12 items-center gap-2 rounded-sm border border-line bg-raised px-5 font-medium text-ink transition-colors duration-fast ease-out hover:border-line-strong hover:bg-surface"
              >
                Read the three cases ↓
              </a>
            </div>
          </Reveal>
        </div>

        <Reveal delay={0.2}>
          {fan.length ? (
            <DocumentFan pages={fan} state="rest" source={pages} />
          ) : (
            <div className="h-[560px] rounded-sm border border-line bg-surface" aria-hidden />
          )}
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
            <span className="flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rounded-[2px] bg-warn" />what the lease says</span>
            <span className="flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rounded-[2px] bg-bad" />what was billed</span>
            <span className="flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rounded-[2px] bg-accent" />what explains it</span>
          </div>
          {detail ? (
            <p className="num mt-3 text-sm text-ink-soft">
              Schedule {money(detail.expected)} · billed {money(detail.actual)} · <span className="text-bad">{signedMoney(detail.delta)}</span>
              {inv?.liability_before != null && inv.liability_after != null ? (
                <>
                  {" "}· liability {money(inv.liability_before)} → <span className="font-medium text-ink">{money(inv.liability_after)}</span>
                </>
              ) : null}
            </p>
          ) : null}
          {detail ? (
            <div className="mt-2">
              <SourceTag live={source.kind === "live"}>
                {id} · {sourceLabel(source)}
              </SourceTag>
            </div>
          ) : null}
        </Reveal>
      </div>
    </section>
  );
}
