import { useQuery } from "@tanstack/react-query";
import { geoUrl } from "./basemap";
import { type Bounds, boundsOf, type Feature, type FeatureCollection } from "./geo";
import type { AdvisoryHazard } from "./types";

/** `[lead hours, lat, lon, max wind kt]` */
type NhcFix = [number, number, number, number];

/** The official NHC five-day cone, forecast track and forecast points of one advisory (public-domain GIS archive). */
export interface NhcProduct {
  label: string;
  nhc_advisory: number;
  cone: [number, number][];
  track: [number, number][];
  fixes: NhcFix[];
}

export type NhcProducts = Record<string, NhcProduct>;

const APPROACH_H = 12;
const FALLBACK_HORIZON_H = 48;
const FALLBACK_STEP_H = 12;
const MPH_PER_KT = 1.15078;

export const useNhcProducts = () =>
  useQuery({
    queryKey: ["geo", "helene-nhc"],
    queryFn: async (): Promise<NhcProducts> => {
      const res = await fetch(geoUrl("helene-nhc.json"));
      if (!res.ok) throw new Error(`helene-nhc.json ${res.status}`);
      return res.json();
    },
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });

export const issuedKey = (iso: string) => new Date(iso).toISOString().replace(".000Z", "Z");

const empty = (): FeatureCollection => ({ type: "FeatureCollection", features: [] });

export interface StormGeometry {
  cone: FeatureCollection;
  past: FeatureCollection;
  future: FeatureCollection;
  fixes: FeatureCollection;
  now: FeatureCollection;
  bounds: Bounds | null;
  source: "nhc" | "replay" | null;
}

const line = (coordinates: number[][]): FeatureCollection => ({
  type: "FeatureCollection",
  features:
    coordinates.length < 2
      ? []
      : [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates } }],
});

const point = (coordinates: number[], properties: Feature["properties"] = {}): Feature => ({
  type: "Feature",
  properties,
  geometry: { type: "Point", coordinates },
});

const collect = (features: Feature[]): FeatureCollection => ({ type: "FeatureCollection", features });

const fixPoint = (issuedUtc: string, [lead, lat, lon, kt]: NhcFix): Feature =>
  point([lon, lat], {
    at: new Date(Date.parse(issuedUtc) + lead * 3_600_000).toISOString(),
    kt,
    mph: Math.round(kt * MPH_PER_KT),
  });

/** Fixes of the replayed official forecast, thinned to the NHC spacing and cut where the storm is gone. */
function replayFixes(h: AdvisoryHazard): NhcFix[] {
  return h.official_track.filter((f) => f[0] <= FALLBACK_HORIZON_H && f[0] % FALLBACK_STEP_H === 0);
}

export function stormGeometry(h: AdvisoryHazard | undefined, product: NhcProduct | undefined): StormGeometry {
  if (!h) {
    return {
      cone: empty(),
      past: empty(),
      future: empty(),
      fixes: empty(),
      now: empty(),
      bounds: null,
      source: null,
    };
  }
  const fixes: NhcFix[] = product ? product.fixes : replayFixes(h);
  const future = product ? product.track : fixes.map((f) => [f[2], f[1]]);
  const first = fixes[0];
  const past = h.analysis_track.map((f) => [f[2], f[1]]);
  const joined = first && past.length > 0 ? [...past, [first[2], first[1]]] : past;
  const approach = fixes.filter((f) => f[0] <= APPROACH_H).map((f) => point([f[2], f[1]]));
  return {
    cone: product
      ? collect([
          { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [product.cone] } },
        ])
      : empty(),
    past: line(joined),
    future: line(future),
    fixes: collect(fixes.slice(1).map((f) => fixPoint(h.issued_utc, f))),
    now: collect(first ? [point([first[2], first[1]])] : []),
    bounds: approach.length > 0 ? boundsOf(collect(approach)) : null,
    source: product ? "nhc" : "replay",
  };
}
