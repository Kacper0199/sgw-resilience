import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { components } from "@/contracts/api.gen";
import type { ApprovalFunction } from "@/contracts/vocab.gen";
import { type Me, post, type ScenarioState } from "@/lib/api";
import { freshWorld } from "@/lib/world";
import { useOpsRestart } from "@/sse/OpsStreamProvider";
import { setScenario } from "@/sse/refresh";

const CLOCK_FUNCTIONS: ReadonlySet<ApprovalFunction> = new Set(["command", "operations"]);

/** Who may move the replay clock, the same rule as the API (command, operations or the presenter role). */
export const canMoveClock = (me: Pick<Me, "function" | "roles"> | null | undefined): boolean =>
  Boolean(me && (CLOCK_FUNCTIONS.has(me.function) || me.roles.includes("presenter")));

export type JumpDirection = "forward" | "back" | "here";

export const directionOf = (target: string, now: string | null): JumpDirection => {
  if (!now) return "forward";
  const d = Date.parse(target) - Date.parse(now);
  return d === 0 ? "here" : d > 0 ? "forward" : "back";
};

/** Seeks the replay clock, then refreshes everything on screen: every query and the ops stream. */
export function useScenarioJump() {
  const qc = useQueryClient();
  const restart = useOpsRestart();
  return useMutation({
    mutationFn: (scenarioTime: string) =>
      post<ScenarioState>("/api/scenario", { action: "seek", scenario_time: scenarioTime }),
    onSuccess: (state) => {
      qc.setQueryData(["scenario"], state);
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "scenario" && q.queryKey[0] !== "me" });
      restart();
    },
  });
}

export type ReplaySpeed = 1 | 60 | 900;
export type ReplayCommand =
  | { action: "play" }
  | { action: "pause" }
  | { action: "speed"; speed: ReplaySpeed };
export type DemoGotoResult = components["schemas"]["DemoGotoResult"];

/** Plays, pauses or sets the speed of the replay clock; the clock on screen follows the new speed. */
export function useReplayCommand() {
  const qc = useQueryClient();
  const restart = useOpsRestart();
  return useMutation({
    mutationFn: (cmd: ReplayCommand) => post<ScenarioState>("/api/scenario", cmd),
    onSuccess: (state) => {
      qc.setQueryData(["scenario"], state);
      restart();
    },
  });
}

/** Loads a demo moment's saved state (presenters, demo only), then refetches everything, the session included. */
export function useLoadMoment() {
  const qc = useQueryClient();
  const restart = useOpsRestart();
  return useMutation({
    mutationFn: (bookmark: string) => post<DemoGotoResult>("/api/demo/goto", { bookmark }),
    onSuccess: () => {
      freshWorld(qc);
      restart();
    },
  });
}

export type ScenarioLoadResult = components["schemas"]["ScenarioLoadResult"];
export type LoadableScenario = components["schemas"]["ScenarioLoadRequest"]["scenario"];

/** Loads another scenario for everyone (presenters, demo only), then refetches everything, the session included. */
export function useLoadScenario() {
  const qc = useQueryClient();
  const restart = useOpsRestart();
  return useMutation({
    mutationFn: (scenario: LoadableScenario) => post<ScenarioLoadResult>("/api/demo/scenario", { scenario }),
    onSuccess: (result) => {
      setScenario(qc, result);
      freshWorld(qc);
      restart();
    },
  });
}
