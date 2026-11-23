import { describe, expect, it } from "vitest";
import type { Reference } from "../../agent-panel/types";
import { chipText, referenceHref, splitReferences } from "./references";

const none = () => null;
const ref = (kind: Reference["kind"], id: string, label = id): Reference => ({ kind, id, label });

describe("reference chips for the AI-platform kinds", () => {
  it.each([
    [ref("photo", "LADI-0042"), "/crews?photo=LADI-0042"],
    [ref("gauge", "02197000"), "/map?gauge=02197000"],
    [ref("crew", "CRW-AIK-04"), "/crews?crew=CRW-AIK-04"],
    [ref("yard", "STG-AIK-SANDHILL-YARD"), "/crews?yard=STG-AIK-SANDHILL-YARD"],
    [ref("zone", "WZ-PS17-CEDARFALL"), "/water?zone=WZ-PS17-CEDARFALL"],
    [ref("check", "DC-RDY-GEN-PS52-LOADTEST"), "/readiness?check=DC-RDY-GEN-PS52-LOADTEST"],
    [ref("surge", "45003@2024-09-27T04:00:00Z"), "/map?county=45003&at=2024-09-27T04%3A00%3A00Z"],
    [ref("surge", "45003"), "/map?county=45003"],
  ])("opens %j at %s", (reference, href) => {
    expect(referenceHref(reference, none)).toBe(href);
  });

  it("finds a surge by its label and the others by their id", () => {
    const refs = [
      ref("surge", "45003@2024-09-27T04:00:00Z", "Aiken surge, 27 Sep 00:00"),
      ref("photo", "LADI-0042", "Flooded road"),
    ];
    const parts = splitReferences("Aiken surge, 27 Sep 00:00 matches photo LADI-0042.", refs);
    expect(parts.filter((p) => p.kind === "ref").map((p) => p.text)).toEqual([
      "Aiken surge, 27 Sep 00:00",
      "LADI-0042",
    ]);
  });

  it("a decision with no proposal yet has no page to open", () => {
    expect(referenceHref(ref("decision", "DC-D3-PS17-PRESSURE"), none)).toBeNull();
    expect(referenceHref(ref("decision", "DC-D3-PS17-POWER"), () => "PRP-1")).toBe("/?d=PRP-1");
  });

  it("a possessive stays inside the chip", () => {
    const parts = splitReferences("PS-17's generator and PS-17’s tank.", [ref("asset", "PS-17")]);
    expect(parts.filter((p) => p.kind === "ref").map((p) => p.text)).toEqual(["PS-17's"]);
    expect(parts[1]).toEqual({ kind: "text", text: " generator and PS-17’s tank.", at: 7 });
  });

  it("reads the plain name, never the id, and keeps a pump station as written", () => {
    const decision = ref("decision", "DC-D3-PS17-POWER", "Hook up the portable generator at PS-17");
    expect(chipText(decision, "DC-D3-PS17-POWER")).toBe("Hook up the portable generator at PS-17");
    expect(chipText(ref("asset", "PS-17", "Cedarfall pump station"), "PS-17's")).toBe("PS-17's");
    expect(
      chipText(ref("asset", "HSP-AIK-TALLOWBRANCH", "Tallowbranch hospital"), "HSP-AIK-TALLOWBRANCH"),
    ).toBe("Tallowbranch hospital");
  });

  it("takes an id and the title that follows it as one mention", () => {
    const decision = ref("decision", "DC-D3-HSP-WATER", "Secure water supply to Tallowbranch hospital");
    const parts = splitReferences(
      "DC-D3-HSP-WATER Secure water supply to Tallowbranch hospital: decide by 06:29 ET",
      [decision],
    );
    expect(parts.map((p) => p.kind)).toEqual(["ref", "text"]);
    expect(parts[1]).toMatchObject({ text: ": decide by 06:29 ET" });
  });
});
