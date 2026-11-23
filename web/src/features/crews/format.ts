import { assetName } from "@/lib/names";

const minus = (s: string) => s.replace("-", "−");

export const int = (n: number): string => Math.round(n).toLocaleString("en-US");

export const millions = (n: number, digits = 1): string => `${(n / 1e6).toFixed(digits)} M`;

export const usdMillions = (n: number, digits = 1): string => `$${(n / 1e6).toFixed(digits)} M`;

export const deltaPercent = (value: number, base: number): string => {
  const d = ((value - base) / base) * 100;
  if (Math.abs(d) < 0.05) return "same";
  return `${minus(d.toFixed(Math.abs(d) < 10 ? 1 : 0))}%`.replace(/^(\d)/, "+$1");
};

export { yardName } from "@/lib/names";

/** A crew location in words: a yard, a hospital, a feeder by name; a pump station by its short label. */
export const placeName = assetName;

export const PLAN_UI = {
  P50: {
    name: "Standard plan",
    blurb: "Middle forecast only",
  },
  "COA-A": {
    name: "A: Same cost, better placed",
    blurb: "Same early aid, crews placed for the full range",
  },
  "COA-B": {
    name: "B: Pre-stage for a big storm",
    blurb: "Far more early aid; idle if the storm is small",
  },
  "COA-C": {
    name: "C: Own crews first",
    blurb: "No early aid; help arrives a day later",
  },
} as const;

/** The counties a crew list reports from, in plain words ("Aiken and Richmond"); null when none is known. */
export function reportingArea(
  crews: readonly { region_id?: string | null }[],
  regions: readonly { region_id: string; name: string }[] | undefined,
): string | null {
  const names = [...new Set(crews.map((c) => c.region_id).filter((id): id is string => Boolean(id)))]
    .map((id) => regions?.find((r) => r.region_id === id)?.name.replace(/ County$/, ""))
    .filter((n): n is string => Boolean(n))
    .sort();
  if (names.length === 0) return null;
  return names.length === 1 ? (names[0] as string) : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}
