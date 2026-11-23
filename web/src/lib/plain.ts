import { FUNCTION_LABEL } from "@/auth/personas";
import type { ApprovalFunction } from "@/contracts/vocab.gen";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;
const etClock = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const etDay = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  day: "numeric",
  month: "short",
});

/**
 * Server sentences carry UTC stamps such as "27 Sep 03:59Z". Rewrites each into Eastern Time first:
 * "26 Sep 23:59 ET". A stamp without a day takes the day of `refIso` (default: now).
 */
export function etText(text: string, refIso?: string | null): string {
  const ref = refIso ? new Date(refIso) : new Date();
  const year = Number.isNaN(ref.getTime()) ? new Date().getUTCFullYear() : ref.getUTCFullYear();
  const dated = text.replace(
    /(?<!·\s|\()\b(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{2}):(\d{2})(?:Z\b| UTC\b)/g,
    (_m, d: string, mon: string, h: string, min: string) => {
      const at = new Date(
        Date.UTC(year, MONTHS.indexOf(mon as (typeof MONTHS)[number]), Number(d), Number(h), Number(min)),
      );
      return `${etDay.format(at)} ${etClock.format(at)} ET`;
    },
  );
  return dated.replace(/(?<!·\s|\()\b(\d{2}):(\d{2})(?:Z\b| UTC\b)/g, (_m, h: string, min: string) => {
    const at = new Date(ref);
    at.setUTCHours(Number(h), Number(min), 0, 0);
    return `${etClock.format(at)} ET`;
  });
}

const FUNCTION_ID = new RegExp(
  `\\b(${Object.keys(FUNCTION_LABEL)
    .filter((id) => id.includes("_"))
    .join("|")})\\b`,
  "g",
);

/** Function ids with an underscore ("water_operations") read as "water operations", capitalised at the start of a sentence. */
export function plainFunctions(text: string): string {
  return text.replace(FUNCTION_ID, (id, _g, offset: number) => {
    const label = FUNCTION_LABEL[id as ApprovalFunction];
    const startsSentence = offset === 0 || /[.!?]\s$/.test(text.slice(Math.max(0, offset - 2), offset));
    return startsSentence ? label : label.toLowerCase();
  });
}

const BASIS_NAME: Record<string, string> = {
  "water_twin.zone_drain_critical_node": "Water network model: how fast a zone loses pressure",
  "water_twin.ps17_pressure_floor": "Water network model: PS-17 pressure floor",
  "water_twin.ps17_tank_drain": "Water network model: PS-17 tank drain",
  "water_twin.zone_pressure": "Water network model: zone pressure",
  "water_twin.portable_generator_fuel": "Water network model: generator fuel",
  "water_twin.hospital_storage": "Water network model: hospital water storage",
  "water_twin.station_survival_mc": "Water network model: station survival",
  "lead_time.portable_generator_hookup": "Time to hook up a portable generator",
  "lead_time.crew_mobilise_and_stage": "Time to mobilize and stage crews",
  "lead_time.small_crew_staging": "Time to stage a few crews",
  "lead_time.mutual_aid_arrival": "Time for mutual aid to arrive",
  "lead_time.notice_issue": "Time to issue a notice",
  "lead_time.sitrep_review": "Time to review a situation report",
};

const BASIS_GROUP: Record<string, string> = {
  water_twin: "Water network model",
  lead_time: "Lead time",
  rule: "Rule",
  forecast: "Forecast model",
  outage_forecast: "Outage forecast",
};

const sentenceCase = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

/** A model or rule id in plain words ("water_twin.zone_pressure" becomes "Water network model: zone pressure"). */
export function plainBasisName(id: string): string {
  const known = BASIS_NAME[id];
  if (known) return known;
  if (id.startsWith("inject.")) return "Exercise script";
  const dot = id.indexOf(".");
  const group = dot === -1 ? "" : id.slice(0, dot);
  const rest = (dot === -1 ? id : id.slice(dot + 1)).replace(/[_.]+/g, " ");
  return group in BASIS_GROUP ? `${BASIS_GROUP[group]}: ${rest}` : sentenceCase(rest);
}

/** "claude-haiku-5-5" reads as "Claude Haiku 5.5"; "haiku" alone reads as "Haiku". */
export function modelName(id: string): string {
  const m = /^(?:claude-)?(haiku|sonnet|opus|fable)(?:-(\d+)(?:-(\d+))?)?(?:-\d{8})?$/i.exec(id.trim());
  if (!m) return sentenceCase(id.replace(/[_-]+/g, " "));
  const family = sentenceCase((m[1] ?? "").toLowerCase());
  const version = m[2] ? ` ${m[2]}${m[3] ? `.${m[3]}` : ""}` : "";
  return `${/^claude-/i.test(id) ? "Claude " : ""}${family}${version}`;
}
