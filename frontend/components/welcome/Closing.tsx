"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useProof } from "@/lib/proof";
import { shortDate } from "@/lib/welcome";
import { Reveal, Section, SourceTag } from "./Section";

export function Closing() {
  const proof = useProof();
  const t = proof.data?.tests;
  const ev = proof.data?.eval;
  return (
    <Section className="pb-24">
      <Reveal>
        <div className="rounded-lg border border-accent/25 bg-accent-soft/40 p-10 text-center md:p-14">
          <h2 className="text-headline font-semibold">It is looking for the next one right now.</h2>
          <p className="mx-auto mt-4 max-w-xl leading-relaxed text-ink-soft">
            One case found the amendment. The same run covers every lease, every month, and asks a person the moment it is unsure.
          </p>
          <Link
            href="/login"
            className="mt-8 inline-flex h-12 items-center gap-2 rounded-sm bg-accent px-7 font-medium text-accent-ink shadow-raised transition-all duration-fast ease-out hover:bg-accent-strong hover:shadow-glow active:translate-y-px"
          >
            Open the desk <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        </div>
      </Reveal>

      <Reveal delay={0.1}>
        <div className="mt-10 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-ink-muted" data-testid="proof-footer">
          {t?.backend != null && t.frontend != null ? (
            <span>
              <span className="num text-ink">{t.backend.toLocaleString("en-US")}</span> backend and{" "}
              <span className="num text-ink">{t.frontend.toLocaleString("en-US")}</span> frontend tests, every one offline
              <SourceTag className="ml-2">counted {shortDate(t.counted_at)}</SourceTag>
            </span>
          ) : null}
          {ev ? (
            <span>
              <span className="num text-ink">{ev.held_out_clinics}</span> locations in a held-out company, never seen in development
              <SourceTag className="ml-2">
                measured {shortDate(ev.measured_at)} by {ev.by}
              </SourceTag>
            </span>
          ) : null}
        </div>
      </Reveal>

      <Reveal delay={0.15}>
        <footer className="mt-14 flex flex-col items-center gap-2 text-sm text-ink-faint">
          <a href="https://github.com/sarvesh172000/lease-desk" className="transition-colors hover:text-ink-soft">
            github.com/sarvesh172000/lease-desk
          </a>
          <p>Built at Cal Hacks 13.0 by Sarvesh Waghmare and Jenil.</p>
        </footer>
      </Reveal>
    </Section>
  );
}
