import { isPack, SCENARIO_PACKS } from "@/lib/scenarios";
import { useScenario } from "@/sse/useScenarioNow";
import starters from "./starters.json";

export type StarterSet = "before_landfall" | "after_landfall";

const sets = starters as unknown as Record<StarterSet | "exercise", readonly string[]> & {
  polish: Record<string, string>;
};

/** Four questions per storm phase, offered on an empty chat. Before landfall the advisory clocks lead; from
 * landfall on there is no advisory to wait for, so the decision queue leads. Each AI starter is recorded at
 * every demo moment of its phase (`tests/unit/agent/copilot/test_demo_replay_coverage.py`); change the JSON only
 * together with a new recording. */
export const STARTERS_BY_PHASE: Record<StarterSet, readonly string[]> = {
  before_landfall: sets.before_landfall,
  after_landfall: sets.after_landfall,
};

export const STARTERS = STARTERS_BY_PHASE.before_landfall;

export function startersFor(phase: string | null | undefined): readonly string[] {
  return phase && phase !== "before_landfall" ? STARTERS_BY_PHASE.after_landfall : STARTERS;
}

/** A scripted exercise: plain questions its data can answer, recorded for the presenters at each of its
 * moments (`sgw.agent.copilot.demo.pack_matrix`). */
export const EXERCISE_STARTERS: readonly string[] = sets.exercise;

/** The same questions for a chat held in Polish (follow-up chips after a Polish question). */
export const inPolish = (questions: readonly string[]): readonly string[] =>
  questions.map((q) => sets.polish[q] ?? q);

export function useStarters(): readonly string[] {
  const data = useScenario().data;
  return isPack(data?.scenario) ? EXERCISE_STARTERS : startersFor(data?.phase);
}

export const PLACEHOLDER = "Ask about a decision, a procedure, or the water system";
export const SCOPE = "Helene, SGW service area";

export function useScope(): string {
  const scenario = useScenario().data?.scenario;
  return isPack(scenario) ? `${SCENARIO_PACKS[scenario].title} exercise` : SCOPE;
}
