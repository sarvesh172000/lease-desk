/**
 * public/proof.json — what the real runs reported, copied by scripts/proof.mjs.
 *
 * The welcome page shows live figures when the API answers; otherwise it shows
 * these, each stamped with when and by what it was measured. It never shows a
 * figure that was typed into the page.
 */
import { useQuery } from "@tanstack/react-query";

export interface ProofEval {
  measured_at: string;
  by: string;
  seed: number;
  passed: boolean;
  charges_checked: number;
  held: number;
  planted: number;
  caught: number;
  missed: number;
  false_holds: number;
  dollars_flagged: number;
  dollars_expected: number;
  citations_correct: number;
  sources_searched: number;
  sources_refused: number;
  confidence: number;
  entries_balance: boolean;
  never_posts_alone: boolean;
  held_out_clinics: number;
}

export interface ProofRefusal {
  seq: number;
  actor_id: string;
  action: string;
  refused_by: string;
  reason: string;
}

export interface ProofLimits {
  measured_at: string;
  by: string;
  refusals: ProofRefusal[];
  chain_verified: boolean;
}

export interface Proof {
  eval: ProofEval;
  limits: ProofLimits | null;
  tests: { counted_at: string; backend: number | null; frontend: number | null };
}

export async function getProof(): Promise<Proof> {
  const r = await fetch("/proof.json", { cache: "no-store" });
  if (!r.ok) throw new Error(`proof.json: ${r.status}`);
  return (await r.json()) as Proof;
}

export function useProof() {
  return useQuery({ queryKey: ["proof"], queryFn: getProof, staleTime: Infinity, retry: false });
}
