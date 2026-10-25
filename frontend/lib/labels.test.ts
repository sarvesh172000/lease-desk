import { describe, expect, it } from "vitest";
import { actionLabel, actorKind, attemptLabel, chargeLabel, checkerRuleLabel, landlordName, landlordNamesFromDescription, policyTitle, disputeStatusLabel, clinicLabel, monthLong, placeLabel, rootCauseLabel, TRUST_RANKS } from "./labels";

describe("labels", () => {
  it("names charge types in words", () => {
    expect(chargeLabel("base_rent")).toBe("Base rent");
    expect(chargeLabel("cam_estimate")).toBe("CAM estimate");
    expect(chargeLabel("cam_reconciliation")).toBe("CAM reconciliation");
    expect(chargeLabel("property_tax")).toBe("Property tax");
  });

  it("reads an unknown charge type as words, never as a key", () => {
    expect(chargeLabel("signage_fee")).toBe("Signage fee");
    expect(chargeLabel(null)).toBe("Charge");
    expect(chargeLabel("")).toBe("Charge");
  });

  it("names root causes", () => {
    expect(rootCauseLabel("amendment")).toBe("Executed amendment");
    expect(rootCauseLabel("unexplained")).toBe("Unexplained");
    expect(rootCauseLabel(undefined)).toBe("—");
  });

  it("turns a clinic's location into its place, with the id as the fallback", () => {
    expect(placeLabel("Northbay Coffee — Daly City — Suite 210")).toBe("Daly City, Suite 210");
    expect(placeLabel("Northbay Coffee - San Mateo — Suite 100")).toBe("San Mateo, Suite 100");
    expect(clinicLabel("Northbay Coffee — Daly City — Suite 210", "STORE-01")).toBe("Northbay Coffee Daly City, Suite 210");
    expect(clinicLabel(null, "STORE-01")).toBe("STORE-01");
    expect(placeLabel(null)).toBeNull();
  });

  it("writes periods as a month in full", () => {
    expect(monthLong("2026-07-01")).toBe("July 2026");
    expect(monthLong("2026-01")).toBe("January 2026");
    expect(monthLong(null)).toBe("—");
  });

  it("has the six trust ranks in order, 1 the executed amendment", () => {
    expect(TRUST_RANKS.map((r) => r.rank)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(TRUST_RANKS[0].short).toBe("Executed amendment");
  });

  it("names audit actions in the past tense, in words", () => {
    expect(actionLabel("create")).toBe("Created");
    expect(actionLabel("propose")).toBe("Proposed");
    expect(actionLabel("approve")).toBe("Approved");
    expect(actionLabel("close")).toBe("Closed");
    expect(actionLabel("release_batch")).toBe("Released batch");
    expect(actionLabel("post")).toBe("Posted to ledger");
    expect(actionLabel("some_new_action")).toBe("Some new action");
    expect(actionLabel(null)).toBe("—");
  });

  it("phrases a refused attempt as what was tried", () => {
    expect(attemptLabel("approve")).toBe("tried to approve");
    expect(attemptLabel("post")).toBe("tried to post to the ledger");
  });

  it("tells people, agents and the system apart by id", () => {
    expect(actorKind("PER-RM-BAY")).toBe("person");
    expect(actorKind("agent:checker")).toBe("agent");
    expect(actorKind("system:gateway")).toBe("system");
    expect(actorKind("engine")).toBe("system");
  });

  it("titles a policy by its description, falling back to its name read as words", () => {
    expect(policyTitle({ name: "onboarding:LL-PACIFIC:base_rent:unchanged", description: "Pay base rent as billed when it matches the prior month" })).toBe("Pay base rent as billed when it matches the prior month");
    expect(policyTitle({ name: "onboarding:LL-PACIFIC:base_rent:unchanged", description: null })).toBe("Base rent · unchanged · LL-PACIFIC");
    expect(policyTitle({ name: "onboarding:LL-PACIFIC:cam_estimate:matches_lease", description: "  " })).toBe("CAM estimate · matches lease · LL-PACIFIC");
    expect(policyTitle({ name: "manual:late_fee_waiver", description: undefined })).toBe("Manual · late fee waiver");
  });

  it("names dispute statuses", () => {
    expect(disputeStatusLabel("partially_credited")).toBe("Partly credited");
    expect(disputeStatusLabel("drafted")).toBe("Drafted");
  });

  it("reads landlord names from what the API said, never from a built-in list", () => {
    expect(landlordNamesFromDescription("LL-PACIFIC", "Pay base rent from Pacific Crest Properties LLC as billed when it equals what was paid the month before.")).toEqual({ "LL-PACIFIC": "Pacific Crest Properties LLC" });
    expect(landlordNamesFromDescription("LL-SERRA", "Pay operating expense estimate from Serramonte Retail Partners LLC as billed.")).toEqual({ "LL-SERRA": "Serramonte Retail Partners LLC" });
    expect(landlordNamesFromDescription("LL-X", null)).toEqual({});
    expect(landlordName("LL-PACIFIC", { "LL-PACIFIC": "Pacific Crest Properties LLC" })).toBe("Pacific Crest Properties LLC");
    expect(landlordName("LL-UNKNOWN", {})).toBe("LL-UNKNOWN");
  });

  it("phrases the checker's rules", () => {
    expect(checkerRuleLabel("amount")).toBe("the amount against the schedule");
    expect(checkerRuleLabel("premises")).toBe("the premises the lease demises");
  });
});
