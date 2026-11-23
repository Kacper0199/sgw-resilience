import { phaseAt, phaseInfo } from "./phase";

const PHASES = [
  { phase: "before_landfall" as const, label: "Before landfall", starts_utc: "2024-09-23T12:00:00Z" },
  { phase: "storm" as const, label: "Storm", starts_utc: "2024-09-27T03:10:00Z" },
  { phase: "restoration" as const, label: "Restoration", starts_utc: "2024-09-27T14:00:00Z" },
  { phase: "recovery" as const, label: "Recovery", starts_utc: "2024-10-06T02:00:00Z" },
];
const SCENARIO = { phases: PHASES, final_advisory_utc: "2024-09-27T09:00:00Z" };

describe("phase on the scenario clock", () => {
  it("names the phase at each demo moment", () => {
    expect(phaseAt(PHASES, "2024-09-26T15:05:00Z")).toBe("before_landfall");
    expect(phaseAt(PHASES, "2024-09-27T12:00:00Z")).toBe("storm");
    expect(phaseAt(PHASES, "2024-09-30T12:00:00Z")).toBe("restoration");
    expect(phaseAt(PHASES, "2024-10-06T02:00:00Z")).toBe("recovery");
  });

  it("ends the advisories at the final one and moves headlines after the peak", () => {
    expect(phaseInfo(SCENARIO, "2024-09-27T08:59:00Z")).toMatchObject({
      advisoriesOver: false,
      afterPeak: false,
    });
    expect(phaseInfo(SCENARIO, "2024-09-27T12:00:00Z")).toMatchObject({
      phase: "storm",
      advisoriesOver: true,
      afterPeak: false,
    });
    expect(phaseInfo(SCENARIO, "2024-09-30T12:00:00Z")).toMatchObject({
      phase: "restoration",
      afterPeak: true,
    });
  });

  it("reads as before landfall until the scenario is known", () => {
    expect(phaseInfo(undefined, "2024-09-30T12:00:00Z")).toMatchObject({
      phase: "before_landfall",
      advisoriesOver: false,
    });
    expect(phaseInfo({}, "2024-09-30T12:00:00Z")).toMatchObject({
      phase: "before_landfall",
      advisoriesOver: false,
    });
  });
});
