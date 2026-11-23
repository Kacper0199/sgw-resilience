import { describe, expect, it } from "vitest";
import type { ProposalCard } from "@/lib/api";
import { signaturesOf } from "./signatures";

const card = (bg: Partial<NonNullable<ProposalCard["break_glass"]>> | null): ProposalCard =>
  ({
    approvals: [],
    functions_required: ["command", "logistics"],
    break_glass: bg && {
      proposal_id: "PRP-1",
      ic_id: "ic_01",
      reason: "Roads close at dusk",
      used_at_utc: "2024-09-26T15:05:00Z",
      cosign_due_utc: "2024-09-27T15:05:00Z",
      cosigned_by: null,
      cosigned_at_utc: null,
      flagged_for_after_action: true,
      ...bg,
    },
  }) as unknown as ProposalCard;

describe("signatures of an emergency approval", () => {
  it("counts Command at the time it approved alone", () => {
    expect(signaturesOf(card({}))).toEqual([
      { function: "command", approver_id: "ic_01", at: "2024-09-26T15:05:00Z" },
    ]);
  });

  it("counts the co-sign for the co-signer's team", () => {
    const signed = signaturesOf(card({ cosigned_by: "log_01", cosigned_at_utc: "2024-09-26T16:00:00Z" }));
    expect(signed.map((s) => s.function)).toEqual(["command", "logistics"]);
  });

  it("is the recorded signatures without one", () => {
    expect(signaturesOf(card(null))).toEqual([]);
  });
});
