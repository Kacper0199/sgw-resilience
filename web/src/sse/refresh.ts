import type { Query, QueryClient } from "@tanstack/react-query";
import { api, type ScenarioState } from "@/lib/api";

/** Map reads named after one storm's advisories and times: fixed for a scenario, dropped when it changes. */
const STORM_READS: ReadonlySet<unknown> = new Set(["hazard", "risk"]);
const isStormRead = (q: Query) => STORM_READS.has(q.queryKey[0]);

/** Drops the previous storm's map reads as soon as another scenario is in the cache, before anything renders with it. */
export function watchScenario(qc: QueryClient): () => void {
  let current = qc.getQueryData<ScenarioState>(["scenario"])?.scenario;
  return qc.getQueryCache().subscribe((e) => {
    if (e.type !== "updated" || e.query.queryKey[0] !== "scenario" || e.query.queryKey.length !== 1) return;
    const next = (e.query.state.data as ScenarioState | undefined)?.scenario;
    if (next === undefined || next === current) return;
    if (current !== undefined) qc.removeQueries({ predicate: isStormRead });
    current = next;
  });
}

/** Shows the loaded scenario at once (its full state follows with the refresh). */
export function setScenario(qc: QueryClient, state: Pick<ScenarioState, "scenario" | "scenario_time">) {
  qc.setQueryData<ScenarioState>(["scenario"], (s) => (s ? { ...s, ...state } : s));
}

const isList = (q: Query) => q.queryKey[0] === "proposals" && q.queryKey.length === 1;

/**
 * Refetches everything after the server replaced its state (a loaded moment or scenario, a stream resync):
 * the scenario and the decision list first, then every other read except those of decisions that are gone
 * and the fixed storm reads.
 */
export async function refreshAll(qc: QueryClient): Promise<void> {
  const state = await api.scenario().catch(() => null);
  if (state) qc.setQueryData(["scenario"], state);
  const list = await qc
    .fetchQuery({ queryKey: ["proposals"], queryFn: api.proposals, staleTime: 0 })
    .catch(() => null);
  if (!list) return void qc.invalidateQueries({ predicate: (q) => !isStormRead(q) });
  const ids = new Set(list.map((p) => p.proposal_id));
  const gone = (q: Query) =>
    q.queryKey[0] === "proposals" && typeof q.queryKey[1] === "string" && !ids.has(q.queryKey[1]);
  void qc.invalidateQueries({
    predicate: (q) => !gone(q) && !isList(q) && !isStormRead(q) && q.queryKey[0] !== "scenario",
  });
}
