import { money } from "@/lib/format";
import { chargeLabel, checkerRuleLabel, landlordName, policyActionLabel } from "@/lib/labels";
import type { PolicyRule, PolicySummary } from "@/lib/types";

/** The scope in words: who the rule applies to. */
export function scopeLabel(s: PolicySummary["scope"]): string {
  const parts = [s.landlord_id && `landlord ${s.landlord_id}`, s.lease_id, s.clinic_id].filter(Boolean);
  return parts.length ? parts.join(" · ") : s.entity_id ? `all of ${s.entity_id}` : "everywhere";
}

/** The rule in plain words, from its stored conditions; `names` maps landlord ids to names when known. */
export function ruleInWords(r: PolicyRule, names: Record<string, string> = {}): string[] {
  const w = r.when;
  const lines: string[] = [];
  const charges = w.charge_types.length ? w.charge_types.map(chargeLabel).join(", ") : "any charge";
  const who = [r.scope.landlord_id && `from ${landlordName(r.scope.landlord_id, names)}`, r.scope.lease_id && `on ${r.scope.lease_id}`, r.scope.clinic_id && `at ${r.scope.clinic_id}`].filter(Boolean).join(" ");
  lines.push(`When a ${charges.toLowerCase()} charge ${who}`.trim());
  if (w.same_as_prior_paid === true) lines.push("equals what was paid the month before");
  if (w.same_as_prior_paid === false) lines.push("differs from what was paid the month before");
  if (w.matches_lease === true) lines.push("matches what the lease supports");
  if (w.matches_lease === false) lines.push("does not match what the lease supports");
  if (w.min_amount || w.max_amount) lines.push(`is ${w.min_amount ? `at least ${money(Number(w.min_amount))}` : ""}${w.min_amount && w.max_amount ? " and " : ""}${w.max_amount ? `at most ${money(Number(w.max_amount))}` : ""}`);
  if (w.min_variance || w.max_variance) lines.push(`varies ${w.min_variance ? `by at least ${money(Number(w.min_variance))}` : ""}${w.min_variance && w.max_variance ? " and " : ""}${w.max_variance ? `by at most ${money(Number(w.max_variance))}` : ""}`);
  if (w.description_contains) lines.push(`and its description contains “${w.description_contains}”`);
  if (w.checker_rules.length) lines.push(`and the checker's finding was about ${w.checker_rules.map(checkerRuleLabel).join(" or ")},`);
  lines.push(`then ${policyActionLabel(r.then.action).toLowerCase()}${r.then.account ? ` to ${r.then.account}` : ""}${r.then.trust_source ? `, trusting ${r.then.trust_source}` : ""}.`);
  return lines;
}
