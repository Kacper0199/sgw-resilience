import type { Asset } from "@/lib/api";
import type { Bounds, Feature, FeatureCollection } from "./geo";

export interface CountyValue {
  fips: string;
  name: string;
  risk?: number;
  gust?: number;
  /** Customers out now, from the outage feed. */
  out?: number;
}

export interface Domain {
  min: number;
  max: number;
}

export function domainOf(values: (number | undefined)[]): Domain | null {
  const v = values.filter((x): x is number => x !== undefined);
  if (v.length === 0) return null;
  const min = Math.min(...v);
  const max = Math.max(...v);
  return { min, max: max > min ? max : min + 1e-6 };
}

/** Counties carry the shown value as `v`; with the outage feed read, a county it has no report for carries `nodata`. */
export function countyCollection(
  counties: FeatureCollection,
  values: Map<string, CountyValue>,
  key: "risk" | "gust" | "out" | null,
  outagesReported = false,
): FeatureCollection {
  const marksNoData = key === "out" && outagesReported;
  return {
    type: "FeatureCollection",
    features: counties.features.map((f): Feature => {
      const fips = String(f.properties.fips);
      const v = key ? values.get(fips)?.[key] : undefined;
      const extra: Feature["properties"] = v !== undefined ? { v } : marksNoData ? { nodata: true } : {};
      return { ...f, properties: { ...f.properties, ...extra } };
    }),
  };
}

export const unionBounds = (a: Bounds, b: Bounds | null): Bounds =>
  b
    ? [
        [Math.min(a[0][0], b[0][0]), Math.min(a[0][1], b[0][1])],
        [Math.max(a[1][0], b[1][0]), Math.max(a[1][1], b[1][1])],
      ]
    : a;

export const assetPosition = (a: Asset): [number, number] => [a.lon_e6 / 1e6, a.lat_e6 / 1e6];
