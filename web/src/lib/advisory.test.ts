import { advisoryTime, plainAdvisory } from "./advisory";

describe("plainAdvisory", () => {
  it("names the two advisories previous and latest", () => {
    expect(plainAdvisory("Advisory N+1 moved the deadline.")).toBe("The latest advisory moved the deadline.");
    expect(plainAdvisory("Crews mobilise at advisory N.")).toBe("Crews mobilise at the previous advisory.");
    expect(plainAdvisory("What changed from N to N+1")).toBe("What changed from previous to latest advisory");
  });
  it("leaves text without advisory labels alone", () => {
    expect(plainAdvisory("Generator at PS-17 N of 4")).toBe("Generator at PS-17 N of 4");
  });
  it("formats an advisory by its issue time", () => {
    expect(advisoryTime("2024-09-26T15:00:00Z")).toBe("Sep 26 11:00 ET");
  });
});
