"use client";

import { motion, useReducedMotion } from "framer-motion";
import { CountUp } from "@/components/data/CountUp";
import { money } from "@/lib/format";
import { useApiHealth, useDataSource, useSignedIn, useSummaryWhen } from "@/lib/hooks";
import { useProof } from "@/lib/proof";
import { figureSource, shortDate, sourceLabel } from "@/lib/welcome";
import { cn } from "@/lib/utils";
import { IntoTheDesk, Reveal, Section, SourceTag } from "./Section";

/**
 * Beat 2: the January run. The counts are what `make eval` measured on the
 * last real run (public/proof.json), and say so. When the API is reachable the
 * desk's own month figures sit beside them, marked live.
 */
export function BeatJanuary() {
  const reduce = useReducedMotion();
  const proof = useProof();
  const source = useDataSource();
  const health = useApiHealth();
  const signedIn = useSignedIn();
  const summary = useSummaryWhen(source === "api" && signedIn);
  const ev = proof.data?.eval;
  const live = figureSource({ source, reachable: health.reachable, liveOk: summary.isSuccess, asOf: summary.data?.as_of });

  return (
    <Section id="january" className="min-h-[85vh] py-20 md:py-28">
      <div className="grid grid-cols-1 gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
        <div className="lg:sticky lg:top-24 lg:self-start">
          <Reveal>
            <div className="eyebrow mb-3 text-warn">2 · January</div>
            <h2 className="text-headline font-semibold">
              {ev ? (
                <>
                  <span className="num">{ev.charges_checked}</span> charges checked.{" "}
                  <span className="num text-bad">{ev.held}</span> held, for{" "}
                  <span className="num">{money(ev.dollars_flagged)}</span>.
                </>
              ) : (
                "A month of landlord bills, checked line by line."
              )}
            </h2>
            <p className="mt-5 leading-relaxed text-ink-soft">
              The checker reads every charge of the month against the schedule its lease implies, and holds only what it can
              prove wrong, citing the clause. Among January&rsquo;s holds: a rent invoice billed twice, and rent for a suite the
              store does not lease. The rest goes to the AP clerk to pay.
            </p>
            {ev ? (
              <p className="mt-4 text-sm text-ink-muted">
                Scored against an answer key the checker has never read: <span className="num text-ink">{ev.caught}/{ev.planted}</span> planted
                errors caught, <span className="num text-ink">{ev.false_holds}</span> false holds,{" "}
                <span className="num text-ink">{ev.citations_correct}/{ev.held}</span> holds cite the clause that proves them.
              </p>
            ) : null}
            <div className="mt-4">
              {ev ? <SourceTag>measured {shortDate(ev.measured_at)} by {ev.by}</SourceTag> : proof.isError ? <SourceTag>no measurement on record</SourceTag> : null}
            </div>
            <IntoTheDesk href="/month">Open the Month run</IntoTheDesk>
          </Reveal>
        </div>

        <div className="space-y-6">
          <Reveal>
            <div className="rounded-md border border-line bg-surface p-5">
              <div className="flex items-baseline justify-between">
                <span className="eyebrow">The month&rsquo;s charges</span>
                {ev ? <span className="font-mono text-2xs text-ink-muted">{ev.held} of {ev.charges_checked} held</span> : null}
              </div>
              {/* one tile per charge checked, the held ones in red: a count, not a list — which five is on the Month run */}
              <ol className="mt-4 grid grid-cols-6 gap-2 sm:grid-cols-12" aria-label="Charges checked" data-testid="charge-tiles">
                {Array.from({ length: ev?.charges_checked ?? 0 }, (_, i) => {
                  const held = ev ? i < ev.held : false;
                  return (
                    <motion.li
                      key={i}
                      initial={reduce ? false : { opacity: 0, y: 8 }}
                      whileInView={{ opacity: 1, y: 0 }}
                      viewport={{ once: true }}
                      transition={{ duration: 0.3, delay: i * 0.06 }}
                      className={cn(
                        "flex aspect-square items-center justify-center rounded-sm border font-mono text-2xs",
                        held ? "border-bad-line bg-bad-soft text-bad" : "border-ok-line bg-ok-soft text-ok",
                      )}
                      aria-label={held ? "held" : "pays"}
                    >
                      {held ? "hold" : "pay"}
                    </motion.li>
                  );
                })}
              </ol>
              {ev ? (
                <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-line pt-4 sm:grid-cols-4">
                  <Figure label="Checked" value={<CountUp value={ev.charges_checked} decimals={0} />} />
                  <Figure label="Held" value={<CountUp value={ev.held} decimals={0} />} tone="bad" />
                  <Figure label="Held, in dollars" value={<CountUp value={ev.dollars_flagged} prefix="$" />} />
                  <Figure label="False holds" value={<CountUp value={ev.false_holds} decimals={0} />} tone="ok" />
                </dl>
              ) : null}
            </div>
          </Reveal>

          {live.kind === "live" && summary.data ? (
            <Reveal delay={0.1}>
              <div className="rounded-md border border-ok-line/60 bg-surface p-5" data-testid="live-summary">
                <div className="flex items-baseline justify-between">
                  <span className="eyebrow">The desk right now</span>
                  <SourceTag live>{sourceLabel(live)}</SourceTag>
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <Figure label="Active leases" value={<span className="num">{summary.data.active_leases}</span>} />
                  <Figure label="Open exceptions" value={<span className="num">{summary.data.open_exceptions}</span>} />
                  <Figure label="Held" value={<span className="num">{money(summary.data.held_total)}</span>} tone="bad" />
                  <Figure label="Lease liability" value={<span className="num">{money(summary.data.portfolio_liability)}</span>} />
                </dl>
              </div>
            </Reveal>
          ) : null}
        </div>
      </div>
    </Section>
  );
}

function Figure({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "bad" | "ok" }) {
  return (
    <div>
      <dt className="text-2xs font-semibold uppercase tracking-[0.1em] text-ink-faint">{label}</dt>
      <dd className={cn("mt-1 text-2xl font-semibold tracking-tight", tone === "bad" && "text-bad", tone === "ok" && "text-ok")}>{value}</dd>
    </div>
  );
}
