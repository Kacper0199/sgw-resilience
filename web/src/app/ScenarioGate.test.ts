import { describe, expect, it } from "vitest";
import { notModelledPages } from "./ScenarioGate";

describe("not modelled for a scripted exercise", () => {
  it("names exactly the pages without a model for the exercise", () => {
    expect(notModelledPages()).toBe("Forecast and Water");
  });
});
