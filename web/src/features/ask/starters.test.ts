import { describe, expect, it } from "vitest";
import { STARTERS_BY_PHASE, startersFor } from "./starters";

describe("starters per storm phase", () => {
  it("offers the advisory question only before landfall", () => {
    const advisory = "What does the latest advisory mean for PS-17's deadline?";
    expect(startersFor("before_landfall")).toContain(advisory);
    for (const phase of ["storm", "restoration", "recovery"]) {
      expect(startersFor(phase)).not.toContain(advisory);
      expect(startersFor(phase)).toEqual(STARTERS_BY_PHASE.after_landfall);
    }
  });

  it("offers four starters in every phase", () => {
    expect(STARTERS_BY_PHASE.before_landfall).toHaveLength(4);
    expect(STARTERS_BY_PHASE.after_landfall).toHaveLength(4);
    expect(startersFor(null)).toEqual(STARTERS_BY_PHASE.before_landfall);
  });
});
