"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { CountUp } from "@/components/data/CountUp";
import { money, signedMoney } from "@/lib/format";
import { sourceLabel } from "@/lib/welcome";
import { DocCrop } from "./DocCrop";
import { Reveal, SourceTag } from "./Section";
import { liabilityLine, useAmendmentCase } from "./useAmendmentCase";

/** The first screen: the number, the sentence it came from, and the way in. */
export function Hero() {
  const { id, detail, source, pages } = useAmendmentCase();
  const inv = detail?.investigation ?? null;
  const headline = liabilityLine(inv?.entries) ?? inv?.liability_delta ?? null;
  const ev = inv?.evidence[0] ?? null;

  return (
    <section className="relative mx-auto w-full max-w-6xl px-6 pb-16 pt-14 md:pt-20">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-40 right-0 h-[36rem] w-[60rem] rounded-full bg-accent/10 blur-[120px]" />
      </div>
      <div className="grid gap-12 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-14">
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

        <Reveal delay={0.2} className="lg:pt-6">
          <div className="space-y-5">
            {ev ? (
              <div className="-rotate-1">
                <DocCrop
                  docId={ev.doc_id}
                  page={ev.page}
                  box={ev.box}
                  pages={pages}
                  quote={ev.quote}
                  crop={{ top: 3, height: 26 }}
                  caption={`found in the mailbox · ${ev.source} · ${ev.date}${ev.page ? ` · page ${ev.page}` : ""}`}
                />
              </div>
            ) : (
              <div className="h-40 rounded-sm border border-line bg-surface" aria-hidden />
            )}
            {detail ? (
              <dl className="num grid grid-cols-3 gap-3 rounded-md border border-line bg-surface p-4 text-sm">
                <div>
                  <dt className="text-2xs font-semibold uppercase tracking-[0.1em] text-ink-faint">Schedule says</dt>
                  <dd className="mt-1 font-medium">{money(detail.expected)}</dd>
                </div>
                <div>
                  <dt className="text-2xs font-semibold uppercase tracking-[0.1em] text-ink-faint">Landlord billed</dt>
                  <dd className="mt-1 font-medium">{money(detail.actual)}</dd>
                </div>
                <div>
                  <dt className="text-2xs font-semibold uppercase tracking-[0.1em] text-ink-faint">Short by</dt>
                  <dd className="mt-1 font-medium text-bad">{signedMoney(detail.delta)}</dd>
                </div>
                {inv?.liability_before != null && inv.liability_after != null ? (
                  <div className="col-span-3 border-t border-line pt-3 text-ink-soft">
                    Lease liability {money(inv.liability_before)} <span aria-hidden>→</span>{" "}
                    <span className="font-medium text-ink">{money(inv.liability_after)}</span>
                    {inv.balanced ? <span className="text-ok"> · four entries, balanced</span> : null}
                  </div>
                ) : null}
                <div className="col-span-3">
                  <SourceTag live={source.kind === "live"}>
                    {id} · {sourceLabel(source)}
                  </SourceTag>
                </div>
              </dl>
            ) : null}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
