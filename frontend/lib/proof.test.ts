import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { Proof } from "./proof";

// the file the welcome page shows offline: copied from real runs by scripts/proof.mjs
const proof = JSON.parse(readFileSync(join(process.cwd(), "public", "proof.json"), "utf8")) as Proof;

describe("public/proof.json", () => {
  it("carries a measured-at date and what measured it", () => {
    expect(proof.eval.by).toBe("make eval");
    expect(Number.isNaN(Date.parse(proof.eval.measured_at))).toBe(false);
    expect(proof.eval.passed).toBe(true);
  });

  it("reports the checker's run as counts, with caught and missed summing to planted", () => {
    const e = proof.eval;
    for (const k of ["charges_checked", "held", "planted", "caught", "missed", "false_holds", "dollars_flagged", "citations_correct", "sources_refused"] as const) {
      expect(typeof e[k], k).toBe("number");
    }
    expect(e.caught + e.missed).toBe(e.planted);
    expect(e.dollars_flagged).toBe(e.dollars_expected);
  });

  it("records the refused actions from prove-limits, each with who, what and by whom", () => {
    expect(proof.limits).not.toBeNull();
    const l = proof.limits!;
    expect(l.by).toBe("make prove-limits");
    expect(l.refusals.length).toBeGreaterThan(0);
    for (const r of l.refusals) {
      expect(r.seq).toBeGreaterThan(0);
      expect(r.actor_id).toBeTruthy();
      expect(["can()", "Postgres"]).toContain(r.refused_by);
    }
    expect(l.refusals.some((r) => r.refused_by === "Postgres" && r.action === "post")).toBe(true);
    expect(l.chain_verified).toBe(true);
  });

  it("counts the tests rather than naming a number", () => {
    expect(proof.tests.backend).toBeGreaterThan(0);
    expect(proof.tests.frontend).toBeGreaterThan(0);
    expect(Number.isNaN(Date.parse(proof.tests.counted_at))).toBe(false);
  });
});
