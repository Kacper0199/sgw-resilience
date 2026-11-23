import type { UiSeverity } from "@/contracts/vocab.gen";
import type { HazardAction, HeatUnit, HeatView, WildfireView } from "./hazardTypes";

export const VIEWS = ["heat", "wildfire"] as const;
export type HazardViewName = (typeof VIEWS)[number];

const etDay = new Intl.DateTimeFormat("en-GB", {
  timeZone: "America/New_York",
  day: "numeric",
  month: "short",
});
const etYear = new Intl.DateTimeFormat("en-GB", { timeZone: "America/New_York", year: "numeric" });

/** "15 Jul" in Eastern time. */
export const dayET = (iso: string) => etDay.format(new Date(iso));

/** "13–18 Jul 2024": the scenario window in Eastern days; the end is exclusive. */
export function windowText(startIso: string, endIso: string): string {
  const last = new Date(Date.parse(endIso) - 1).toISOString();
  const [d1, m1] = dayET(startIso).split(" ");
  const [d2, m2] = dayET(last).split(" ");
  const year = etYear.format(new Date(last));
  return m1 === m2 ? `${d1}–${d2} ${m2} ${year}` : `${d1} ${m1} – ${d2} ${m2} ${year}`;
}

/** "5 Jul" from a local ISO date such as "2024-07-05". */
export const localDay = (isoDate: string) => {
  const [, m, d] = isoDate.split("-").map(Number);
  return `${d} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][(m ?? 1) - 1]}`;
};

export const ALARM: Record<HeatUnit["alarm"], { level: UiSeverity; label: string }> = {
  emergency: { level: "severe", label: "Emergency" },
  warning: { level: "elevated", label: "Warning" },
  watch: { level: "advisory", label: "Watch" },
  normal: { level: "normal", label: "Normal" },
};

export const unitsInWarning = (view: HeatView) =>
  view.units.filter((u) => u.alarm === "warning" || u.alarm === "emergency").length;

export function firstHotRun(view: HeatView): string | null {
  return view.days.find((d) => d.hot && d.day === view.trigger_fired_utc.slice(0, 10))?.day ?? null;
}

export const redFlagHours = (view: WildfireView) => view.episodes.reduce((n, e) => n + e.hours, 0);

export const peakIndex = (view: WildfireView) => Math.max(...view.hours.map((h) => h.ffwi));

/** "1.35%" for a window probability. */
export const percent = (p: number) => `${(p * 100).toFixed(2)}%`;

const SHORT: Record<string, string> = {
  "wildfire.recloser_one_shot_settings": "Refer one-shot reclosing to the protection operator",
  "wildfire.targeted_de_energisation": "De-energise rank 1, last resort",
  "heat.protect_critical_load": "Keep units serving PS-17 and Tallowbranch hospital out of any shed block",
};

/** The secondary steps in a few words; the first recommended step keeps its full text. */
export const shortText = (a: HazardAction) => SHORT[a.action_id] ?? a.text;
