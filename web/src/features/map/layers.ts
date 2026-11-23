export type CountyColour = "risk" | "wind" | "outages" | "none";
export type ValueLabels = "risk" | "gust" | "out" | "none";
export type Utility = "all" | "power" | "water";

export interface LayerState {
  county: CountyColour;
  values: ValueLabels;
  power: boolean;
  water: boolean;
  track: boolean;
  cone: boolean;
  steps: boolean;
  warnings: boolean;
  gauges: boolean;
  wind: boolean;
  windValues: boolean;
  surges: boolean;
}

export const DEFAULT_LAYERS: LayerState = {
  county: "risk",
  values: "risk",
  power: true,
  water: true,
  track: true,
  cone: true,
  steps: true,
  warnings: false,
  gauges: false,
  wind: false,
  windValues: true,
  surges: false,
};

export const OBSERVED_LAYERS: LayerState = {
  ...DEFAULT_LAYERS,
  county: "outages",
  values: "out",
  track: false,
  cone: false,
};

export const PREVIEW_LAYERS: LayerState = { ...DEFAULT_LAYERS, values: "none", track: false, cone: false };
export const OBSERVED_PREVIEW_LAYERS: LayerState = { ...OBSERVED_LAYERS, values: "none" };

/** A scripted exercise has no forecast models: customers out and the storm track only. */
export const PACK_LAYERS: LayerState = { ...OBSERVED_LAYERS, track: true };
export const PACK_PREVIEW_LAYERS: LayerState = { ...OBSERVED_LAYERS, values: "none" };

/** After the final advisory or the outage peak the forecast is history: the map opens on what was observed. */
export const defaultLayers = (forecastIsHistory: boolean, preview = false, scripted = false): LayerState =>
  scripted
    ? preview
      ? PACK_PREVIEW_LAYERS
      : PACK_LAYERS
    : forecastIsHistory
      ? preview
        ? OBSERVED_PREVIEW_LAYERS
        : OBSERVED_LAYERS
      : preview
        ? PREVIEW_LAYERS
        : DEFAULT_LAYERS;

export const utilityOf = (l: LayerState): Utility =>
  l.power === l.water ? "all" : l.power ? "power" : "water";

export const withUtility = (l: LayerState, u: Utility): LayerState => ({
  ...l,
  power: u !== "water",
  water: u !== "power",
});

export const stormOn = (l: LayerState) => l.track || l.cone;

export const observedOn = (l: LayerState) => l.warnings || l.gauges || l.wind;
