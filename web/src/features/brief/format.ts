import type { BriefNumber } from "./types";

const nf = new Intl.NumberFormat("en-US");
export const formatCount = (n: number): string => nf.format(n);

export type Basis = "actual" | "forecast";

export interface Shown {
  value: string;
  line: string;
  source: string;
}

/** What one of the four numbers shows for the chosen basis. Pure formatting of what the server sent. */
export function shownFor(n: BriefNumber, basis: Basis, nowZ: (iso: string) => string): Shown | null {
  if (basis === "actual") {
    if (!n.actual) return null;
    return {
      value: formatCount(n.actual.value),
      line: n.actual.detail ?? `as of ${nowZ(n.actual.as_of)}`,
      source: n.actual.source_id,
    };
  }
  const f = n.forecast;
  if (!f) return null;
  const line =
    f.low !== null && f.high !== null
      ? `80% range ${formatCount(f.low)} to ${formatCount(f.high)}`
      : f.basis
        ? `Counts ${f.basis}`
        : "Model median";
  return { value: formatCount(f.p50), line, source: f.source_id };
}

const etDay = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  weekday: "short",
  day: "numeric",
  month: "short",
});

/** "Thu 26 Sep" in Eastern Time, the day the scenario clock is on. */
export function formatWeekdayEt(iso: string): string {
  const p = Object.fromEntries(etDay.formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
  return `${p.weekday} ${p.day} ${p.month}`;
}
