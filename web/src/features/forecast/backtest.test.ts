import { describe, expect, it } from "vitest";
import { parseBacktest } from "./backtest";
import v1 from "./mock/outage_loso.json";
import v2 from "./mock/outage_loso_v2.json";
import type { K17Report } from "./types";

const four = parseBacktest(v1 as K17Report);
const twentyFour = parseBacktest(v2 as K17Report);

describe("backtest, 4-storm report", () => {
  it("reads one row per storm in report order, with both baselines beside the forecast", () => {
    expect(four.storms.map((s) => s.name)).toEqual(["Michael", "Ian", "Debby", "Helene"]);
    const helene = four.storms[3];
    expect(helene?.county).toMatchObject({ model: 14187.1, wind: 14862.6 });
    expect(helene?.total).toMatchObject({ model: 0.6736, wind: 0.7548, curve: 0.5519 });
    expect(helene?.worstMiss).toMatchObject({ model: 184698, wind: 196390 });
    expect(four.windName).toBe("Wind rule");
    expect(four.curveName).toBe("Standard damage curve");
    expect(four.countyCurve).toBe(false);
    expect(four.totalCurve).toBe(true);
  });

  it("flags the storms whose 80% range missed its claim", () => {
    expect(four.coverageMisses).toEqual([{ storm: "Helene", value: 0.2927, nominal: 0.8 }]);
  });

  it("keeps the summary row with the report's own unit text", () => {
    expect(four.summary).toHaveLength(1);
    expect(four.summary[0]).toMatchObject({
      label: "Storms where the total beat the wind rule",
      value: 3,
      passed: true,
    });
    expect(four.summary[0]?.unit).toContain("strictly lower");
  });
});

describe("backtest, 24-storm report", () => {
  it("reads 24 storms and a fitted curve in both groups", () => {
    expect(twentyFour.storms).toHaveLength(24);
    expect(twentyFour.storms.map((s) => s.name)).toContain("Colin 2016");
    expect(twentyFour.countyCurve).toBe(true);
    expect(twentyFour.totalCurve).toBe(true);
    expect(twentyFour.curveName).toBe("Damage curve fitted to past storms");
  });

  it("shows where it falls short from the report's own pass flags", () => {
    const under = twentyFour.summary.find((s) => s.metric === "storms_s2_under_predicted_total");
    expect(under).toMatchObject({ value: 18, passed: false });
    expect(under?.unit).toContain("forecast total below observed");
    const share = twentyFour.summary.find((s) => s.metric === "s2_share_of_observed_outages_forecast");
    expect(share?.value).toBeCloseTo(0.4313, 4);
    expect(share?.passed).toBe(false);
  });

  it("does not turn sensitivity or subset rows into storms", () => {
    expect(twentyFour.storms.map((s) => s.key)).not.toContain("large_storms");
    expect(twentyFour.storms.map((s) => s.key)).not.toContain("sensitivity_2018_on_refit");
  });
});

it("a report with no rows gives an empty table, not an error", () => {
  const empty = parseBacktest({ ...(v1 as K17Report), metrics: [] });
  expect(empty.storms).toEqual([]);
  expect(empty.summary).toEqual([]);
});
