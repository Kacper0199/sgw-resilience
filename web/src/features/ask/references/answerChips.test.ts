import { describe, expect, it } from "vitest";
import type { Reference } from "../../agent-panel/types";
import { chipText, splitAnswer, splitReferences } from "./references";

const ref = (kind: Reference["kind"], id: string, label = id): Reference => ({ kind, id, label });
const chips = (parts: ReturnType<typeof splitReferences>) =>
  parts.filter((p) => p.kind === "ref").map((p) => p.text);

describe("one chip per reference per answer", () => {
  it("names the feeders of a decision title in words, as the Decisions page does", () => {
    const order = ref(
      "decision",
      "DC-D3-EX-31",
      "Set the restoration order of FDR-AIK-2219 and FDR-AIK-2207",
    );
    expect(chipText(order, "DC-D3-EX-31")).toBe("Set the restoration order of feeder 2219 and feeder 2207");
    const parts = splitReferences(
      "Set the restoration order of FDR-AIK-2219 and FDR-AIK-2207 (DC-D3-EX-31) is open.",
      [order],
    );
    const chip = parts.find((p) => p.kind === "ref");
    expect(parts[0]?.kind).toBe("ref");
    expect(chip && chipText(order, chip.text)).toBe(
      "Set the restoration order of feeder 2219 and feeder 2207",
    );
    const restore = ref(
      "decision",
      "DC-D3-EX-29",
      "Restore FDR-CLB-0817 before the last Columbia County laterals",
    );
    expect(chipText(restore, "DC-D3-EX-29")).toBe(
      "Restore feeder 0817 before the last Columbia County laterals",
    );
  });

  it("chips a clause at its first mention only, across every sentence of the answer", () => {
    const dom = ref("clause", "DOM 14.206", "6.0 PROCEDURE");
    const parts = splitAnswer(["Revise per DOM 14.206 ", ". Approvals per DOM 14.206 ", "."], [dom]);
    expect(parts.map(chips)).toEqual([["DOM 14.206"], [], []]);
  });

  it("leaves a clause as plain text when the answer shows its source badge", () => {
    const dom = ref("clause", "DOM 14.206", "6.0 PROCEDURE");
    expect(splitAnswer(["Revise per DOM 14.206 "], [dom], [dom]).map(chips)).toEqual([[]]);
  });

  it("names a generator in brackets after its station without repeating the station", () => {
    const gen = ref("asset", "GEN-PS38-COPPERLEAF", "Onsite generator at PS-38");
    const parts = splitReferences("PS-38 (GEN-PS38-COPPERLEAF) and PS-52 have one.", [gen]);
    const chip = parts.find((p) => p.kind === "ref");
    expect(chip && chipText(gen, chip.text, "PS-38 (")).toBe("onsite generator");
    expect(chipText(gen, "GEN-PS38-COPPERLEAF", "Only ")).toBe("Onsite generator at PS-38");
  });

  it("takes a decision and an aside that restates its title as one mention", () => {
    const power = ref("decision", "DC-D3-PS17-POWER", "Hook up the portable generator at PS-17");
    const parts = splitReferences(
      "DC-D3-PS17-POWER, hooking up the portable generator, has a decide-by of Sep 26.",
      [power],
    );
    expect(parts.map((p) => p.kind)).toEqual(["ref", "text"]);
    expect(parts[1]).toMatchObject({ text: " has a decide-by of Sep 26." });
    const other = splitReferences("DC-D3-PS17-POWER, decided on time, needs fuel.", [power]);
    expect(other[1]).toMatchObject({ text: ", decided on time, needs fuel." });
  });

  it("takes a decision title followed by its id in brackets as one mention", () => {
    const power = ref("decision", "DC-D3-PS17-POWER", "Hook up the portable generator at PS-17");
    const parts = splitReferences(
      "For PS-17, Hook up the portable generator at PS-17 (DC-D3-PS17-POWER) should be decided.",
      [power],
    );
    expect(parts.map((p) => p.kind)).toEqual(["text", "ref", "text"]);
    expect(parts[0]).toMatchObject({ text: "For PS-17, " });
    expect(parts[2]).toMatchObject({ text: " should be decided." });
  });

  it("drops the id when the brackets after a decision title go on, and keeps the rest in brackets", () => {
    const fuel = ref("decision", "DC-D3-PS17-FUEL", "Dispatch the fuel truck to PS-17");
    const parts = splitReferences(
      "It follows Dispatch the fuel truck to PS-17 (DC-D3-PS17-FUEL, Sep 26, 21:59 ET).",
      [fuel],
    );
    expect(parts.map((p) => [p.kind, p.text])).toEqual([
      ["text", "It follows "],
      ["ref", "Dispatch the fuel truck to PS-17"],
      ["text", " ("],
      ["text", "Sep 26, 21:59 ET)."],
    ]);
  });

  it("chips a decision title that names a place before the place itself", () => {
    const power = ref("decision", "DC-D3-PS17-POWER", "Hook up the portable generator at PS-17");
    const station = ref("asset", "PS-17", "PS-17");
    const parts = splitReferences("Hook up the portable generator at PS-17 (DC-D3-PS17-POWER) can wait.", [
      station,
      power,
    ]);
    expect(chips(parts)).toEqual(["Hook up the portable generator at PS-17 (DC-D3-PS17-POWER)"]);
  });
});
