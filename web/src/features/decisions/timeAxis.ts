import { formatDayET, formatET, formatZ } from "@/lib/time";

const MIN = 60_000;
const STEPS_MIN = [30, 60, 120, 180, 360, 720, 1440] as const;

export interface Domain {
  start: number;
  end: number;
}

export const position = (d: Domain, t: number): number => ((t - d.start) / (d.end - d.start)) * 100;

export const MAX_TICKS = 4;

/** Whole-hour (Z) ticks, with a step chosen so no more than four fit: ET and UTC labels need about 56 px each.
 * When the axis crosses midnight ET, the first tick and each tick on a new ET day carry the day ("Sep 27 08:00"). */
export function ticks(d: Domain): { ms: number; z: string; et: string }[] {
  const spanMin = (d.end - d.start) / MIN;
  const crossesMidnight =
    formatDayET(new Date(d.start).toISOString()) !== formatDayET(new Date(d.end).toISOString());
  const step = (STEPS_MIN.find((s) => spanMin / s < MAX_TICKS) ?? 1440) * MIN;
  const out: { ms: number; z: string; et: string }[] = [];
  for (let t = Math.ceil(d.start / step) * step; t <= d.end; t += step) {
    const iso = new Date(t).toISOString();
    const time = formatET(iso).replace(" ET", "");
    const day = formatDayET(iso);
    const newDay =
      out.length === 0 || formatDayET(new Date(out[out.length - 1]?.ms ?? t).toISOString()) !== day;
    out.push({ ms: t, z: formatZ(iso), et: crossesMidnight && newDay ? `${day} ${time}` : time });
  }
  return out;
}

/**
 * The axis covers the decide-by range to the end of the consequence range. "Now" is included when it is within
 * twelve hours before the decide-by range; further back it is pinned to the left edge and flagged.
 */
export function domainFor(
  nowMs: number,
  decideP10: number,
  consequenceP90: number,
): { domain: Domain; nowOutside: boolean } {
  const lead = 12 * 60 * MIN;
  const startCore = Math.min(decideP10, nowMs >= decideP10 - lead ? nowMs : decideP10);
  const pad = Math.max(15 * MIN, (consequenceP90 - startCore) * 0.04);
  return {
    domain: { start: startCore - pad, end: consequenceP90 + pad },
    nowOutside: nowMs < decideP10 - lead,
  };
}
