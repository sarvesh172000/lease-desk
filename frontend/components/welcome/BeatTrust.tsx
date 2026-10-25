"use client";

import { motion, useReducedMotion } from "framer-motion";
import { ShieldCheck, ShieldOff } from "lucide-react";
import { useApiHealth, useAudit, useDataSource } from "@/lib/hooks";
import { actorKind, attemptLabel } from "@/lib/labels";
import { useProof, type ProofRefusal } from "@/lib/proof";
import type { AuditEvent } from "@/lib/types";
import { figureSource, shortDate, sourceLabel } from "@/lib/welcome";
import { cn } from "@/lib/utils";
import { IntoTheDesk, Reveal, Section, SourceTag } from "./Section";

const BLOCKS = 40;

type Block = { seq: number; refused: boolean; who?: string; action?: string };

/** The last stretch of the chain, from the live audit trail or from the recorded prove-limits run. */
function blocksFromEvents(events: AuditEvent[]): Block[] {
  return events.slice(-BLOCKS).map((e) => ({ seq: e.seq, refused: !e.allowed, who: e.actor_id, action: e.action }));
}
function blocksFromRefusals(refusals: ProofRefusal[]): Block[] {
  const last = Math.max(...refusals.map((r) => r.seq));
  const byRef = new Map(refusals.map((r) => [r.seq, r]));
  return Array.from({ length: BLOCKS }, (_, i) => {
    const seq = last - BLOCKS + 1 + i;
    const r = byRef.get(seq);
    return { seq, refused: !!r, who: r?.actor_id, action: r?.action };
  });
}

function who(actorId: string): string {
  const kind = actorKind(actorId);
  if (kind === "agent") return `The ${actorId.replace(/^agent:/, "")} agent`;
  if (kind === "system") return "The system";
  return "A regional manager";
}

export function BeatTrust() {
  const reduce = useReducedMotion();
  const source = useDataSource();
  const health = useApiHealth();
  const audit = useAudit();
  const proof = useProof();
  const live = figureSource({ source, reachable: health.reachable, liveOk: audit.isSuccess, asOf: audit.data?.events.at(-1)?.at ?? null });
  const limits = proof.data?.limits ?? null;

  const fromLive = live.kind === "live" && audit.data;
  const blocks: Block[] = fromLive ? blocksFromEvents(audit.data.events) : limits ? blocksFromRefusals(limits.refusals) : [];
  const refusals: ProofRefusal[] = fromLive
    ? audit.data.events.filter((e) => !e.allowed).slice(-3).map((e) => ({ seq: e.seq, actor_id: e.actor_id, action: e.action, refused_by: /database refused/i.test(e.reason ?? "") ? "Postgres" : "can()", reason: e.reason ?? "" }))
    : limits?.refusals ?? [];
  const verified: boolean | null = fromLive ? audit.data.chain_verified : limits ? limits.chain_verified : null;
  const eventCount = fromLive ? audit.data.events.length : null;
  const tag = fromLive ? sourceLabel(live) : limits ? `measured ${shortDate(limits.measured_at)} by ${limits.by}` : null;

  return (
    <Section id="trust" className="min-h-[85vh] py-20 md:py-28">
      <div className="grid gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
        <div className="lg:sticky lg:top-24 lg:self-start">
          <Reveal>
            <div className="eyebrow mb-3 text-bad">3 · Trust</div>
            <h2 className="text-headline font-semibold">The agent tried to post. Postgres said no.</h2>
            <p className="mt-5 leading-relaxed text-ink-soft">
              The agent process holds a database role that cannot write the ledger: not a policy, a grant. A manager who answered
              the agent&rsquo;s question may not approve the answer. Every attempt, allowed or refused, is hashed to the one before
              it, and the chain verifies on request.
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              {tag ? <SourceTag live={!!fromLive}>{tag}</SourceTag> : null}
              {verified != null ? (
                <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-2xs", verified ? "border-ok-line bg-ok-soft text-ok" : "border-bad-line bg-bad-soft text-bad")} data-testid="chain-verdict">
                  {verified ? <ShieldCheck aria-hidden className="h-3 w-3" /> : <ShieldOff aria-hidden className="h-3 w-3" />}
                  {verified ? "chain verified" : "chain broken"}
                  {eventCount != null ? ` · ${eventCount} events` : ""}
                </span>
              ) : null}
            </div>
            <IntoTheDesk href="/audit">Open the audit trail</IntoTheDesk>
          </Reveal>
        </div>

        <div className="space-y-6">
          <Reveal>
            <div className="rounded-md border border-line bg-surface p-5">
              <div className="flex items-baseline justify-between">
                <span className="eyebrow">The chain, newest on the right</span>
                <span className="font-mono text-2xs text-ink-muted">{blocks.length ? `seq ${blocks[0].seq}–${blocks.at(-1)!.seq}` : "—"}</span>
              </div>
              <ol className="mt-4 flex items-end gap-[3px]" aria-label="Audit chain" data-testid="chain-blocks">
                {blocks.map((b, i) => (
                  <motion.li
                    key={b.seq}
                    initial={reduce ? false : { opacity: 0, scaleY: 0.2 }}
                    whileInView={{ opacity: 1, scaleY: 1 }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.25, delay: i * 0.03 }}
                    title={b.refused ? `seq ${b.seq} · ${b.who} ${attemptLabel(b.action)} · refused` : `seq ${b.seq}`}
                    className={cn(
                      "h-10 min-w-0 flex-1 origin-bottom rounded-[2px]",
                      b.refused ? "h-14 bg-bad shadow-[0_0_0_1px_rgb(var(--bad)/0.4),0_0_18px_-2px_rgb(var(--bad)/0.6)]" : "bg-accent/55",
                    )}
                    data-refused={b.refused || undefined}
                  />
                ))}
              </ol>
              {!blocks.length ? <p className="mt-3 text-sm text-ink-muted">No chain to draw: the API is unreachable and no prove-limits run is on record.</p> : null}
            </div>
          </Reveal>

          {refusals.length ? (
            <Reveal delay={0.1}>
              <ol className="divide-y divide-line rounded-md border border-line bg-surface" data-testid="refusals">
                {refusals.map((r) => (
                  <li key={r.seq} className="flex items-start gap-4 p-4">
                    <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-sm border border-bad-line bg-bad-soft text-bad">
                      <ShieldOff aria-hidden className="h-3.5 w-3.5" />
                    </span>
                    <div className="min-w-0">
                      <div className="text-sm">
                        <span className="font-medium">{who(r.actor_id)}</span> {attemptLabel(r.action)} ·{" "}
                        <span className="font-semibold text-bad">refused by {r.refused_by}</span>
                      </div>
                      <div className="mt-0.5 font-mono text-2xs text-ink-muted">
                        seq {r.seq} · {r.reason}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            </Reveal>
          ) : null}
        </div>
      </div>
    </Section>
  );
}
