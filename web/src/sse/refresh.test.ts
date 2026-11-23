import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { withinPeriod } from "@/features/map/useMapData";
import { watchScenario } from "./refresh";

describe("scenario switch", () => {
  it("drops the previous storm's map reads only when another scenario arrives", () => {
    const qc = new QueryClient();
    qc.setQueryData(["scenario"], { scenario: "helene", scenario_time: "2024-09-26T15:00:00Z" });
    const stop = watchScenario(qc);
    qc.setQueryData(["hazard", "advisories", "N-1"], { advisory_label: "N-1" });
    qc.setQueryData(["risk", "county", "2024-09-26T15:00:00Z"], []);
    qc.setQueryData(["scenario"], { scenario: "helene", scenario_time: "2024-09-27T09:00:00Z" });
    expect(qc.getQueryData(["hazard", "advisories", "N-1"])).toBeDefined();
    qc.setQueryData(["scenario"], { scenario: "ian", scenario_time: "2022-09-29T15:00:00Z" });
    expect(qc.getQueryData(["hazard", "advisories", "N-1"])).toBeUndefined();
    expect(qc.getQueryData(["risk", "county", "2024-09-26T15:00:00Z"])).toBeUndefined();
    stop();
  });

  it("reads no advisory while the clock is outside the scenario on screen", () => {
    const helene = { start_utc: "2024-09-23T04:00:00Z", end_utc: "2024-10-07T04:00:00Z" };
    expect(withinPeriod(helene, "2024-09-26T15:00:00Z")).toBe(true);
    expect(withinPeriod(helene, "2022-09-29T15:00:00Z")).toBe(false);
    expect(withinPeriod(undefined, "2022-09-29T15:00:00Z")).toBe(true);
  });
});
