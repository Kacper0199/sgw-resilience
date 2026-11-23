import type { CountyValue } from "./layerData";
import type { CountyColour, ValueLabels } from "./layers";

const MPH_PER_MS = 2.23694;

export const formatRisk = (ppm: number) => `${Math.round(ppm / 10_000)}%`;
export const formatGust = (ms: number) => `${Math.round(ms * MPH_PER_MS)} mph`;

/** "842", "12k", "202k", "1.3M": customers out, short enough for a county label. */
export function formatOut(customers: number): string {
  if (customers >= 1_000_000) return `${(customers / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (customers >= 10_000) return `${Math.round(customers / 1000)}k`;
  if (customers >= 1000) return `${(customers / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(customers);
}

export function valueText(value: CountyValue | undefined, kind: ValueLabels | CountyColour): string | null {
  if (!value) return null;
  if (kind === "risk") return value.risk === undefined ? null : formatRisk(value.risk);
  if (kind === "gust" || kind === "wind") return value.gust === undefined ? null : formatGust(value.gust);
  if (kind === "out" || kind === "outages")
    return value.out === undefined ? null : `${value.out.toLocaleString("en-US")} out now`;
  return null;
}

export function countyReadout(
  name: string,
  value: CountyValue | undefined,
  county: CountyColour,
  outagesReported = false,
): string {
  const raw = valueText(value, county);
  const text =
    raw && county === "risk"
      ? `outage risk ${raw}`
      : (raw ?? (county === "outages" && outagesReported ? NO_DATA : null));
  return text ? `${name}: ${text}` : name;
}

export const NO_DATA = "No data";

const STATE_BY_FIPS: Record<string, string> = {
  "01": "AL",
  "12": "FL",
  "13": "GA",
  "21": "KY",
  "37": "NC",
  "45": "SC",
  "47": "TN",
  "51": "VA",
  "54": "WV",
};

/** "Clinch" with FIPS 13065 reads as "Clinch, GA", as on the Forecast page. */
export const countyWithState = (name: string, fips: string): string => {
  const state = STATE_BY_FIPS[fips.slice(0, 2)];
  return state ? `${name}, ${state}` : name;
};
