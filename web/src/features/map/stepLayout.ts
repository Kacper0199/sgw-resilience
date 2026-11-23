import { relaxMarkers, spreadMarkers } from "./declutter";

export const STEP_SIZE = 26;
export const PULSE_CLEAR = 44;
/** Zoom range over which the badge layout stays as it is; it is computed at the lower end, where markers lie closest. */
export const LAYOUT_RANGE = 0.5;
const TILE = 512;

interface Point {
  x: number;
  y: number;
}

export interface LayoutStop {
  key: string;
  assetId: string;
  position: [number, number];
}

export interface LayoutPulse {
  id: string;
  lon: number;
  lat: number;
}

export interface StepLayout {
  /** Pixel offset of each badge from its own coordinates, by stop key. */
  offsets: Map<string, [number, number]>;
  /** The badge each pulse ring sits on, by asset id. */
  owners: Map<string, string>;
}

export const layoutZoom = (zoom: number): number => Math.floor(zoom / LAYOUT_RANGE) * LAYOUT_RANGE;

/** Web Mercator pixel of a coordinate at a zoom: a pixel difference between two points does not depend on the
 * map centre, so a layout computed from these is the same wherever the map is panned. */
export function worldPixel(lon: number, lat: number, zoom: number): Point {
  const scale = TILE * 2 ** zoom;
  const sin = Math.sin((lat * Math.PI) / 180);
  return {
    x: ((lon + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale,
  };
}

/**
 * Where each step badge sits so that no two touch and none lies on a pulse ring. A pure function of the stops, the
 * rings and the zoom range, in input order: the same range always gives the same order and offsets, whatever the
 * map centre or the way the user got there.
 */
export function layoutSteps(stops: LayoutStop[], pulses: LayoutPulse[], zoom: number): StepLayout {
  const at = layoutZoom(zoom);
  const own = new Map(stops.map((s) => [s.key, worldPixel(s.position[0], s.position[1], at)]));
  const fanned = spreadMarkers(
    stops.map((s) => ({ id: s.key, ...(own.get(s.key) as Point) })),
    STEP_SIZE,
  );
  const owners = new Map(
    pulses.flatMap((p) => {
      const stop = stops.find((s) => s.assetId === p.id);
      return stop ? [[p.id, stop.key] as const] : [];
    }),
  );
  const ownerKeys = new Set(owners.values());
  const apart = relaxMarkers(
    new Map([...fanned].filter(([key]) => ownerKeys.has(key))),
    new Set(),
    [],
    PULSE_CLEAR - 2,
    0,
  );
  const base = new Map([...fanned, ...apart]);
  const rings = pulses.map((p) => {
    const key = owners.get(p.id);
    return key ? (base.get(key) as Point) : worldPixel(p.lon, p.lat, at);
  });
  const placed = relaxMarkers(base, ownerKeys, rings, STEP_SIZE, PULSE_CLEAR);
  const offsets = new Map(
    stops.flatMap((s) => {
      const to = placed.get(s.key);
      const from = own.get(s.key);
      return to && from ? [[s.key, [Math.round(to.x - from.x), Math.round(to.y - from.y)]] as const] : [];
    }),
  );
  return { offsets: offsets as Map<string, [number, number]>, owners };
}
