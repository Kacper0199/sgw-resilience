import type { components } from "@/contracts/api.gen";

export type PhaseName = components["schemas"]["ScenarioPhase"]["phase"];
type PhaseSpan = components["schemas"]["ScenarioPhase"];

/** What the screens may present as current at the scenario clock, from the server's phase timeline. */
export interface ScenarioPhaseInfo {
  phase: PhaseName;
  now: string | null;
  /** The final advisory is out: no "next advisory" exists from here on. */
  advisoriesOver: boolean;
  finalAdvisoryUtc: string | null;
  /** The observed outage peak has passed: headlines show what was observed, the forecast moves to "forecast vs actual". */
  afterPeak: boolean;
}

export const BEFORE_LANDFALL: ScenarioPhaseInfo = {
  phase: "before_landfall",
  now: null,
  advisoriesOver: false,
  finalAdvisoryUtc: null,
  afterPeak: false,
};

const AFTER_PEAK: ReadonlySet<PhaseName> = new Set(["restoration", "recovery"]);

export function phaseAt(phases: readonly PhaseSpan[], now: string): PhaseName {
  const t = Date.parse(now);
  let current: PhaseName = phases[0]?.phase ?? "before_landfall";
  for (const span of phases) if (Date.parse(span.starts_utc) <= t) current = span.phase;
  return current;
}

export function phaseInfo(
  scenario: { phases?: PhaseSpan[]; final_advisory_utc?: string | null } | undefined,
  now: string | null,
): ScenarioPhaseInfo {
  if (!scenario || !now) return { ...BEFORE_LANDFALL, now };
  const phase = phaseAt(scenario.phases ?? [], now);
  const final = scenario.final_advisory_utc ?? null;
  return {
    phase,
    now,
    advisoriesOver: final !== null && Date.parse(final) <= Date.parse(now),
    finalAdvisoryUtc: final,
    afterPeak: AFTER_PEAK.has(phase),
  };
}

/** The forecast is history from the final advisory on, and once the observed outage peak has passed. */
export const forecastIsHistory = (phase: Pick<ScenarioPhaseInfo, "afterPeak" | "advisoriesOver">): boolean =>
  phase.afterPeak || phase.advisoriesOver;
