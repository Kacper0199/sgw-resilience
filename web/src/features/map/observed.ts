import { useQuery } from "@tanstack/react-query";
import type { components } from "@/contracts/api.gen";
import { getJson } from "@/lib/api";
import { formatDayET, formatET } from "@/lib/time";
import type { Feature, FeatureCollection } from "./geo";

export type ObservedHazard = components["schemas"]["ObservedHazard"];
export type GaugeObserved = components["schemas"]["GaugeObserved"];
export type WindStation = components["schemas"]["WindStationObserved"];
export type WarningArea = components["schemas"]["WarningArea"];
export type WarningKind = WarningArea["kind"];
export type FloodCategory = GaugeObserved["category"];

const BUCKET_MS = 15 * 60_000;

/** The time the observed layers show: the clock when the map is live, else the shown advisory's issue time.
 * Rounded down to 15 minutes so a running clock does not refetch every second. */
export function observedAt(live: boolean, now: string | null, issued: string | null): string | null {
  const iso = live ? (now ?? issued) : issued;
  if (!iso) return null;
  const t = Math.floor(Date.parse(iso) / BUCKET_MS) * BUCKET_MS;
  return new Date(t).toISOString().replace(".000Z", "Z");
}

export const useObserved = (asOf: string | null, enabled: boolean) =>
  useQuery({
    queryKey: ["hazard", "observed", asOf],
    queryFn: () =>
      getJson<ObservedHazard>(`/api/hazard/observed?as_of=${encodeURIComponent(asOf as string)}`),
    enabled: enabled && asOf !== null,
    staleTime: Number.POSITIVE_INFINITY,
    placeholderData: (previous) => previous,
    retry: false,
  });

export const WARNING_LABEL: Record<WarningKind, string> = {
  hurricane: "Hurricane",
  tropical_storm: "Tropical storm",
  flood: "Flood",
  flash_flood: "Flash flood",
  tornado: "Tornado",
};

export const WARNING_ORDER: WarningKind[] = [
  "hurricane",
  "tropical_storm",
  "tornado",
  "flash_flood",
  "flood",
];

export const FLOOD_LABEL: Record<FloodCategory, string> = {
  major: "Major flood",
  moderate: "Moderate flood",
  minor: "Minor flood",
  below: "Below flood stage",
};

export const FLOOD_ORDER: FloodCategory[] = ["major", "moderate", "minor", "below"];

const RANK: Record<FloodCategory, number> = { below: 0, minor: 1, moderate: 2, major: 3 };

const when = (iso: string) => `${formatDayET(iso)} ${formatET(iso)}`;
const ft = (v: number) => `${v.toFixed(1)} ft`;

export function gaugeCollection(gauges: GaugeObserved[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: [...gauges]
      .sort((a, b) => RANK[a.category] - RANK[b.category])
      .map(
        (g): Feature => ({
          type: "Feature",
          properties: { id: g.gauge_id, category: g.category, rank: RANK[g.category] },
          geometry: { type: "Point", coordinates: [g.lon, g.lat] },
        }),
      ),
  };
}

export function warningCollection(warnings: WarningArea[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: warnings.map(
      (w): Feature => ({
        type: "Feature",
        properties: {
          id: w.warning_id,
          kind: w.kind,
          polygon: w.kind !== "hurricane" && w.kind !== "tropical_storm",
        },
        geometry: w.geometry as Feature["geometry"],
      }),
    ),
  };
}

export interface TipText {
  text: string;
  detail?: string;
}

export function gaugeTip(g: GaugeObserved): TipText {
  if (g.peak_ft === null || g.peak_utc === null) return { text: g.name, detail: "No report yet" };
  return {
    text: g.name,
    detail: `${FLOOD_LABEL[g.category]}, ${ft(g.peak_ft)} so far (flood ${ft(g.flood_ft)}) at ${when(g.peak_utc)}`,
  };
}

const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

export const compass = (deg: number) => COMPASS[Math.round((((deg % 360) + 360) % 360) / 45) % 8] as string;

export function stationTip(s: WindStation): TipText {
  const text = `${s.name} airport`;
  if (s.gust_mph === null || s.gust_utc === null) return { text, detail: "No gust reported yet" };
  const from = s.from_deg === null ? "" : ` from ${compass(s.from_deg)}`;
  const silent = s.silent_since_utc ? `\nNo report since ${when(s.silent_since_utc)}` : "";
  return { text, detail: `Peak gust so far ${s.gust_mph} mph${from} at ${when(s.gust_utc)}${silent}` };
}

export function warningTip(w: Pick<WarningArea, "kind" | "issued_utc" | "expires_utc">): TipText {
  return {
    text: `${WARNING_LABEL[w.kind]} warning`,
    detail: `${when(w.issued_utc)} to ${when(w.expires_utc)}`,
  };
}

const ARROW_MIN = 22;
const ARROW_MAX = 44;

/** Arrow length in px: 22 px up to 20 mph, 44 px from 90 mph, linear between; shorter when zoomed out below 6 so
 * neighbouring airports do not overlap (half length at zoom 4). */
export function arrowLength(mph: number, zoom = 6): number {
  const t = Math.min(1, Math.max(0, (mph - 20) / 70));
  const scale = Math.min(1, Math.max(0.5, 0.5 + (zoom - 4) * 0.25));
  return Math.round((ARROW_MIN + t * (ARROW_MAX - ARROW_MIN)) * scale);
}

/** Screen rotation of an arrow that points where the wind blows to (meteorological `from` + 180). */
export const downwind = (fromDeg: number) => (fromDeg + 180) % 360;
