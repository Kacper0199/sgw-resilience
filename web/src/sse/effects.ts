import type { QueryClient } from "@tanstack/react-query";
import { freshWorld } from "@/lib/world";
import type { Effect } from "./reducer";
import { refreshAll } from "./refresh";

/** Applies one invalidation. The queue list is invalidated by exact key; cards by id or by their decision case. */
export function applyEffect(qc: QueryClient, e: Effect): void {
  if (e.newDatabase) {
    freshWorld(qc);
    return;
  }
  if (e.caseId) {
    const caseId = e.caseId;
    void qc.invalidateQueries({
      queryKey: e.invalidate,
      predicate: (q) =>
        q.queryKey.length === 2 &&
        (q.state.data as { decision_case_id?: string } | undefined)?.decision_case_id === caseId,
    });
    return;
  }
  if (e.invalidate.length === 0) return void refreshAll(qc);
  void qc.invalidateQueries({ queryKey: e.invalidate, exact: e.exact });
}
