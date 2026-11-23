import { describe, expect, it } from "vitest";
import { type Canonical, canonicalJson, sha256Hex } from "./canonical";
import { GOLDEN_STREAMS, handlers } from "./msw.gen";
import { POLICIES } from "./policies.gen";
import { ACTION_HASH_VECTORS } from "./vectors.gen";
import { APPROVAL_FUNCTION, TIER } from "./vocab.gen";
import { parseSseId, WIRE_EVENTS } from "./wire.gen";

describe("K8 canonical hash parity with Python", () => {
  for (const v of ACTION_HASH_VECTORS.vectors) {
    it(v.name, async () => {
      const canonical = canonicalJson(v.input as unknown as Canonical);
      expect(canonical).toBe(v.canonical);
      expect(await sha256Hex(canonical)).toBe(v.sha256);
    });
  }
  it("rejects floats", () => {
    expect(() => canonicalJson({ p: 0.5 })).toThrow();
  });
});

describe("generated contracts", () => {
  it("vocab and policies", () => {
    expect(TIER).toEqual(["T0", "T1", "T2", "T3", "T4"]);
    expect(APPROVAL_FUNCTION).toContain("water_operations");
    expect(POLICIES.policy_equity_weight.value).toBe(0);
    expect(POLICIES.policy_equity_weight.chip).toBe("Assumed SGW policy");
  });
  it("wire ids and golden streams", () => {
    expect(parseSseId("run:abc.1.7")).toEqual({
      stream: "run:abc",
      epoch: 1,
      seq: 7,
    });
    expect(() => parseSseId("nope")).toThrow();
    expect(WIRE_EVENTS).toContain("approval_required");
    expect(GOLDEN_STREAMS.ops_ps17_hinge).toContain("event: ledger");
    expect(handlers.length).toBeGreaterThan(40);
  });
});
