import { describe, expect, it } from "vitest";
import { SEVERITY_VECTORS } from "@/contracts/vectors.gen";
import { freshCards, MOCK_NOW } from "./fixtures";

describe("mock queue severity", () => {
  it("comes from the server vectors generated for the same proposals, clock and time", () => {
    expect(SEVERITY_VECTORS.now).toBe(MOCK_NOW);
    for (const card of freshCards()) {
      const vector = SEVERITY_VECTORS.cases.find((c) => c.id === card.proposal_id);
      expect(vector).toBeDefined();
      expect(vector?.effective_decide_by_utc).toBe(card.effective_decide_by_utc);
      expect(vector?.on_critical_path).toBe(card.on_critical_path);
      expect(card.severity).toBe(vector?.severity);
    }
  });
});
