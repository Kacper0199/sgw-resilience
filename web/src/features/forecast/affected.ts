import type { NoRegretVerdict } from "@/contracts/vocab.gen";
import { TIMING_LABEL } from "../decisions/ui";
import type { PlanDiffAction } from "./types";

export interface AffectedDecisions {
  /** Rows of the plan table whose share of scenarios changed since the previous advisory. */
  count: number;
  /** All rows of the plan table. */
  total: number;
  urgent: boolean;
  line: string;
}

const ORDER: readonly NoRegretVerdict[] = ["act_now", "decide_now", "wait_for_next_advisory", "n/a"];
const URGENT: ReadonlySet<NoRegretVerdict> = new Set(["act_now", "decide_now"]);

export const shareChanged = (a: PlanDiffAction): boolean => a.share_ppm[0] !== a.share_ppm[1];

/** The plan steps whose share changed, counted as the table lists them, worded with the Timing Decisions shows. */
export function affectedDecisions(actions: readonly PlanDiffAction[]): AffectedDecisions {
  const changed = actions.filter(shareChanged);
  const timings = changed.map((a) => a.timing ?? "n/a");
  const open = new Set(changed.map((a) => a.proposal_id).filter((id): id is string => !!id)).size;
  const parts = ORDER.map((t) => [t, timings.filter((v) => v === t).length] as const)
    .filter(([, n]) => n > 0)
    .map(([t, n]) => `${n} ${TIMING_LABEL[t].toLowerCase()}`);
  if (open > 0) parts.push(`${open} open decision${open === 1 ? "" : "s"}`);
  return {
    count: changed.length,
    total: actions.length,
    urgent: timings.some((t) => URGENT.has(t)),
    line: changed.length === 0 ? "No plan step changed" : parts.join(", "),
  };
}
