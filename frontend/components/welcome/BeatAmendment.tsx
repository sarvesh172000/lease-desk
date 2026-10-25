"use client";

import { CountUp } from "@/components/data/CountUp";
import { JournalEntryTable } from "@/components/JournalEntryTable";
import { money, signedMoney } from "@/lib/format";
import { TRUST_RANKS } from "@/lib/labels";
import { sourceLabel } from "@/lib/welcome";
import { DocCrop } from "./DocCrop";
import { IntoTheDesk, Reveal, Section, SourceTag } from "./Section";
import { useAmendmentCase } from "./useAmendmentCase";

/**
 * Beat 1: the hidden amendment, told top to bottom. The invoice line boxes
 * itself, then the clause, then the liability counts up to its remeasured
 * figure, then the entries. Every figure is the exception's own.
 */
export function BeatAmendment() {
  const { id, detail, source, pages } = useAmendmentCase();
  const inv = detail?.investigation ?? null;
  const ev = inv?.evidence[0] ?? null;
  const rank = ev ? TRUST_RANKS[ev.trust_rank - 1] : null;

  return (
    <Section id="story" className="min-h-[90vh] py-20 md:py-28">
      <div className="grid gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
        <div className="lg:sticky lg:top-24 lg:self-start">
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
            {id ? <IntoTheDesk href={`/exceptions/${id}`}>Open it on the money screen</IntoTheDesk> : null}
          </Reveal>
        </div>

        <div className="space-y-6">
          {detail?.invoice_line ? (
            <Reveal>
              <DocCrop
                docId={detail.invoice_line.doc_id}
                page={detail.invoice_line.page}
                box={detail.invoice_line.box}
                pages={pages}
                quote={detail.invoice_line.description}
                crop={{ top: 36, height: 14 }}
                tone="bad"
                caption={`the invoice line the checker located · ${detail.invoice_line.description}`}
              />
            </Reveal>
          ) : null}

          {ev ? (
            <Reveal delay={0.1}>
              <DocCrop
                docId={ev.doc_id}
                page={ev.page}
                box={ev.box}
                pages={pages}
                quote={ev.quote}
                crop={{ top: 3, height: 26 }}
                caption={`the sentence it relied on · ${ev.source} · ${ev.date}`}
              />
            </Reveal>
          ) : null}

          {inv?.liability_before != null && inv.liability_after != null ? (
            <Reveal delay={0.15}>
              <div className="rounded-md border border-line bg-surface p-5">
                <div className="eyebrow">Lease liability, remeasured</div>
                <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
                  <span className="num text-sm text-ink-muted">{money(inv.liability_before)}</span>
                  <span aria-hidden className="text-ink-faint">→</span>
                  <span className="text-3xl font-semibold tracking-tight md:text-4xl">
                    <CountUp from={inv.liability_before} value={inv.liability_after} prefix="$" duration={1600} />
                  </span>
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
            <Reveal delay={0.2}>
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
        </div>
      </div>
    </Section>
  );
}
