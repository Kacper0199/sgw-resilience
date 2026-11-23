import "maplibre-gl/dist/maplibre-gl.css";
import "./map.css";
import {
  Map as MapGL,
  type MapLayerMouseEvent,
  type MapRef,
  NavigationControl,
} from "@vis.gl/react-maplibre";
import { setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useMemo, useRef, useState } from "react";
import type { Asset } from "@/lib/api";
import { formatDayET, formatET } from "@/lib/time";
import { MAX_BOUNDS, MAX_ZOOM, MIN_ZOOM } from "./basemap";
import { countyReadout, countyWithState, formatGust, formatOut, formatRisk } from "./format";
import {
  assetCollection,
  type Bounds,
  boundsOf,
  exteriorOnly,
  type FeatureCollection,
  labelPoint,
} from "./geo";
import counties from "./geo/counties.geo.json";
import footprint from "./geo/footprint.geo.json";
import { type CountyValue, countyCollection, type Domain } from "./layerData";
import type { CountyColour, LayerState } from "./layers";
import { stormOn } from "./layers";
import {
  ASSET_LAYERS,
  AssetLayers,
  BaseLayers,
  COUNTY_HIT,
  FIX_HIT,
  GAUGE_HIT,
  ObservedLayers,
  RegionLayers,
  StormLayers,
  WARNING_HIT,
} from "./MapLayers";
import { type LabelPoint, Overlays, type PulsePoint, type StepStop } from "./Overlays";
import {
  gaugeCollection,
  gaugeTip,
  type ObservedHazard,
  type WindStation,
  warningCollection,
  warningTip,
} from "./observed";
import { SURGE_HIT, SurgeLayers } from "./SurgeLayers";
import type { StormGeometry } from "./storm";
import { type OutageSurge, type SurgeStarts, surgeCollection, surgeLabels, surgeTip } from "./surges";
import { MapTip, TipContext, useTipStore } from "./tip";
import type { Basemap } from "./useBasemap";
import { useFitView } from "./useFitView";
import { useHatchPattern } from "./useHatchPattern";
import { useThemeColors } from "./useThemeColors";
import { useWaterIcon } from "./useWaterIcon";

setWorkerUrl(workerUrl);

const BASE_STYLE = { version: 8 as const, sources: {}, layers: [] };
const REGION_OUTLINE = exteriorOnly(footprint as FeatureCollection);
const FOOTPRINT_BOUNDS: Bounds = boundsOf(footprint as FeatureCollection);
const COUNTY_COLLECTION = counties as FeatureCollection;
const COUNTY_LABELS = COUNTY_COLLECTION.features.map((f) => ({
  fips: String(f.properties.fips),
  at: labelPoint(f),
}));
const FIT_PADDING = 28;
const NO_STATIONS: WindStation[] = [];
const NO_SURGES: OutageSurge[] = [];

interface Props {
  basemap: Basemap | undefined;
  assets: Asset[];
  values: Map<string, CountyValue>;
  /** The outage feed has an hour by now, so a county without a report reads "No data". */
  outagesReported?: boolean;
  domain: Domain | null;
  layers: LayerState;
  storm: StormGeometry;
  observations?: ObservedHazard;
  surges?: OutageSurge[];
  surgeAsOf?: string | null;
  surgeStarts?: SurgeStarts | null;
  selectedIds: ReadonlySet<string>;
  stops: StepStop[];
  activeStepKey: string | null;
  reducedMotion: boolean;
  preview: boolean;
  dimSteps: boolean;
  focusCounty: string | null;
  onAssetClick: (assetIds: string[]) => void;
  onStepClick: (stop: StepStop) => void;
  onValuesZoomChange: (zoomedIn: boolean) => void;
  onFailure: () => void;
}

const colourKey = (c: CountyColour) =>
  c === "risk" ? "risk" : c === "wind" ? "gust" : c === "outages" ? "out" : null;

function ramp(colors: string[], domain: Domain): unknown[] {
  const step = (domain.max - domain.min) / (colors.length - 1);
  return colors.flatMap((c, i) => [domain.min + step * i, c]);
}

/** Customers out span three orders of magnitude, so the colours step by ratio, not by difference. */
function outageRamp(colors: string[], domain: Domain): unknown[] {
  const ratio = (domain.max / domain.min) ** (1 / (colors.length - 1));
  return colors.flatMap((c, i) => [domain.min * ratio ** i, c]);
}

const merge = (a: Bounds, b: Bounds | null): Bounds =>
  b
    ? [
        [Math.min(a[0][0], b[0][0]), Math.min(a[0][1], b[0][1])],
        [Math.max(a[1][0], b[1][0]), Math.max(a[1][1], b[1][1])],
      ]
    : a;

/** Own basemap, region and storm layers, no third-party tiles. Colours follow the theme tokens. */
export default function MapView({
  basemap,
  assets,
  values,
  outagesReported = false,
  domain,
  layers,
  storm,
  observations,
  surges = NO_SURGES,
  surgeAsOf = null,
  surgeStarts = null,
  selectedIds,
  stops,
  activeStepKey,
  reducedMotion,
  preview,
  dimSteps,
  focusCounty,
  onAssetClick,
  onStepClick,
  onValuesZoomChange,
  onFailure,
}: Props) {
  const ref = useRef<MapRef>(null);
  const c = useThemeColors();
  const tip = useTipStore();
  const [ready, setReady] = useState(false);
  const [cursor, setCursor] = useState("");
  const [hoverFips, setHoverFips] = useState<string | null>(null);
  const waterIcon = useWaterIcon(ref, ready, c.assetWater, c.surface);
  const noDataPattern = useHatchPattern(ref, ready, c.noData);

  const home = useMemo(
    () => (stormOn(layers) ? merge(FOOTPRINT_BOUNDS, storm.bounds) : FOOTPRINT_BOUNDS),
    [layers, storm.bounds],
  );
  const focus = useMemo<Bounds | null>(() => {
    const targets = assets.filter((a) => selectedIds.has(a.asset_id));
    const points = [
      ...targets.map((a) => [a.lon_e6 / 1e6, a.lat_e6 / 1e6]),
      ...stops.map((s) => s.position as number[]),
    ];
    if (points.length === 0) {
      const county = focusCounty
        ? COUNTY_COLLECTION.features.find((f) => String(f.properties.fips) === focusCounty)
        : undefined;
      return county ? boundsOf({ type: "FeatureCollection", features: [county] }) : null;
    }
    return boundsOf({
      type: "FeatureCollection",
      features: points.map((p) => ({
        type: "Feature",
        properties: {},
        geometry: { type: "Point", coordinates: p },
      })),
    });
  }, [assets, selectedIds, stops, focusCounty]);

  const key = colourKey(layers.county);
  const countyData = useMemo(
    () => countyCollection(COUNTY_COLLECTION, values, key, outagesReported),
    [values, key, outagesReported],
  );
  const all = useMemo(() => assetCollection(assets), [assets]);
  const gauges = useMemo(() => gaugeCollection(observations?.gauges ?? []), [observations]);
  const warnings = useMemo(() => warningCollection(observations?.warnings ?? []), [observations]);
  const gaugeById = useMemo(
    () => new Map((observations?.gauges ?? []).map((g) => [g.gauge_id, g])),
    [observations],
  );
  const warningById = useMemo(
    () => new Map((observations?.warnings ?? []).map((w) => [w.warning_id, w])),
    [observations],
  );
  const surgeOutlines = useMemo(
    () => surgeCollection(COUNTY_COLLECTION, surges, surgeAsOf),
    [surges, surgeAsOf],
  );
  const surgeLabelList = useMemo(() => surgeLabels(COUNTY_COLLECTION, surges), [surges]);
  const surgeById = useMemo(() => new Map(surges.map((s) => [s.surge_id, s])), [surges]);
  const selected = useMemo(() => assetCollection(assets, selectedIds), [assets, selectedIds]);
  const pulses = useMemo<PulsePoint[]>(
    () =>
      assets
        .filter((a) => selectedIds.has(a.asset_id))
        .map((a) => ({ id: a.asset_id, lon: a.lon_e6 / 1e6, lat: a.lat_e6 / 1e6 })),
    [assets, selectedIds],
  );

  const valueLabels = useMemo<LabelPoint[]>(() => {
    const kind = layers.values;
    if (kind === "none") return [];
    return COUNTY_LABELS.flatMap((l) => {
      const v = values.get(l.fips);
      const raw = kind === "risk" ? v?.risk : kind === "out" ? v?.out : v?.gust;
      if (raw === undefined) return [];
      return [{ id: l.fips, lon: l.at[0], lat: l.at[1], text: valueTextFor(kind, raw), weight: raw }];
    });
  }, [layers.values, values]);
  const stateLabels = useMemo<LabelPoint[]>(
    () =>
      (basemap?.states.features ?? [])
        .filter((f) => f.properties.abbr !== "GA" && f.properties.abbr !== "SC")
        .map((f) => ({
          id: `state-${f.properties.abbr}`,
          lon: Number(f.properties.lon),
          lat: Number(f.properties.lat),
          text: String(f.properties.abbr),
          weight: 0,
        })),
    [basemap],
  );

  const userMoved = useFitView({
    map: ref,
    ready,
    home,
    focus,
    reducedMotion,
    preview,
    homeSettled: !stormOn(layers) || storm.bounds !== null,
  });

  const onClick = (e: MapLayerMouseEvent) => {
    if (overMarker(e)) return;
    const hits = (e.features ?? [])
      .filter((f) => ASSET_LAYERS.includes(f.layer.id))
      .map((f) => String(f.properties?.id));
    if (hits.length > 0) onAssetClick([...new Set(hits)]);
  };
  const onMove = (e: MapLayerMouseEvent) => {
    if (overMarker(e)) return;
    const features = e.features ?? [];
    const asset = features.find((f) => ASSET_LAYERS.includes(f.layer.id));
    const fix = features.find((f) => f.layer.id === FIX_HIT);
    const county = features.find((f) => f.layer.id === COUNTY_HIT);
    const gauge = gaugeById.get(String(features.find((f) => f.layer.id === GAUGE_HIT)?.properties?.id));
    const warning = warningById.get(String(features.find((f) => f.layer.id === WARNING_HIT)?.properties?.id));
    const surge = surgeById.get(String(features.find((f) => f.layer.id === SURGE_HIT)?.properties?.id));
    setCursor(asset || fix ? "pointer" : "");
    const observed =
      !asset && !fix
        ? gauge
          ? gaugeTip(gauge)
          : warning
            ? warningTip(warning)
            : surge
              ? surgeTip(surge)
              : null
        : null;
    const text = observed
      ? observed.text
      : asset
        ? String(asset.properties?.name)
        : fix
          ? `${formatDayET(String(fix.properties?.at))} ${formatET(String(fix.properties?.at))}, ${fix.properties?.mph} mph`
          : county
            ? countyReadout(
                countyWithState(String(county.properties?.name), String(county.properties?.fips)),
                values.get(String(county.properties?.fips)),
                layers.county,
                outagesReported,
              )
            : null;
    const next = !asset && !fix && !observed && county ? String(county.properties?.fips) : null;
    setHoverFips((prev) => (prev === next ? prev : next));
    tip.set(
      text
        ? {
            text,
            detail: observed?.detail,
            x: e.point.x,
            y: e.point.y,
            width: e.target.getContainer().clientWidth,
          }
        : null,
    );
  };

  const clearHover = () => {
    setHoverFips(null);
    tip.set(null);
  };

  const showCounty = layers.county !== "none" && domain !== null;
  const fillColor = !domain
    ? c.land
    : layers.county === "outages"
      ? (["interpolate", ["linear"], ["get", "v"], ...outageRamp([...c.surge].reverse(), domain)] as never)
      : (["interpolate", ["linear"], ["get", "v"], ...ramp(c.risk, domain)] as never);

  return (
    <TipContext.Provider value={tip}>
      <MapGL
        ref={ref}
        mapLib={import("maplibre-gl")}
        mapStyle={BASE_STYLE}
        initialViewState={{ bounds: home, fitBoundsOptions: { padding: FIT_PADDING } }}
        minZoom={MIN_ZOOM}
        maxZoom={MAX_ZOOM}
        maxBounds={MAX_BOUNDS}
        attributionControl={false}
        dragRotate={false}
        touchPitch={false}
        cooperativeGestures={preview}
        cursor={cursor}
        interactiveLayerIds={[COUNTY_HIT, SURGE_HIT, WARNING_HIT, GAUGE_HIT, FIX_HIT, ...ASSET_LAYERS]}
        onClick={onClick}
        onMouseMove={onMove}
        onMouseLeave={clearHover}
        onMouseOut={clearHover}
        onMoveStart={(e) => {
          if (e.originalEvent) userMoved.current = true;
        }}
        onLoad={(e) => {
          setReady(true);
          if (import.meta.env.DEV) (window as unknown as { __sgwMap?: unknown }).__sgwMap = e.target;
        }}
        onError={onFailure}
        style={{ width: "100%", height: "100%" }}
      >
        {!preview && <NavigationControl position="top-right" showCompass={false} />}
        <BaseLayers basemap={basemap} c={c} />
        <RegionLayers
          c={c}
          counties={countyData}
          footprint={REGION_OUTLINE}
          colour={showCounty ? layers.county : "none"}
          domain={domain}
          fillColor={fillColor}
          hoverFips={hoverFips}
          focusFips={focusCounty}
          noDataPattern={noDataPattern}
        />
        <SurgeLayers
          on={layers.surges}
          outlines={surgeOutlines}
          labels={surgeLabelList}
          starts={surgeStarts}
          c={c}
        />
        <ObservedLayers gauges={gauges} warnings={warnings} layers={layers} c={c} />
        <StormLayers storm={storm} layers={layers} c={c} />
        <AssetLayers all={all} selected={selected} layers={layers} c={c} waterIcon={waterIcon} />
        <Overlays
          stops={stops}
          activeStepKey={activeStepKey}
          showSteps={layers.steps}
          pulses={pulses}
          dimSteps={dimSteps}
          values={valueLabels}
          states={stateLabels}
          stations={layers.wind ? (observations?.stations ?? []) : NO_STATIONS}
          showStationValues={layers.windValues}
          onStepClick={onStepClick}
          onValuesZoomChange={onValuesZoomChange}
        />
      </MapGL>
      <MapTip store={tip} />
    </TipContext.Provider>
  );
}

const overMarker = (e: MapLayerMouseEvent) =>
  e.originalEvent.target instanceof Element && e.originalEvent.target.closest(".maplibregl-marker") !== null;

function valueTextFor(kind: "risk" | "gust" | "out", raw: number): string {
  return kind === "risk" ? formatRisk(raw) : kind === "out" ? formatOut(raw) : formatGust(raw);
}
