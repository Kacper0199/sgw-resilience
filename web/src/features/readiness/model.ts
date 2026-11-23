import type { ReadinessItem, ReadinessStatus } from "./types";

export const GROUPS: { status: ReadinessStatus; title: string }[] = [
  { status: "gap", title: "Not ready" },
  { status: "unknown", title: "No record" },
  { status: "ready", title: "Ready" },
  { status: "waived", title: "Waived" },
];

const byDue = (a: ReadinessItem, b: ReadinessItem) =>
  (a.due_utc ? Date.parse(a.due_utc) : Number.POSITIVE_INFINITY) -
  (b.due_utc ? Date.parse(b.due_utc) : Number.POSITIVE_INFINITY);

export const grouped = (items: ReadinessItem[]): Record<ReadinessStatus, ReadinessItem[]> => ({
  gap: items.filter((i) => i.status === "gap").sort(byDue),
  unknown: items.filter((i) => i.status === "unknown").sort(byDue),
  ready: items.filter((i) => i.status === "ready").sort(byDue),
  waived: items.filter((i) => i.status === "waived").sort(byDue),
});

/** Equipment ids named in a check's title, such as "GEN-PS52-DEERWATER" or "FDR-AIK-2207". */
export const assetIdsIn = (title: string): string[] => [
  ...new Set(title.match(/\b[A-Z]{2,5}(?:-[A-Z0-9]+){1,}\b/g) ?? []),
];

export const isOverdue = (item: ReadinessItem, now: string): boolean =>
  item.status !== "ready" &&
  item.status !== "waived" &&
  item.due_utc !== null &&
  Date.parse(item.due_utc) < Date.parse(now);

/** Whole days between the scenario clock and a due date, for lead times counted in weeks. */
export function dueText(dueIso: string, nowIso: string): string {
  const hours = Math.round((Date.parse(dueIso) - Date.parse(nowIso)) / 3_600_000);
  const abs = Math.abs(hours);
  const span = abs >= 48 ? `${Math.round(abs / 24)} d` : abs === 0 ? "" : `${abs} h`;
  if (hours === 0) return "now";
  return hours > 0 ? `in ${span}` : `${span} overdue`;
}

/** The pre-season review the API read the checks at; checks are judged there, never against the replay clock. */
export const reviewTime = (items: readonly ReadinessItem[]): string | null =>
  items.find((i) => i.evaluated_at_utc)?.evaluated_at_utc ?? null;

/** "6 May 2024" in Eastern time. */
export function calendarDay(iso: string): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "America/New_York",
    day: "numeric",
    month: "short",
    year: "numeric",
  }).formatToParts(new Date(iso));
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("day")} ${get("month")} ${get("year")}`;
}
