import { describe, expect, it } from "vitest";
import type { MissedDecisionCase } from "@/lib/api";
import { isMissed, type QueueRow, toMissedRows, withMissed } from "./queueModel";

const pressure: MissedDecisionCase = {
  decision_case_id: "DC-D3-PS17-PRESSURE",
  title: "Hold Cedarfall zone pressure above the state floor",
  domain: "water",
  effective_decide_by_utc: "2024-09-27T05:59:00Z",
};

const closed = (id: string, at: string) => ({ id, decideByMs: Date.parse(at) }) as unknown as QueueRow;

describe("Closed rows for deadlines that passed with no proposal (V4-10b)", () => {
  it("follow the Utility, Owner and find filters", () => {
    expect(toMissedRows([pressure], "all", "all", "")).toHaveLength(1);
    expect(toMissedRows([pressure], "electric", "all", "")).toHaveLength(0);
    expect(toMissedRows([pressure], "all", "command", "")).toHaveLength(0);
    expect(toMissedRows([pressure], "all", "all", "cedarfall")).toHaveLength(1);
    expect(toMissedRows([pressure], "all", "all", "fuel")).toHaveLength(0);
  });

  it("sit in deadline order among the closed decisions, after them for other sorts", () => {
    const rows = [closed("a", "2024-09-27T01:59:00Z"), closed("b", "2024-09-27T10:29:00Z")];
    const missed = toMissedRows([pressure], "all", "all", "");
    expect(withMissed(rows, missed, true, false).map((r) => r.id)).toEqual([
      "a",
      "missed:DC-D3-PS17-PRESSURE",
      "b",
    ]);
    expect(withMissed([...rows].reverse(), missed, true, true).map((r) => r.id)).toEqual([
      "b",
      "missed:DC-D3-PS17-PRESSURE",
      "a",
    ]);
    const other = withMissed(rows, missed, false, false);
    expect(other.map((r) => isMissed(r))).toEqual([false, false, true]);
  });
});
