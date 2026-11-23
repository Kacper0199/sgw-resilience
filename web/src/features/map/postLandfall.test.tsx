import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { forecastIsHistory } from "@/lib/phase";
import { countyReadout, formatOut, valueText } from "./format";
import type { FeatureCollection } from "./geo";
import counties from "./geo/counties.geo.json";
import { countyCollection } from "./layerData";
import { DEFAULT_LAYERS, defaultLayers, OBSERVED_LAYERS, stormOn } from "./layers";
import { MapLegend } from "./MapLegend";
import feed from "./mock/county-outages.gen.json";
import { type CountyOutagesNow, outagesByCounty } from "./outagesNow";

const fc = counties as unknown as FeatureCollection;
const lifted = feed.reports.find((r) => r.as_of === "2024-09-30T12:00:00Z") as CountyOutagesNow;

describe("the map once the forecast is history", () => {
  it("opens on customers out now with the storm layers off", () => {
    expect(defaultLayers(true)).toBe(OBSERVED_LAYERS);
    expect(OBSERVED_LAYERS).toMatchObject({ county: "outages", values: "out" });
    expect(stormOn(OBSERVED_LAYERS)).toBe(false);
    expect(defaultLayers(false)).toBe(DEFAULT_LAYERS);
    expect(defaultLayers(true, true).values).toBe("none");
    expect(defaultLayers(false, true).county).toBe("risk");
  });

  it("treats the forecast as history from the final advisory or the outage peak on", () => {
    expect(forecastIsHistory({ afterPeak: false, advisoriesOver: false })).toBe(false);
    expect(forecastIsHistory({ afterPeak: false, advisoriesOver: true })).toBe(true);
    expect(forecastIsHistory({ afterPeak: true, advisoriesOver: false })).toBe(true);
  });

  it("takes customers out per county from the outage feed hour the Briefing reads", () => {
    const out = outagesByCounty(lifted);
    expect(out.get("45045")).toBe(4505);
    expect(out.has("45003")).toBe(false);
    expect([...out.values()].reduce((a, b) => a + b, 0)).toBe(lifted.customers_out_now);
    expect(lifted.customers_out_now).toBe(168_598);
  });

  it("marks a county the feed has no report for as no data, never as no one out", () => {
    const values = new Map(
      [...outagesByCounty(lifted)].map(([fips, out]) => [fips, { fips, name: "", out }]),
    );
    const shown = countyCollection(fc, values, "out", true);
    const aiken = shown.features.find((f) => String(f.properties.fips) === "45003");
    const greenville = shown.features.find((f) => String(f.properties.fips) === "45045");
    expect(aiken?.properties).toMatchObject({ nodata: true });
    expect(aiken?.properties.v).toBeUndefined();
    expect(greenville?.properties).toMatchObject({ v: 4505 });
    expect(greenville?.properties.nodata).toBeUndefined();
    expect(countyCollection(fc, values, "risk", true).features.some((f) => f.properties.nodata)).toBe(false);
    expect(countyReadout("Aiken", values.get("45003"), "outages", true)).toBe("Aiken: No data");
    expect(countyReadout("Aiken", values.get("45003"), "risk", true)).toBe("Aiken");
    expect(countyReadout("Clinch, GA", { fips: "13065", name: "Clinch", risk: 830_000 }, "risk")).toBe(
      "Clinch, GA: outage risk 83%",
    );
  });

  it("explains no data in the legend instead of no one out", () => {
    render(
      <MapLegend
        layers={OBSERVED_LAYERS}
        domain={{ min: 3, max: 4505 }}
        hasSteps={false}
        forecastIsHistory
        unplacedNote={null}
        track={{ past: false, future: false, now: false }}
        surgeRange={null}
        open
        onOpenChange={() => {}}
      />,
    );
    expect(screen.getByText("No data")).toBeInTheDocument();
    expect(screen.queryByText(/no one out/i)).toBeNull();
  });

  it("writes counts short enough for a county label", () => {
    expect([7, 842, 1500, 12_400, 202_381, 1_300_000].map(formatOut)).toEqual([
      "7",
      "842",
      "1.5k",
      "12k",
      "202k",
      "1.3M",
    ]);
    expect(valueText({ fips: "45001", name: "", out: 1500 }, "outages")).toBe("1,500 out now");
  });
});
