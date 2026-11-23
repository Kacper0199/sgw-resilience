import { FUNCTION_LABEL } from "@/auth/personas";
import type { ApprovalFunction } from "@/contracts/vocab.gen";
import { plainIds } from "@/lib/names";
import { formatDayET, formatET, formatRelative } from "@/lib/time";
import type { EtrArea } from "./types";

export const when = (iso: string): string => `${formatDayET(iso)}, ${formatET(iso)}`;

export const count = (n: number): string => Math.round(n).toLocaleString("en-US");

export const percent = (ppm: number): string => `${Math.round(ppm / 10_000)}%`;

/** The share still out, rounded up until the area is restored, so it never reads as at the target first. */
export const stillOutText = ({ ppm, restored }: { ppm: number; restored: boolean }): string =>
  restored ? percent(ppm) : `${Math.ceil(ppm / 10_000)}%`;

export const functionList = (fns: readonly ApprovalFunction[]): string =>
  fns.map((f) => FUNCTION_LABEL[f]).join(" and ");

const pick = (times: readonly string[], f: (...n: number[]) => number): string =>
  new Date(f(...times.map((t) => Date.parse(t)))).toISOString();

export const earliest = (times: readonly string[]): string => pick(times, Math.min);
export const latest = (times: readonly string[]): string => pick(times, Math.max);

/** Position of a time on the shared axis from the earliest P10 to the latest P90 of the areas, in percent. */
export function axis(startIso: string, endIso: string) {
  const start = Date.parse(startIso);
  const span = Math.max(Date.parse(endIso) - start, 1);
  return (iso: string): number => Math.min(100, Math.max(0, ((Date.parse(iso) - start) / span) * 100));
}

type Outcome = NonNullable<EtrArea["outcome"]>;

const RESTORED: Partial<Record<Outcome, string>> = {
  restored_early: "early",
  restored_late: "late",
};

/** The P50 of an estimate against the scenario clock and the actuals: "in 9 h", "2 h ago", "Restored Sep 28,
 * 18:00 ET, early", "Late". Relative times count from the scenario clock, never from the issue time. */
export function p50Status(a: EtrArea, now: string): string {
  if (a.restored_utc && a.outcome?.startsWith("restored")) {
    const tag = a.outcome ? RESTORED[a.outcome] : undefined;
    return `Restored ${when(a.restored_utc)}${tag ? `, ${tag}` : ""}`;
  }
  if (a.outcome === "late") return `Late, latest likely ${formatRelative(a.p90_utc, now)}`;
  return formatRelative(a.p50_utc, now);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const title = (w: string) => w.charAt(0) + w.slice(1).toLowerCase();

/** The review text as the rest of the app reads: plain names, ET times, no case codes or method notes. */
export function plainReview(text: string, asOfIso: string): string {
  const year = new Date(asOfIso).getUTCFullYear();
  return plainIds(
    text
      .replace(/\s*Template text: [^.]*\.$/, "")
      .replace(/\s*\((?:D\d, )?decision case DC-[A-Z0-9-]+\)/g, "")
      .replace(
        /The audit chain verified before the review, checked through record \d+\./,
        "The audit log verified.",
      )
      .replace(
        /The audit chain did not verify \(checked through record \d+\)/,
        "The audit log did not verify",
      )
      .replace(/Break-glass uses:/g, "Emergency approvals:")
      .replace(/ by break-glass/g, " by emergency approval")
      .replace(/generator MGEN-([A-Z]+)-\d+/g, (_, n: string) => `generator ${title(n)}`)
      .replace(/fuel truck FTK-([A-Z]+)-(\d+)/g, (_, n: string, k: string) => `fuel truck ${title(n)} ${k}`)
      .replace(
        /\b(\d{1,2}) ([A-Z][a-z]{2}) (\d{2}):(\d{2})Z\b/g,
        (whole, d: string, m: string, h: string, min: string) => {
          const month = MONTHS.indexOf(m);
          if (month < 0) return whole;
          return when(new Date(Date.UTC(year, month, Number(d), Number(h), Number(min))).toISOString());
        },
      ),
  );
}
