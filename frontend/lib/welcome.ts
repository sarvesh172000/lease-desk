/**
 * Where a figure on the welcome page comes from, and how to say so.
 *
 * A number is "live" only when the data source is the API, the API is
 * reachable and the query that produced it succeeded. Fixtures are never
 * called live, whatever they contain; without the API the page shows what the
 * last real run measured (public/proof.json) and says when.
 */
import type { DataSource } from "./api";
import type { ExceptionSummary } from "./types";

export type FigureSource =
  | { kind: "live"; asOf: string | null }
  | { kind: "measured"; at: string; by: string }
  | { kind: "fixtures" }
  | { kind: "none" };

export function figureSource(opts: {
  source: DataSource;
  reachable: boolean;
  liveOk: boolean;
  asOf?: string | null;
  measured?: { measured_at: string; by: string } | null;
}): FigureSource {
  if (opts.source === "api" && opts.reachable && opts.liveOk) return { kind: "live", asOf: opts.asOf ?? null };
  if (opts.measured) return { kind: "measured", at: opts.measured.measured_at, by: opts.measured.by };
  if (opts.source === "fixtures") return { kind: "fixtures" };
  return { kind: "none" };
}

/** "live · as of 1 Jul 2026" / "measured 25 Oct 2026 by make eval". */
export function sourceLabel(s: FigureSource): string {
  if (s.kind === "live") return s.asOf ? `live · as of ${shortDate(s.asOf)}` : "live";
  if (s.kind === "measured") return `measured ${shortDate(s.at)} by ${s.by}`;
  if (s.kind === "fixtures") return "demo fixtures · offline, not live";
  return "no figures: the API is unreachable and nothing was measured";
}

export function shortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** The July base-rent under-bill the story opens on, whatever id the running system gave it. */
export function amendmentCaseId(exceptions: ExceptionSummary[] | undefined): string | null {
  const hit = exceptions?.find((e) => e.charge_type === "base_rent" && e.delta < 0 && e.period.startsWith("2026-07"));
  return hit?.exception_id ?? null;
}

/** The welcome page's document fan, as beat 1 scrolls through: which page is forward. */
export type FanState = "rest" | "invoice" | "email" | "figure";

/**
 * Scroll progress through beat 1 → the fan's state. Four discrete states, so a
 * page comes forward, holds, and hands over; nothing is interpolated on the way.
 * With reduced motion the story is told in its final frame.
 */
export function fanState(progress: number, reduce = false): FanState {
  if (reduce) return "figure";
  if (progress < 0.12) return "rest";
  if (progress < 0.42) return "invoice";
  if (progress < 0.7) return "email";
  return "figure";
}
