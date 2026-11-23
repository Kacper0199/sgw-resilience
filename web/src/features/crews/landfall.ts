import { usePhase } from "@/lib/PhaseProvider";

/** Before landfall no field photos exist yet; without a known scenario clock (tests) the queue shows as is. */
export function useBeforeLandfall(): boolean {
  const phase = usePhase();
  return phase.now !== null && phase.phase === "before_landfall";
}
