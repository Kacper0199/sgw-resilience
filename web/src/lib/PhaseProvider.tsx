import { createContext, type ReactNode, useContext, useMemo } from "react";
import { useScenario, useScenarioNow } from "@/sse/useScenarioNow";
import { BEFORE_LANDFALL, phaseInfo, type ScenarioPhaseInfo } from "./phase";

const PhaseContext = createContext<ScenarioPhaseInfo>(BEFORE_LANDFALL);

/** The storm phase at the scenario clock for every screen under it; without it a screen reads as before landfall. */
export function PhaseProvider({ children }: { children: ReactNode }) {
  const scenario = useScenario().data;
  const now = useScenarioNow();
  const value = useMemo(() => phaseInfo(scenario, now), [scenario, now]);
  return <PhaseContext.Provider value={value}>{children}</PhaseContext.Provider>;
}

export const PhaseValue = PhaseContext.Provider;

export const usePhase = (): ScenarioPhaseInfo => useContext(PhaseContext);
