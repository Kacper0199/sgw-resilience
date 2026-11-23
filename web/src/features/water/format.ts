import type { WaterZone } from "./types";

const titleCase = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();

export { zoneName } from "@/lib/names";

/** The Decisions queue with this decision selected; the one link target every module uses for a decision. */

export const psi = (x10: number): string => `${(x10 / 10).toFixed(1)} psi`;

export const percentPpm = (ppm: number, digits = 1): string => `${(ppm / 10_000).toFixed(digits)}%`;

export const percentShare = (share: number, digits = 0): string => `${(share * 100).toFixed(digits)}%`;

export const FAULT_LABEL: Record<string, string> = {
  pump_trip: "Pump trip",
  drift_pressure: "Pressure sensor drift",
  stuck_level: "Stuck tank-level sensor",
  replay_pressure: "Old pressure readings resent",
  replay_level: "Old tank-level readings resent",
  leak: "Hidden leak (tank stays full)",
};

export const ANOMALY_LABEL: Record<string, string> = {
  pressure_loss: "Pressure loss",
  demand_increase: "Demand increase",
  pump_trip: "Pump trip",
  pressure_level_inconsistent: "Pressure and tank level disagree",
  replayed_sequence: "Old readings resent",
  frozen_reading: "Frozen reading",
};

export const anomalyLabel = (cls: string): string =>
  ANOMALY_LABEL[cls] ?? titleCase(cls.replaceAll("_", " "));

const CAVEAT: [RegExp, string][] = [
  [
    /replayed_sequence needs 8 equal readings/i,
    "A sensor that repeats the same steady reading for hours can be missed. A shorter window would raise false alarms.",
  ],
  [
    /leak while the tank is held full/i,
    "A leak while the pump keeps the tank full changes neither pressure nor level. Only flow metering would show it.",
  ],
  [
    /pairwise A8 alarms/i,
    "When two sensors disagree, the checks can't tell which one is wrong unless a third sensor is present.",
  ],
];

/** A test caveat in plain words; the server's engineering wording ("replayed_sequence needs 8 equal readings…") stays out of the screen. */
export function plainCaveat(text: string): string {
  const known = CAVEAT.find(([re]) => re.test(text));
  if (known) return known[1];
  const first = text.split(/(?<=[.!?])\s+/)[0] ?? text;
  const clean = first.replaceAll("_", " ");
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

const SPLIT_LABEL: Record<string, string> = { dev: "development", test: "held-out test", train: "training" };

export const splitLabel = (split: string): string => SPLIT_LABEL[split] ?? split;

const GENERATOR_TROUBLE: Record<string, string> = {
  failed_run: "Generator failed",
  out_of_fuel: "Generator out of fuel",
};

/** Backup power of a pump station in plain words: a running generator, a fault it reported, its own standby generator, a portable generator ordered by an executed decision but not running yet, or none. */
export function backupPower(
  z: Pick<WaterZone, "on_backup_power" | "onsite_generator_id" | "generator_state">,
  generatorOrdered = false,
): { label: string; warn: boolean } {
  if (z.on_backup_power) return { label: "On backup power", warn: false };
  const trouble = z.generator_state ? GENERATOR_TROUBLE[z.generator_state] : undefined;
  if (trouble) return { label: trouble, warn: true };
  if (z.onsite_generator_id) return { label: "Generator on site", warn: false };
  if (generatorOrdered) return { label: "Generator not running yet", warn: true };
  return { label: "No backup power", warn: true };
}

/** An executed decision that sends a portable generator to this pump station. */
export const generatorOrdered = (
  stationId: string,
  cards: readonly { state: string; params: Record<string, unknown> }[],
): boolean =>
  cards.some((c) => c.state === "executed" && c.params.station_id === stationId && !!c.params.generator_id);
