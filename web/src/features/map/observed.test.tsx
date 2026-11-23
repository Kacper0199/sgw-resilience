import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { LayerPanel } from "./LayerPanel";
import { DEFAULT_LAYERS, type LayerState, observedOn } from "./layers";
import observedData from "./mock/observed.gen.json";
import {
  arrowLength,
  compass,
  downwind,
  type GaugeObserved,
  gaugeCollection,
  gaugeTip,
  type ObservedHazard,
  observedAt,
  stationTip,
  type WindStation,
  warningCollection,
  warningTip,
} from "./observed";

const snapshots = observedData.observed as ObservedHazard[];

const gauge = (patch: Partial<GaugeObserved>): GaugeObserved => ({
  gauge_id: "02336300",
  nws_id: "AANG1",
  name: "Peachtree Creek at Atlanta",
  state: "GA",
  county: "Fulton",
  lon: -84.4,
  lat: 33.8,
  flood_ft: 17,
  moderate_ft: 18,
  major_ft: 20,
  peak_ft: 23.75,
  peak_utc: "2024-09-27T12:15:00Z",
  category: "major",
  ...patch,
});

const station = (patch: Partial<WindStation>): WindStation => ({
  station: "AGS",
  name: "Augusta",
  lon: -81.96,
  lat: 33.37,
  gust_mph: 82,
  from_deg: 135,
  gust_utc: "2024-09-27T09:37:00Z",
  silent_since_utc: null,
  ...patch,
});

describe("observed layers: time", () => {
  it("live follows the clock, a past stop its issue time, both rounded down to 15 minutes", () => {
    expect(observedAt(true, "2024-09-27T10:44:59Z", "2024-09-27T09:00:00Z")).toBe("2024-09-27T10:30:00Z");
    expect(observedAt(false, "2024-09-27T10:44:59Z", "2024-09-26T09:00:00Z")).toBe("2024-09-26T09:00:00Z");
    expect(observedAt(true, null, "2024-09-26T09:00:00Z")).toBe("2024-09-26T09:00:00Z");
    expect(observedAt(false, null, null)).toBeNull();
  });

  it("the exported snapshots never hold a value later than their time, and peaks only grow", () => {
    for (const s of snapshots) {
      const t = Date.parse(s.as_of);
      expect(s.gauges.every((g) => g.peak_utc === null || Date.parse(g.peak_utc) <= t)).toBe(true);
      expect(s.stations.every((w) => w.gust_utc === null || Date.parse(w.gust_utc) <= t)).toBe(true);
      expect(s.warnings.every((w) => Date.parse(w.issued_utc) <= t && t < Date.parse(w.expires_utc))).toBe(
        true,
      );
    }
    const first = snapshots[0] as ObservedHazard;
    const last = snapshots[snapshots.length - 1] as ObservedHazard;
    const gustAt = (s: ObservedHazard, id: string) => s.stations.find((x) => x.station === id)?.gust_mph ?? 0;
    expect(gustAt(last, "SAV")).toBeGreaterThanOrEqual(gustAt(first, "SAV"));
    expect(first.warnings).toHaveLength(0);
    expect(last.warnings.length).toBeGreaterThan(0);
  });
});

describe("observed layers: symbols and text", () => {
  it("gauges draw flooded ones on top, warnings mark storm-based polygons", () => {
    const fc = gaugeCollection([
      gauge({}),
      gauge({ gauge_id: "b", category: "below" }),
      gauge({ gauge_id: "m", category: "minor" }),
    ]);
    expect(fc.features.map((f) => f.properties.category)).toEqual(["below", "minor", "major"]);
    const w = warningCollection([
      { warning_id: "a", kind: "tornado", office: "CAE", issued_utc: "", expires_utc: "", geometry: {} },
      { warning_id: "b", kind: "hurricane", office: "CAE", issued_utc: "", expires_utc: "", geometry: {} },
    ]);
    expect(w.features.map((f) => f.properties.polygon)).toEqual([true, false]);
  });

  it("tooltips carry name, value against flood stage or direction, and the ET time", () => {
    expect(gaugeTip(gauge({}))).toEqual({
      text: "Peachtree Creek at Atlanta",
      detail: "Major flood, 23.8 ft so far (flood 17.0 ft) at Sep 27 08:15 ET",
    });
    expect(gaugeTip(gauge({ peak_ft: null, peak_utc: null })).detail).toBe("No report yet");
    expect(stationTip(station({})).detail).toBe("Peak gust so far 82 mph from SE at Sep 27 05:37 ET");
    expect(stationTip(station({ silent_since_utc: "2024-09-27T03:45:00Z" })).detail).toContain(
      "\nNo report since Sep 26 23:45 ET",
    );
    expect(stationTip(station({ gust_mph: null, gust_utc: null })).detail).toBe("No gust reported yet");
    expect(
      warningTip({
        kind: "flash_flood",
        issued_utc: "2024-09-27T04:27:00Z",
        expires_utc: "2024-09-27T07:15:00Z",
      }),
    ).toEqual({ text: "Flash flood warning", detail: "Sep 27 00:27 ET to Sep 27 03:15 ET" });
  });

  it("arrows grow with the gust and point downwind", () => {
    expect(arrowLength(10)).toBe(22);
    expect(arrowLength(55)).toBe(33);
    expect(arrowLength(120)).toBe(44);
    expect(arrowLength(120, 4)).toBe(22);
    expect(arrowLength(120, 9)).toBe(44);
    expect(downwind(135)).toBe(315);
    expect(compass(135)).toBe("SE");
    expect(compass(359)).toBe("N");
    expect(compass(-45)).toBe("NW");
  });
});

function Panel({ zoomed = true }: { zoomed?: boolean }) {
  const [layers, setLayers] = useState<LayerState>(DEFAULT_LAYERS);
  const [open, setOpen] = useState(true);
  return (
    <>
      <LayerPanel
        layers={layers}
        onChange={setLayers}
        open={open}
        onOpenChange={setOpen}
        hasSelection={false}
        hasSteps={false}
        valuesNeedZoom={!zoomed}
        onClearSelection={() => {}}
      />
      <output data-testid="state">{JSON.stringify(layers)}</output>
    </>
  );
}

describe("layer panel", () => {
  const state = () => JSON.parse(screen.getByTestId("state").textContent ?? "{}") as LayerState;

  it("observed layers start off and switch on one by one", () => {
    render(<Panel />);
    expect(observedOn(state())).toBe(false);
    const observed = screen.getByRole("region", { name: "Observed" });
    fireEvent.click(within(observed).getByRole("switch", { name: "River gauges" }));
    expect(state().gauges).toBe(true);
  });

  it("offers airport gust values only while airport wind is on", () => {
    render(<Panel />);
    expect(screen.queryByRole("switch", { name: "Airport gust values" })).toBeNull();
    fireEvent.click(screen.getByRole("switch", { name: "Airport wind" }));
    const gust = screen.getByRole("switch", { name: "Airport gust values" });
    expect(gust).toBeChecked();
    fireEvent.click(gust);
    expect(state().windValues).toBe(false);
    fireEvent.click(screen.getByRole("switch", { name: "Airport wind" }));
    expect(screen.queryByRole("switch", { name: "Airport gust values" })).toBeNull();
  });

  it("numbers follow the colouring: values belong to the layer on, and go with it", () => {
    render(<Panel />);
    expect(screen.getByRole("switch", { name: "Outage risk values" })).toBeChecked();
    fireEvent.click(screen.getByRole("switch", { name: "Peak gust" }));
    expect(state()).toMatchObject({ county: "wind", values: "gust" });
    expect(screen.queryByRole("switch", { name: "Outage risk values" })).toBeNull();
    fireEvent.click(screen.getByRole("switch", { name: "Peak gust" }));
    expect(state()).toMatchObject({ county: "none", values: "none" });
  });

  it("says why numbers are missing while the map is zoomed out", () => {
    const { rerender } = render(<Panel />);
    expect(screen.queryByText("Zoom in to see them")).toBeNull();
    rerender(<Panel zoomed={false} />);
    expect(screen.getByText("Zoom in to see them")).toBeInTheDocument();
  });

  it("collapses to one button", () => {
    render(<Panel />);
    fireEvent.click(screen.getByRole("button", { name: "Collapse layers" }));
    expect(screen.queryByRole("switch", { name: "Outage risk" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open layers" })).toHaveAttribute("aria-expanded", "false");
  });
});
