import { describe, expect, it } from "vitest";
import { afterCrack, applyFilters, BROKEN_CHAIN_FIXTURE, chainState, filterOptions, NO_FILTERS } from "./chain";
import type { AuditResponse } from "./types";

const ev = BROKEN_CHAIN_FIXTURE.events;
const verified: AuditResponse = { chain_verified: true, events: ev };

describe("chain state", () => {
  it("takes the verdict from the API: verified, no crack", () => {
    const s = chainState(verified, null);
    expect(s).toMatchObject({ verified: true, brokenSeq: null, crackSeq: null, count: 5 });
  });

  it("shows the API's broken sequence as the crack", () => {
    const s = chainState(BROKEN_CHAIN_FIXTURE, null);
    expect(s).toMatchObject({ verified: false, brokenSeq: 4, crackSeq: 4, simulatedSeq: null });
    expect(afterCrack(3, s.crackSeq)).toBe(false);
    expect(afterCrack(4, s.crackSeq)).toBe(true);
    expect(afterCrack(5, s.crackSeq)).toBe(true);
  });

  it("a simulation cracks a verified chain on screen but never changes the verdict", () => {
    const s = chainState(verified, 3);
    expect(s.verified).toBe(true);
    expect(s.brokenSeq).toBeNull();
    expect(s.simulatedSeq).toBe(3);
    expect(s.crackSeq).toBe(3);
  });

  it("a real break wins over a simulation", () => {
    const s = chainState(BROKEN_CHAIN_FIXTURE, 2);
    expect(s.crackSeq).toBe(4);
    expect(s.simulatedSeq).toBeNull();
  });

  it("falls back to broken_at when broken_seq is absent", () => {
    const s = chainState({ chain_verified: false, broken_at: 2, events: ev }, null);
    expect(s.brokenSeq).toBe(2);
  });
});

describe("audit filters", () => {
  it("keeps refused attempts only", () => {
    expect(applyFilters(ev, { ...NO_FILTERS, outcome: "refused" }).map((e) => e.seq)).toEqual([3]);
    expect(applyFilters(ev, { ...NO_FILTERS, outcome: "allowed" })).toHaveLength(4);
  });

  it("filters by an actor id or by a kind of actor", () => {
    expect(applyFilters(ev, { ...NO_FILTERS, actor: "PER-CTRL" }).map((e) => e.seq)).toEqual([4]);
    expect(applyFilters(ev, { ...NO_FILTERS, actor: "agent" }).map((e) => e.seq)).toEqual([1, 2, 3]);
    expect(applyFilters(ev, { ...NO_FILTERS, actor: "system" }).map((e) => e.seq)).toEqual([5]);
  });

  it("filters by action and subject", () => {
    expect(applyFilters(ev, { ...NO_FILTERS, action: "approve" }).map((e) => e.seq)).toEqual([3, 4]);
    expect(applyFilters(ev, { ...NO_FILTERS, subject: "journal_entry" }).map((e) => e.seq)).toEqual([5]);
  });

  it("finds a row by sequence number or by hash prefix, prev_hash included", () => {
    expect(applyFilters(ev, { ...NO_FILTERS, query: "#4" }).map((e) => e.seq)).toEqual([4]);
    expect(applyFilters(ev, { ...NO_FILTERS, query: "4" }).map((e) => e.seq)).toEqual([2, 3, 4]); // seq 4, plus hashes starting 4a8b…
    expect(applyFilters(ev, { ...NO_FILTERS, query: "C71E" }).map((e) => e.seq)).toEqual([3]);
    expect(applyFilters(ev, { ...NO_FILTERS, query: "deadbeef" }).map((e) => e.seq)).toEqual([4]);
    expect(applyFilters(ev, { ...NO_FILTERS, query: "zzz" })).toEqual([]);
  });

  it("lists the actors, actions and subjects on record", () => {
    const o = filterOptions(ev);
    expect(o.actors.map((a) => a.id)).toContain("system:gateway");
    expect(o.actions).toEqual(["approve", "create", "post", "propose"]);
    expect(o.subjects).toEqual(["journal_entry", "work_item"]);
  });
});
