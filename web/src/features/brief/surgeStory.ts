import { formatDayET, formatET } from "@/lib/time";

const HOUR_MS = 3_600_000;

export interface SurgeStory {
  total: number;
  first: { count: number; at: string };
  latest: string | null;
}

/** When county outage surges began and how far they spread, from the onset time of each surge. */
export function surgeStory(onsets: readonly string[]): SurgeStory | null {
  const times = onsets.map((o) => Date.parse(o)).sort((a, b) => a - b);
  const [first] = times;
  if (first === undefined) return null;
  const count = times.filter((t) => t - first < HOUR_MS).length;
  const last = times[times.length - 1] ?? first;
  return {
    total: times.length,
    first: { count, at: new Date(first).toISOString() },
    latest: count === times.length ? null : new Date(last).toISOString(),
  };
}

/** The same story anchored on the first detections of every surge known so far (active or ended), so the
 * start never moves between moments; the spread counts the surges active now. */
export function surgeSpread(
  allDetected: readonly string[],
  activeDetected: readonly string[],
): SurgeStory | null {
  const all = surgeStory(allDetected);
  const active = surgeStory(activeDetected);
  if (!all || !active) return null;
  const latest = activeDetected
    .map((d) => Date.parse(d))
    .sort((a, b) => a - b)
    .at(-1);
  const startsLater = latest !== undefined && latest - Date.parse(all.first.at) >= HOUR_MS;
  return {
    total: active.total,
    first: all.first,
    latest: startsLater && latest !== undefined ? new Date(latest).toISOString() : null,
  };
}

/** "5 Sep 05:00 ET": the day is left out when it is the day the surges began. */
export function surgeMoment(iso: string, sameDayAs?: string): string {
  const day = formatDayET(iso);
  return sameDayAs && formatDayET(sameDayAs) === day ? formatET(iso) : `${day} ${formatET(iso)}`;
}
