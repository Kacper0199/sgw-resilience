import { describe, expect, it } from "vitest";
import { affectedDecisions } from "./affected";
import type { PlanDiffAction } from "./types";

const action = (over: Partial<PlanDiffAction>): PlanDiffAction => ({
  action_id: "ACT",
  label: "Action",
  decision_case_ids: ["DC"],
  share_ppm: [325_000, 925_000],
  crossed_act_now_threshold: true,
  rule: "rule",
  ...over,
});

describe("plan steps changed", () => {
  it("counts the rows of the table whose share changed, so the key number matches the table", () => {
    const summary = affectedDecisions([
      action({ action_id: "A", proposal_id: "PRP-1", timing: "decide_now" }),
      action({ action_id: "B", proposal_id: "PRP-2", timing: "decide_now" }),
      action({ action_id: "C", proposal_id: null, timing: "decide_now" }),
      action({ action_id: "D", timing: "decide_now" }),
    ]);
    expect(summary).toEqual({
      count: 4,
      total: 4,
      urgent: true,
      line: "4 before next advisory, 2 open decisions",
    });
  });

  it("leaves out steps whose share did not move and words each Timing", () => {
    const summary = affectedDecisions([
      action({ action_id: "A", proposal_id: "PRP-1", timing: "act_now" }),
      action({ action_id: "B", proposal_id: "PRP-1", timing: "act_now", share_ppm: [925_000, 925_000] }),
      action({ action_id: "C", proposal_id: "PRP-3", timing: "wait_for_next_advisory" }),
    ]);
    expect(summary).toEqual({
      count: 2,
      total: 3,
      urgent: true,
      line: "1 act now, 1 can wait, 2 open decisions",
    });
  });

  it("counts a new step as changed and is calm when nothing moved", () => {
    expect(affectedDecisions([action({ share_ppm: [null, 500_000], proposal_id: "PRP-1" })]).count).toBe(1);
    expect(affectedDecisions([action({ share_ppm: [500_000, 500_000], proposal_id: null })])).toEqual({
      count: 0,
      total: 1,
      urgent: false,
      line: "No plan step changed",
    });
  });
});
