import { describe, expect, it } from "vitest";
import { plainReview } from "./format";

describe("review draft text", () => {
  it("reads with plain names and ET times, without case codes or the method note", () => {
    const text =
      "The audit chain verified before the review, checked through record 89. Missed: Set the restoration order of FDR-AIK-2219 and FDR-AIK-2207 (D3, decision case DC-D3-AIK-RESTORE-ORDER), due by 27 Sep 13:05Z, not decided. Missed: Reroute fuel truck FTK-WREN-3 to PS-38 (D3, decision case DC-D3-PS38-FUEL-REROUTE), due by 28 Sep 00:49Z, not decided. Missed: Send portable generator MGEN-HALBERD-500 to PS-52 (D3, decision case DC-D3-PS52-MOBILE-GENERATOR), due by 28 Sep 14:15Z, not decided. Break-glass uses: 1. Template text: the language model was not used for this brief; every value is computed.";
    const out = plainReview(text, "2024-09-30T12:00:00Z");
    expect(out).toContain("The audit log verified.");
    expect(out).toContain("restoration order of feeder 2219 and feeder 2207, due by Sep 27, 09:05 ET");
    expect(out).toContain("Reroute fuel truck Wren 3 to PS-38, due by Sep 27, 20:49 ET");
    expect(out).toContain("Send portable generator Halberd to PS-52");
    expect(out).toContain("Emergency approvals: 1.");
    expect(out).not.toMatch(/DC-|Template text|\dZ\b|FDR-|MGEN-|FTK-/);
  });
});
