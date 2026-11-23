import { describe, expect, it } from "vitest";
import type { ProposalCard } from "@/lib/api";
import { currentShift, describeShift } from "./clockShifts";
import { voidedOf } from "./voidedApprovals";

describe("a fresh browser reads moved deadlines and voided signatures from the server", () => {
  it("shows the server's move against the previous advisory without having watched it", () => {
    const shift = currentShift({}, "DC-FUEL", "2024-09-27T01:59:00Z", {
      advisory_label: "N+1",
      previous_advisory_label: "N",
      previous_effective_decide_by_utc: "2024-09-27T03:15:00Z",
      shift_min: -76,
    });
    expect(shift && describeShift(shift).text).toMatch(/^Earlier by 1 h 16 m, was /);
    expect(currentShift({}, "DC-FUEL", "2024-09-27T01:59:00Z", null)).toBeUndefined();
  });

  it("lists the signature the new version voided", () => {
    const card = {
      proposal_id: "PRP-CREWS",
      proposal_version: 2,
      voided_approvals: [
        {
          approver_id: "ic_01",
          function: "command",
          decision: "approve",
          at: "2024-09-26T09:05:00Z",
          proposal_version: 1,
          voided_by_version: 2,
          voided_at: "2024-09-26T15:05:00Z",
          reason: null,
        },
      ],
    } as unknown as ProposalCard;
    expect(voidedOf(card, [])).toEqual([
      { approver_id: "ic_01", function: "command", at: "2024-09-26T09:05:00Z", version: 1, voidedBy: 2 },
    ]);
    expect(voidedOf(card, voidedOf(card, []))).toHaveLength(1);
  });
});
