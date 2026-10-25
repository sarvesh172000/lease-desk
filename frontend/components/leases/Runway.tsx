"use client";

import { StatusBadge } from "@/components/StatusBadge";
import { Tooltip } from "@/components/ui/Tooltip";
import { day, money } from "@/lib/format";
import { regionOfLocation, REGION_ORDER, type RegionId } from "@/lib/geo";
import { useLeaseVersionsMany } from "@/lib/hooks";
import { obligationLabel, placeLabel, regionLabel } from "@/lib/labels";
import type { LeaseSummary, LeaseVersion, Obligation } from "@/lib/types";
import { cn } from "@/lib/utils";
import { motion, useReducedMotion } from "framer-motion";
import Link from "next/link";
import { useMemo } from "react";

const DAY = 86_400_000;
const LABEL_W = 300; // wide enough for "Serramonte Hand Therapy, Suite 115" at 14px

export interface RunwayProps {
  leases: LeaseSummary[];
  /** The business clock the bars are measured from (summary.as_of). */
  today: string;
  obligations: Obligation[];
  /** The clinic's region when the API knows it (from the queue); the city table otherwise. */
  regionOf?: (lease: LeaseSummary) => string | null | undefined;
}

const STATUS_BAR: Record<string, string> = {
  balanced: "bg-ok",
  exception: "bg-bad",
  pending_review: "bg-warn",
  escalated: "bg-esc",
};

const OBLIGATION_TICK: Record<string, string> = {
  renewal_notice: "bg-warn",
  cam_audit_window: "bg-esc",
  deposit_return: "bg-accent",
  expiration: "bg-ink-soft",
};

/** The newest version's expiration, when a lease has more than one version. */
export function newerEnd(versions: LeaseVersion[] | undefined): { from: number; oldEnd: string | null; newEnd: string | null } | null {
  if (!versions || versions.length < 2) return null;
  const sorted = [...versions].sort((a, b) => a.version - b.version);
  const exp = (v: LeaseVersion) => {
    const t = v.terms.find((x) => x.field === "expiration")?.value;
    return typeof t === "string" ? t : null;
  };
  const last = sorted[sorted.length - 1];
  return { from: last.version, oldEnd: exp(sorted[0]), newEnd: exp(last) };
}

/**
 * The ghost: v1's end against the newest version's, as a span on the axis. It
 * stays after the newer version is confirmed (the lease's end is then the new
 * one), because what changed is the point. Null when the ends agree or are unknown.
 */
export function ghostSpan(
  ghost: { from: number; oldEnd: string | null; newEnd: string | null } | null,
  leaseEnd: string,
): { from: number; oldEnd: string; newEnd: string; start: number; stop: number } | null {
  if (!ghost?.newEnd) return null;
  const oldEnd = ghost.oldEnd ?? leaseEnd;
  if (oldEnd === ghost.newEnd) return null;
  const a = Date.parse(`${oldEnd}T00:00:00Z`);
  const b = Date.parse(`${ghost.newEnd}T00:00:00Z`);
  return { from: ghost.from, oldEnd, newEnd: ghost.newEnd, start: Math.min(a, b), stop: Math.max(a, b) };
}

/** Bar thickness from monthly rent: 10px for the smallest, 24px for the largest. */
export function thickness(rent: number, min: number, max: number): number {
  if (max <= min) return 16;
  return 10 + ((rent - min) / (max - min)) * 14;
}

/**
 * Every lease as a bar on one time axis, from the business clock to its end,
 * grouped by region. Colour is status, thickness is monthly rent, the label
 * is the liability; obligations are ticks on the bar; a newer version shows
 * the old end against the new as a ghost. Hover for the lease, click to open.
 */
export function Runway({ leases, today, obligations, regionOf }: RunwayProps) {
  const reduce = useReducedMotion();
  const versions = useLeaseVersionsMany(leases.map((l) => l.lease_id));
  const versionsById = useMemo(() => new Map(leases.map((l, i) => [l.lease_id, versions[i]?.data])), [leases, versions]);

  const t0 = Date.parse(today.length === 10 ? `${today}T00:00:00Z` : today);
  const ends = leases.map((l) => Date.parse(`${l.end}T00:00:00Z`));
  const ghostEnds = leases.map((l) => {
    const g = newerEnd(versionsById.get(l.lease_id));
    return g?.newEnd ? Date.parse(`${g.newEnd}T00:00:00Z`) : 0;
  });
  // the axis: six months before today to the furthest end (ghosts included), rounded up to a year
  const axisStart = t0 - 182 * DAY;
  const furthest = Math.max(t0 + 365 * DAY, ...ends, ...ghostEnds);
  const endYear = new Date(furthest).getUTCFullYear() + 1;
  const axisEnd = Date.UTC(endYear, 0, 1);
  const x = (ms: number) => `${Math.max(0, Math.min(100, ((ms - axisStart) / (axisEnd - axisStart)) * 100))}%`;
  const years: number[] = [];
  for (let y = new Date(axisStart).getUTCFullYear() + 1; y <= endYear; y++) years.push(y);

  const rents = leases.map((l) => l.monthly_rent);
  const minRent = Math.min(...rents);
  const maxRent = Math.max(...rents);
  const obsByLease = useMemo(() => {
    const m = new Map<string, Obligation[]>();
    for (const o of obligations) m.set(o.lease_id, [...(m.get(o.lease_id) ?? []), o]);
    return m;
  }, [obligations]);

  const groups = useMemo(() => {
    const g = new Map<string, LeaseSummary[]>();
    for (const l of leases) {
      const r = (regionOf?.(l) ?? regionOfLocation(l.location)) as RegionId | string;
      g.set(r, [...(g.get(r) ?? []), l]);
    }
    const order = [...REGION_ORDER.filter((r) => g.has(r)), ...Array.from(g.keys()).filter((r) => !(REGION_ORDER as string[]).includes(r))];
    return order.map((r) => ({ region: r, leases: (g.get(r) ?? []).sort((a, b) => Date.parse(a.end) - Date.parse(b.end)) }));
  }, [leases, regionOf]);

  return (
    <div className="relative overflow-hidden rounded-md border border-line bg-surface" data-testid="runway">
      {/* axis */}
      <div className="relative grid h-12 border-b border-line" style={{ gridTemplateColumns: `${LABEL_W}px minmax(0,1fr)` }}>
        <span className="eyebrow self-center pl-4">Lease</span>
        <div className="relative">
          {years.map((y) => (
            <span key={y} className="num absolute top-1.5 -translate-x-1/2 font-mono text-2xs text-ink-muted" style={{ left: x(Date.UTC(y, 0, 1)) }}>
              {y}
            </span>
          ))}
          {/* the business clock, on its own line so it never collides with a year */}
          <span className="num absolute top-6 ml-1.5 whitespace-nowrap font-mono text-2xs font-semibold text-accent" style={{ left: x(t0) }} data-testid="today-line">
            today · {day(today)}
          </span>
        </div>
      </div>
      <div className="relative">
        {/* year lines and the business clock, behind the rows */}
        <div className="pointer-events-none absolute inset-y-0 right-0" style={{ left: LABEL_W }}>
          {years.map((y) => (
            <span key={y} aria-hidden className="absolute inset-y-0 w-px bg-line/70" style={{ left: x(Date.UTC(y, 0, 1)) }} />
          ))}
          <span aria-hidden className="absolute inset-y-0 w-0 border-l-2 border-dashed border-accent" style={{ left: x(t0) }} />
        </div>

        {groups.map((g) => (
          <section key={g.region} aria-label={regionLabel(g.region)}>
            <div className="grid items-center border-b border-line/70 bg-sunken/40" style={{ gridTemplateColumns: `${LABEL_W}px minmax(0,1fr)` }}>
              <h2 className="eyebrow py-1.5 pl-4">
                {regionLabel(g.region)} · {g.leases.length}
              </h2>
              <span />
            </div>
            <ol>
              {g.leases.map((l, i) => {
                const end = Date.parse(`${l.end}T00:00:00Z`);
                const h = thickness(l.monthly_rent, minRent, maxRent);
                const ghost = newerEnd(versionsById.get(l.lease_id));
                const span = ghostSpan(ghost, l.end);
                const obs = obsByLease.get(l.lease_id) ?? [];
                return (
                  <li
                    key={l.lease_id}
                    className="group relative grid cursor-pointer items-center border-b border-line/70 transition-colors duration-fast hover:bg-sunken/60 focus-within:bg-sunken/60"
                    style={{ gridTemplateColumns: `${LABEL_W}px minmax(0,1fr)`, height: 58 }}
                    data-testid="runway-row"
                    data-lease={l.lease_id}
                  >
                    <div className="min-w-0 pl-4 pr-3">
                      <div className="flex items-center gap-2 truncate text-sm font-medium">
                        <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-full", STATUS_BAR[l.status] ?? "bg-ink-faint")} />
                        {/* a stretched link: the whole row opens the lease, by mouse or keyboard */}
                        <Link
                          href={`/leases/${encodeURIComponent(l.lease_id)}`}
                          className="truncate outline-none after:absolute after:inset-0 after:z-[1] after:content-[''] focus-visible:underline"
                        >
                          {placeLabel(l.location) ?? l.location}
                        </Link>
                      </div>
                      <div className="num truncate font-mono text-2xs text-ink-muted">
                        {l.lease_id} · {money(l.monthly_rent)} / mo
                      </div>
                    </div>
                    <div className="relative h-full">
                      {/* the term: from the clock to the end */}
                      <motion.div
                        className={cn("absolute rounded-xs", STATUS_BAR[l.status] ?? "bg-ink-faint", "opacity-85 group-focus-within:opacity-100 group-hover:opacity-100")}
                        style={{ left: x(t0), top: `calc(50% - ${h / 2}px)`, height: h, width: `calc(${x(end)} - ${x(t0)})`, transformOrigin: "left" }}
                        initial={reduce ? false : { scaleX: 0 }}
                        animate={{ scaleX: 1 }}
                        transition={{ duration: 0.5, delay: reduce ? 0 : 0.05 * i, ease: [0.2, 0.8, 0.2, 1] }}
                        data-testid="runway-bar"
                      />
                      {(() => {
                        const inside = (end - t0) / (axisEnd - axisStart) > 0.34 && h >= 14;
                        return (
                          <span
                            className={cn("num pointer-events-none absolute whitespace-nowrap font-mono text-2xs font-semibold", inside ? "text-accent-ink" : "text-ink-soft")}
                            style={{ left: inside ? `calc(${x(t0)} + 8px)` : `calc(${x(end)} + 8px)`, top: "calc(50% - 7px)" }}
                          >
                            {money(l.liability)} · ends {day(l.end)}
                          </span>
                        );
                      })()}
                      {/* a newer version: the old end against the new */}
                      {span ? (
                        <Tooltip label={`v${span.from}: ends ${day(span.newEnd)} instead of ${day(span.oldEnd)}`} side="top">
                          <button
                            type="button"
                            className="absolute z-10 cursor-default rounded-xs border border-dashed border-accent bg-accent/10"
                            style={{ left: x(span.start), width: `calc(${x(span.stop)} - ${x(span.start)})`, top: `calc(50% - ${h / 2}px)`, height: h }}
                            data-testid="runway-ghost"
                            aria-label={`Version ${span.from} ends ${day(span.newEnd)} instead of ${day(span.oldEnd)}`}
                          />
                        </Tooltip>
                      ) : null}
                      {/* obligations as ticks */}
                      {obs.map((o) => (
                        <Tooltip key={o.id} label={`${obligationLabel(o.kind)} · ${day(o.due_date)} · ${o.days_left} days · ${o.action}`} side="top">
                          <button
                            type="button"
                            aria-label={`${obligationLabel(o.kind)} due ${day(o.due_date)}`}
                            className={cn("absolute z-10 w-0.5 cursor-default rounded-full p-0", OBLIGATION_TICK[o.kind] ?? "bg-ink-soft")}
                            style={{ left: x(Date.parse(`${o.due_date}T00:00:00Z`)), top: `calc(50% - ${h / 2 + 6}px)`, height: h + 12 }}
                            data-testid="runway-tick"
                          />
                        </Tooltip>
                      ))}
                    </div>
                    {/* shown on hover or keyboard focus, by CSS: no handlers on the row */}
                    <HoverCard lease={l} obligations={obs} ghost={ghost} />
                  </li>
                );
              })}
            </ol>
          </section>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-4 px-4 py-2 text-2xs text-ink-muted">
        <span>Bar: from today to the end of the term · thickness is monthly rent · label is the liability</span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="h-3 w-0.5 bg-warn" /> renewal notice
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="h-3 w-0.5 bg-esc" /> CAM audit window
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="h-2.5 w-4 rounded-xs border border-dashed border-accent" /> newer version&apos;s end
        </span>
      </div>
    </div>
  );
}

function HoverCard({ lease, obligations, ghost }: { lease: LeaseSummary; obligations: Obligation[]; ghost: ReturnType<typeof newerEnd> }) {
  const next = [...obligations].sort((a, b) => a.days_left - b.days_left)[0];
  return (
    <div className="pointer-events-none absolute right-4 top-1/2 z-20 hidden w-72 -translate-y-1/2 rounded-sm border border-line bg-surface p-3 shadow-float group-focus-within:block group-hover:block" data-testid="lease-card">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-semibold">{placeLabel(lease.location) ?? lease.location}</span>
        <StatusBadge status={lease.status} />
      </div>
      <div className="font-mono text-2xs text-ink-muted">
        {lease.lease_id} · {lease.lessor}
      </div>
      <dl className="num mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs">
        <dt className="text-ink-muted">Monthly rent</dt>
        <dd className="text-right font-semibold">{money(lease.monthly_rent)}</dd>
        <dt className="text-ink-muted">Liability</dt>
        <dd className="text-right font-semibold">{money(lease.liability)}</dd>
        <dt className="text-ink-muted">Ends</dt>
        <dd className="text-right">
          {day(lease.end)}
          {ghost?.newEnd && ghost.newEnd !== lease.end ? <span className="text-accent"> → {day(ghost.newEnd)} (v{ghost.from})</span> : null}
          {ghost?.oldEnd && ghost.newEnd === lease.end && ghost.oldEnd !== lease.end ? (
            <span className="text-ink-muted"> (v1 ended {day(ghost.oldEnd)})</span>
          ) : null}
        </dd>
        {next ? (
          <>
            <dt className="text-ink-muted">Next</dt>
            <dd className="text-right">
              {obligationLabel(next.kind)} · {day(next.due_date)}
            </dd>
          </>
        ) : null}
      </dl>
    </div>
  );
}
