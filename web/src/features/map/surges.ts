import { useQuery } from "@tanstack/react-query";
import type { components } from "@/contracts/api.gen";
import { getJson } from "@/lib/api";
import { formatDayET, formatET } from "@/lib/time";
import { type Feature, type FeatureCollection, labelPoint } from "./geo";
import type { TipText } from "./observed";

export type SurgeReport = components["schemas"]["SurgeReport"];
export type OutageSurge = components["schemas"]["OutageSurge"];

/** County outage surges from the EAGLE-I detector at the time the observed layers show (`as_of`). */
export const useSurges = (asOf: string | null, enabled: boolean) =>
  useQuery({
    queryKey: ["outages", "surges", asOf],
    queryFn: () => getJson<SurgeReport>(`/api/outages/surges?as_of=${encodeURIComponent(asOf as string)}`),
    enabled: enabled && asOf !== null,
    staleTime: Number.POSITIVE_INFINITY,
    placeholderData: (previous) => previous,
    retry: false,
  });

export const activeSurges = (report: SurgeReport | undefined): OutageSurge[] =>
  (report?.surges ?? []).filter((s) => s.status === "active");

export const RECENT_SURGE_MS = 3 * 3_600_000;

const onsetMs = (s: OutageSurge) => Date.parse(s.onset_at);

/** Every surging county, one feature each, carrying the surge id, when it began and whether it began in the last 3 hours. */
export function surgeCollection(
  counties: FeatureCollection,
  surges: OutageSurge[],
  asOf: string | null,
): FeatureCollection {
  const byFips = new Map(surges.map((s) => [s.fips, s]));
  const since = asOf === null ? Number.POSITIVE_INFINITY : Date.parse(asOf) - RECENT_SURGE_MS;
  return {
    type: "FeatureCollection",
    features: counties.features.flatMap((f): Feature[] => {
      const s = byFips.get(String(f.properties.fips));
      return s
        ? [
            {
              ...f,
              properties: { ...f.properties, id: s.surge_id, onset: onsetMs(s), recent: onsetMs(s) >= since },
            },
          ]
        : [];
    }),
  };
}

export interface SurgeStarts {
  first: string;
  last: string;
  /** Counties whose surge began in the last 3 hours before the report time. */
  recent: number;
}

/** When the first and the latest surge began, for the legend of the start-time colours. */
export function surgeStarts(surges: OutageSurge[], asOf: string | null): SurgeStarts | null {
  if (surges.length === 0) return null;
  const ordered = [...surges].sort((a, b) => onsetMs(a) - onsetMs(b));
  const since = asOf === null ? Number.POSITIVE_INFINITY : Date.parse(asOf) - RECENT_SURGE_MS;
  return {
    first: (ordered[0] as OutageSurge).onset_at,
    last: (ordered[ordered.length - 1] as OutageSurge).onset_at,
    recent: surges.filter((s) => onsetMs(s) >= since).length,
  };
}

export interface SurgeLabel {
  id: string;
  lon: number;
  lat: number;
  text: string;
}

export function surgeLabels(counties: FeatureCollection, surges: OutageSurge[]): SurgeLabel[] {
  const at = new Map(counties.features.map((f) => [String(f.properties.fips), labelPoint(f)]));
  return surges.flatMap((s) => {
    const p = at.get(s.fips);
    return p
      ? [
          {
            id: s.surge_id,
            lon: p[0],
            lat: p[1],
            text: `from ${formatDayET(s.onset_at)} ${formatET(s.onset_at)}`,
          },
        ]
      : [];
  });
}

const CONFIDENCE: Record<OutageSurge["confidence_band"], string> = {
  high: "high confidence",
  medium: "medium confidence",
  low: "low confidence",
};

const percent = (share: number) => (share > 0 && share < 0.01 ? "under 1%" : `${Math.round(share * 100)}%`);

/** "Outage surge in Burke, GA" with when it started, how many are out, and the detector's confidence. */
export function surgeTip(s: OutageSurge): TipText {
  return {
    text: `Outage surge in ${s.county}, ${s.state}`,
    detail: `Since ${formatDayET(s.onset_at)} ${formatET(s.onset_at)}, ${s.customers_out.toLocaleString("en-US")} customers out (${percent(s.share_out)} of the county), ${CONFIDENCE[s.confidence_band]}`,
  };
}
