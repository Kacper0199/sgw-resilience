export interface Feature {
  type: "Feature";
  properties: Record<string, string | number | boolean | null>;
  geometry: { type: string; coordinates: unknown };
}
export interface FeatureCollection {
  type: "FeatureCollection";
  features: Feature[];
}

export type Bounds = [[number, number], [number, number]];

export function boundsOf(fc: FeatureCollection): Bounds {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  const visit = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number" && typeof c[1] === "number") {
      minLon = Math.min(minLon, c[0]);
      maxLon = Math.max(maxLon, c[0]);
      minLat = Math.min(minLat, c[1]);
      maxLat = Math.max(maxLat, c[1]);
    } else if (Array.isArray(c)) c.forEach(visit);
  };
  for (const f of fc.features) visit(f.geometry.coordinates);
  return [
    [minLon, minLat],
    [maxLon, maxLat],
  ];
}

type Ring = number[][];

/** The outer boundary only: the union of the counties carries slivers between them that must not be outlined. */
export function exteriorOnly(fc: FeatureCollection): FeatureCollection {
  return {
    ...fc,
    features: fc.features.map((f) => ({
      ...f,
      geometry:
        f.geometry.type === "Polygon"
          ? { type: "Polygon", coordinates: [(f.geometry.coordinates as Ring[])[0]] }
          : { type: "MultiPolygon", coordinates: (f.geometry.coordinates as Ring[][]).map((p) => [p[0]]) },
    })),
  };
}

const cross = (a: number[], b: number[]) => (a[0] ?? 0) * (b[1] ?? 0) - (b[0] ?? 0) * (a[1] ?? 0);

const ringArea = (r: Ring) => {
  let sum = 0;
  for (let i = 0; i < r.length - 1; i++) sum += cross(r[i] as number[], r[i + 1] as number[]);
  return sum / 2;
};

/** The centroid of the largest outer ring of a polygon or multipolygon, for placing one label per feature. */
export function labelPoint(f: Feature): [number, number] {
  const g = f.geometry;
  const rings: Ring[] =
    g.type === "Polygon"
      ? [(g.coordinates as Ring[])[0] as Ring]
      : ((g.coordinates as Ring[][]).map((p) => p[0]) as Ring[]);
  const ring = rings.reduce((best, r) => (Math.abs(ringArea(r)) > Math.abs(ringArea(best)) ? r : best));
  const area = ringArea(ring);
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    const p = ring[i] as number[];
    const q = ring[i + 1] as number[];
    const w = cross(p, q);
    cx += ((p[0] ?? 0) + (q[0] ?? 0)) * w;
    cy += ((p[1] ?? 0) + (q[1] ?? 0)) * w;
  }
  return [cx / (6 * area), cy / (6 * area)];
}

export const cssVar = (name: string): string =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function mapColors() {
  return {
    water: cssVar("--map-water"),
    land: cssVar("--map-land"),
    landUs: cssVar("--map-land-us"),
    landOther: cssVar("--map-land-other"),
    state: cssVar("--map-state"),
    region: cssVar("--map-region"),
    regionLine: cssVar("--map-region-line"),
    geoLabel: cssVar("--map-geo-label"),
    line: cssVar("--map-line"),
    coast: cssVar("--map-coast"),
    assetWater: cssVar("--map-asset-water"),
    ink: cssVar("--ink"),
    surface: cssVar("--surface"),
    accent: cssVar("--link"),
    muted: cssVar("--muted"),
    risk: [1, 2, 3, 4, 5].map((i) => cssVar(`--risk-${i}`)),
    surge: [1, 2, 3, 4, 5].map((i) => cssVar(`--map-surge-${i}`)),
    noData: cssVar("--map-nodata"),
    gauge: {
      below: cssVar("--map-gauge-below"),
      minor: cssVar("--map-gauge-minor"),
      moderate: cssVar("--map-gauge-moderate"),
      major: cssVar("--map-gauge-major"),
    },
    warning: {
      hurricane: cssVar("--map-warning-hurricane"),
      tropical_storm: cssVar("--map-warning-tropical"),
      flood: cssVar("--map-warning-flood"),
      flash_flood: cssVar("--map-warning-flash-flood"),
      tornado: cssVar("--map-warning-tornado"),
    },
  };
}

import type { Asset } from "@/lib/api";
import { assetLabel } from "@/lib/names";

const assetPoint = (a: Asset): Feature => ({
  type: "Feature",
  properties: { id: a.asset_id, name: assetLabel(a), domain: a.domain, critical: a.critical_facility },
  geometry: { type: "Point", coordinates: [a.lon_e6 / 1e6, a.lat_e6 / 1e6] },
});

export const assetCollection = (assets: Asset[], only?: ReadonlySet<string>): FeatureCollection => ({
  type: "FeatureCollection",
  features: assets.filter((a) => !only || only.has(a.asset_id)).map(assetPoint),
});
