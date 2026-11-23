import { SOON_MINUTES } from "./thresholds";

const ET = "America/New_York";

const etParts = new Intl.DateTimeFormat("en-US", {
  timeZone: ET,
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const etDay = new Intl.DateTimeFormat("en-US", { timeZone: ET, day: "numeric", month: "short" });
const zDay = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", day: "numeric", month: "short" });

const pad = (n: number) => String(n).padStart(2, "0");

export function formatZ(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}Z`;
}

export function formatET(iso: string): string {
  return `${etParts.format(new Date(iso))} ET`;
}

export function formatDayZ(iso: string): string {
  return zDay.format(new Date(iso));
}

export function formatDayET(iso: string): string {
  return etDay.format(new Date(iso));
}

const etDate = new Intl.DateTimeFormat("en-CA", {
  timeZone: ET,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** An ET time with its day when that day is not the scenario clock's own: "15:45 ET" or "28 Sep 15:45 ET". */
export function formatETOn(iso: string, nowIso: string | null): string {
  const sameDay = nowIso !== null && etDate.format(new Date(iso)) === etDate.format(new Date(nowIso));
  return sameDay ? formatET(iso) : `${formatDayET(iso)} ${formatET(iso)}`;
}

/** A past or far time with its day, for example "Sep 26 23:29 ET": never read as a time still to come. */
export const formatDayTimeET = (iso: string): string => `${formatDayET(iso)} ${formatET(iso)}`;

/** The one time format of the app: ET first, UTC second, for example "23:29 ET (03:29Z)". */
export function formatEtZ(iso: string): string {
  return `${formatET(iso)} (${formatZ(iso)})`;
}

export const formatAbsolute = formatEtZ;

/** The time a record was written: the Eastern day and time first, then UTC. */
export function formatRecorded(iso: string): string {
  return `${formatDayET(iso)}, ${formatEtZ(iso)}`;
}

export function minutesUntil(targetIso: string, nowIso: string): number {
  return Math.round((Date.parse(targetIso) - Date.parse(nowIso)) / 60_000);
}

/** Hours up to two days ("47 h 30 m"), then days and hours ("3 d 12 h"). */
export function formatDuration(totalMinutes: number): string {
  const abs = Math.abs(totalMinutes);
  const h = Math.floor(abs / 60);
  if (h >= 48) {
    const d = Math.floor(h / 24);
    return h % 24 === 0 ? `${d} d` : `${d} d ${h % 24} h`;
  }
  const m = abs % 60;
  if (h === 0) return `${m} m`;
  if (m === 0) return `${h} h`;
  return `${h} h ${m} m`;
}

export function formatRelative(targetIso: string, nowIso: string): string {
  const min = minutesUntil(targetIso, nowIso);
  if (min === 0) return "now";
  return min > 0 ? `in ${formatDuration(min)}` : `${formatDuration(min)} ago`;
}

export type Urgency = "normal" | "soon" | "missed";

export function urgencyOf(targetIso: string, nowIso: string): Urgency {
  const min = minutesUntil(targetIso, nowIso);
  if (min < 0) return "missed";
  return min < SOON_MINUTES ? "soon" : "normal";
}
