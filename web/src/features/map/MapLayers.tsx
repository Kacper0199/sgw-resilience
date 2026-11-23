import { Layer, Source } from "@vis.gl/react-maplibre";
import type { FeatureCollection } from "./geo";
import type { Domain } from "./layerData";
import type { LayerState } from "./layers";
import type { StormGeometry } from "./storm";
import type { Basemap } from "./useBasemap";
import type { useThemeColors } from "./useThemeColors";

type Colors = ReturnType<typeof useThemeColors>;
const vis = (on: boolean) => ({ visibility: on ? ("visible" as const) : ("none" as const) });
const data = (fc: FeatureCollection) => fc as never;

export const COUNTY_HIT = "county-hit";
export const GAUGE_HIT = "gauges";
export const WARNING_HIT = "warnings-fill";
export const FIX_HIT = "track-fixes-hit";
export const ASSET_LAYERS = ["electric", "water-assets"];
export const WATER_ICON = "asset-water";
export const NO_DATA_PATTERN = "county-nodata";
const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

export function BaseLayers({ basemap, c }: { basemap: Basemap | undefined; c: Colors }) {
  return (
    <>
      <Layer id="water" type="background" paint={{ "background-color": c.water }} />
      <Source id="land" type="geojson" data={data(basemap?.land ?? EMPTY)}>
        <Layer id="land-other" type="fill" paint={{ "fill-color": c.landOther }} />
      </Source>
      <Source id="states" type="geojson" data={data(basemap?.states ?? EMPTY)}>
        <Layer id="states-fill" type="fill" paint={{ "fill-color": c.landUs }} />
        <Layer id="states-line" type="line" paint={{ "line-color": c.state, "line-width": 0.9 }} />
      </Source>
      <Source id="lakes" type="geojson" data={data(basemap?.lakes ?? EMPTY)}>
        <Layer id="lakes-fill" type="fill" paint={{ "fill-color": c.water }} />
      </Source>
      <Source id="land-coast" type="geojson" data={data(basemap?.land ?? EMPTY)}>
        <Layer id="coast" type="line" paint={{ "line-color": c.coast, "line-width": 1 }} />
      </Source>
    </>
  );
}

interface RegionProps {
  c: Colors;
  counties: FeatureCollection;
  footprint: FeatureCollection;
  colour: LayerState["county"];
  domain: Domain | null;
  fillColor: unknown;
  hoverFips: string | null;
  focusFips: string | null;
  /** The hatch image for counties without an outage report is registered. */
  noDataPattern: boolean;
}

export function RegionLayers({
  c,
  counties,
  footprint,
  colour,
  domain,
  fillColor,
  hoverFips,
  focusFips,
  noDataPattern,
}: RegionProps) {
  const showFill = colour !== "none" && domain !== null;
  const hover = ["==", ["get", "fips"], hoverFips ?? ""] as never;
  return (
    <>
      <Source id="counties" type="geojson" data={data(counties)}>
        <Layer id="county-base" type="fill" paint={{ "fill-color": c.region }} />
        <Layer
          id="county-fill"
          type="fill"
          filter={["has", "v"]}
          layout={vis(showFill)}
          paint={{ "fill-color": fillColor as never, "fill-opacity": 0.78 }}
        />
        <Layer
          id="county-nodata"
          type="fill"
          filter={["has", "nodata"]}
          layout={vis(showFill && colour === "outages" && noDataPattern)}
          paint={{ "fill-pattern": NO_DATA_PATTERN, "fill-opacity": 0.55 }}
        />
        <Layer id={COUNTY_HIT} type="fill" paint={{ "fill-color": c.land, "fill-opacity": 0 }} />
        <Layer
          id="county-lines"
          type="line"
          paint={{ "line-color": c.line, "line-width": 0.8, "line-opacity": 0.9 }}
        />
        <Layer
          id="county-hover-fill"
          type="fill"
          filter={hover}
          paint={{ "fill-color": c.ink, "fill-opacity": 0.1 }}
        />
        <Layer
          id="county-focus-line"
          type="line"
          filter={["==", ["get", "fips"], focusFips ?? ""] as never}
          paint={{ "line-color": c.accent, "line-width": 3 }}
        />
        <Layer
          id="county-hover-line"
          type="line"
          filter={hover}
          paint={{ "line-color": c.ink, "line-width": 2.2 }}
        />
      </Source>
      <Source id="footprint" type="geojson" data={data(footprint)}>
        <Layer id="region-line" type="line" paint={{ "line-color": c.regionLine, "line-width": 1.8 }} />
      </Source>
    </>
  );
}

export function StormLayers({ storm, layers, c }: { storm: StormGeometry; layers: LayerState; c: Colors }) {
  return (
    <>
      <Source id="cone" type="geojson" data={data(storm.cone)}>
        <Layer
          id="cone-fill"
          type="fill"
          layout={vis(layers.cone)}
          paint={{ "fill-color": c.accent, "fill-opacity": 0.11 }}
        />
        <Layer
          id="cone-line"
          type="line"
          layout={{ ...vis(layers.cone), "line-join": "round" }}
          paint={{ "line-color": c.accent, "line-width": 1.4 }}
        />
      </Source>
      <Source id="track-past" type="geojson" data={data(storm.past)}>
        <Layer
          id="track-past-casing"
          type="line"
          layout={{ ...vis(layers.track), "line-join": "round" }}
          paint={{ "line-color": c.surface, "line-width": 5.4, "line-opacity": 0.85 }}
        />
        <Layer
          id="track-past"
          type="line"
          layout={{ ...vis(layers.track), "line-join": "round" }}
          paint={{ "line-color": c.ink, "line-width": 2.6 }}
        />
      </Source>
      <Source id="track-future" type="geojson" data={data(storm.future)}>
        <Layer
          id="track-future"
          type="line"
          layout={{ ...vis(layers.track), "line-join": "round" }}
          paint={{ "line-color": c.ink, "line-width": 1.8, "line-dasharray": [2.5, 2] }}
        />
      </Source>
      <Source id="track-fixes" type="geojson" data={data(storm.fixes)}>
        <Layer
          id="track-fixes"
          type="circle"
          layout={vis(layers.track)}
          paint={{
            "circle-radius": 3.6,
            "circle-color": c.surface,
            "circle-stroke-color": c.ink,
            "circle-stroke-width": 1.5,
          }}
        />
        <Layer
          id={FIX_HIT}
          type="circle"
          layout={vis(layers.track)}
          paint={{ "circle-radius": 11, "circle-color": c.surface, "circle-opacity": 0 }}
        />
      </Source>
      <Source id="track-now" type="geojson" data={data(storm.now)}>
        <Layer
          id="track-now-halo"
          type="circle"
          layout={vis(layers.track)}
          paint={{
            "circle-radius": 12,
            "circle-color": c.accent,
            "circle-opacity": 0.2,
            "circle-stroke-color": c.accent,
            "circle-stroke-width": 2.2,
          }}
        />
        <Layer
          id="track-now"
          type="circle"
          layout={vis(layers.track)}
          paint={{
            "circle-radius": 4.6,
            "circle-color": c.accent,
            "circle-stroke-color": c.surface,
            "circle-stroke-width": 1.8,
          }}
        />
      </Source>
    </>
  );
}

interface AssetProps {
  all: FeatureCollection;
  selected: FeatureCollection;
  layers: LayerState;
  c: Colors;
  /** The square water symbol is registered with the map; until then only the power layer draws. */
  waterIcon: boolean;
}

export function AssetLayers({ all, selected, layers, c, waterIcon }: AssetProps) {
  return (
    <>
      <Source id="assets" type="geojson" data={data(all)}>
        <Layer
          id="electric"
          type="circle"
          filter={["==", ["get", "domain"], "electric"]}
          layout={vis(layers.power)}
          paint={{
            "circle-radius": ["case", ["get", "critical"], 6, 4.5],
            "circle-color": c.ink,
            "circle-stroke-color": c.surface,
            "circle-stroke-width": 1.5,
          }}
        />
        {waterIcon && (
          <Layer
            id="water-assets"
            type="symbol"
            filter={["==", ["get", "domain"], "water"]}
            layout={{
              ...vis(layers.water),
              "icon-image": WATER_ICON,
              "icon-size": ["case", ["get", "critical"], 1.2, 0.9] as never,
              "icon-allow-overlap": true,
              "icon-ignore-placement": true,
            }}
          />
        )}
      </Source>
      <Source id="selected" type="geojson" data={data(selected)}>
        <Layer
          id="selected"
          type="circle"
          paint={{
            "circle-radius": 11,
            "circle-opacity": 0,
            "circle-stroke-color": c.accent,
            "circle-stroke-width": 2.5,
          }}
        />
      </Source>
    </>
  );
}

interface ObservedProps {
  gauges: FeatureCollection;
  warnings: FeatureCollection;
  layers: LayerState;
  c: Colors;
}

const WARNING_RANK = [
  "match",
  ["get", "kind"],
  "tropical_storm",
  0,
  "hurricane",
  1,
  "flood",
  2,
  "flash_flood",
  3,
  4,
];

/** NWS warnings in force, outlined only so the risk colours underneath stay readable, and river gauges coloured
 * by the flood category reached so far; below flood stage they are small muted dots. */
export function ObservedLayers({ gauges, warnings, layers, c }: ObservedProps) {
  const kindColor = [
    "match",
    ["get", "kind"],
    "hurricane",
    c.warning.hurricane,
    "tropical_storm",
    c.warning.tropical_storm,
    "flood",
    c.warning.flood,
    "flash_flood",
    c.warning.flash_flood,
    c.warning.tornado,
  ] as never;
  const category = (below: unknown, minor: unknown, moderate: unknown, major: unknown) =>
    ["match", ["get", "category"], "major", major, "moderate", moderate, "minor", minor, below] as never;
  return (
    <>
      <Source id="warnings" type="geojson" data={data(warnings)}>
        <Layer
          id={WARNING_HIT}
          type="fill"
          layout={vis(layers.warnings)}
          paint={{ "fill-color": kindColor, "fill-opacity": 0 }}
        />
        <Layer
          id="warnings-casing"
          type="line"
          layout={{ ...vis(layers.warnings), "line-join": "round", "line-sort-key": WARNING_RANK as never }}
          paint={{
            "line-color": c.surface,
            "line-opacity": 0.85,
            "line-width": ["case", ["get", "polygon"], 4.4, 3.6] as never,
          }}
        />
        <Layer
          id="warnings-line"
          type="line"
          layout={{ ...vis(layers.warnings), "line-join": "round", "line-sort-key": WARNING_RANK as never }}
          paint={{ "line-color": kindColor, "line-width": ["case", ["get", "polygon"], 2.4, 1.8] as never }}
        />
      </Source>
      <Source id="gauges" type="geojson" data={data(gauges)}>
        <Layer
          id={GAUGE_HIT}
          type="circle"
          layout={{ ...vis(layers.gauges), "circle-sort-key": ["get", "rank"] as never }}
          paint={{
            "circle-radius": [
              "interpolate",
              ["linear"],
              ["zoom"],
              4,
              category(1.6, 3, 3.6, 4.4),
              8,
              category(3, 5, 6, 7),
            ] as never,
            "circle-color": category(c.gauge.below, c.gauge.minor, c.gauge.moderate, c.gauge.major),
            "circle-opacity": category(0.75, 1, 1, 1),
            "circle-stroke-color": c.surface,
            "circle-stroke-width": category(0, 1.2, 1.2, 1.4),
          }}
        />
      </Source>
    </>
  );
}
