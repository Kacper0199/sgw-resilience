import { describe, expect, it } from "vitest";
import type { AuditEvent, ProposalCard } from "@/lib/api";
import { entriesFrom, systemActorName } from "./HistoryTab";
import { storyCards } from "./mocks/story";

const event = (kind: string, actor: string, at: string, actorType: "user" | "system" = "user"): AuditEvent =>
  ({
    stream: "global",
    seq: 1,
    occurred_at: at,
    actor_type: actorType,
    actor_id: actor,
    kind,
    subject: "PRP-CREW-AIK-0926A",
    payload_hash: "0".repeat(64),
    prev_hash: "0".repeat(64),
    hash: "0".repeat(64),
  }) as AuditEvent;

const base = (): ProposalCard => {
  const card = storyCards("N").find((c) => c.proposal_id === "PRP-CREW-AIK-0926A");
  if (!card) throw new Error("story card missing");
  return card;
};

const EVENTS = [
  event("proposal_created", "ops_dm_01", "2024-09-26T09:00:00Z"),
  event("approval_recorded", "ic_01", "2024-09-26T09:05:00Z"),
  event("proposal_revised", "system:clock-replanner", "2024-09-26T15:05:00Z", "system"),
];

describe("history", () => {
  it("says a signature was voided when a new advisory moved the deadline", () => {
    const card: ProposalCard = {
      ...base(),
      proposal_version: 2,
      approvals: [],
      voided_approvals: [
        {
          approver_id: "ic_01",
          function: "command",
          decision: "approve",
          at: "2026-11-20T21:38:20Z",
          proposal_version: 1,
          voided_by_version: 2,
          voided_at: "2026-11-20T21:38:21Z",
          reason: "advisory N+1 moved DC-D2-CREWS-AIK: effective decide-by ... ; signatures voided",
        },
      ],
    };
    const texts = entriesFrom(card, EVENTS).map((e) => e.text);
    expect(texts).toContain("Signature voided — a new advisory moved the deadline");
    expect(texts).not.toContain("Signature recorded");
  });

  it("keeps a later signature by the same person as recorded", () => {
    const card: ProposalCard = {
      ...base(),
      proposal_version: 2,
      voided_approvals: [
        {
          approver_id: "ic_01",
          function: "command",
          decision: "approve",
          at: "2026-11-20T21:38:20Z",
          proposal_version: 1,
          voided_by_version: 2,
          voided_at: "2026-11-20T21:38:21Z",
          reason: "withdrawn by the proposer",
        },
      ],
    };
    const resigned = [...EVENTS, event("approval_recorded", "ic_01", "2024-09-26T15:20:00Z")];
    const entries = entriesFrom(card, resigned);
    const signatures = entries.filter((e) => e.text.startsWith("Signature")).map((e) => e.text);
    expect(signatures).toEqual(["Signature recorded", "Signature voided — the decision changed"]);
  });

  it("leaves signatures of the current version as recorded", () => {
    const texts = entriesFrom({ ...base(), voided_approvals: [] }, EVENTS).map((e) => e.text);
    expect(texts).toContain("Signature recorded");
  });
});

describe("R34 history lines", () => {
  const at = "2024-09-26T15:05:00Z";
  const ev = (kind: string, seq: number, extra: Partial<AuditEvent> = {}): AuditEvent =>
    ({ ...event(kind, "ic_01", at), seq, ...extra }) as AuditEvent;

  it("names a send-back and a withdrawn signature with the reason given", () => {
    const entries = entriesFrom(base(), [
      ev("approval_recorded", 2, { decision: "reject", reason: "Add the affected county list" }),
      ev("approval_withdrawn", 3, { reason: "Wrong crew" }),
    ]);
    expect(entries.map((e) => [e.text, e.detail])).toEqual([
      ["Signature withdrawn", "Wrong crew"],
      ["Sent back", "Add the affected county list"],
    ]);
  });

  it("lists the same minute newest first, the go-ahead above what caused it", () => {
    const entries = entriesFrom(base(), [ev("execution_token_issued", 4), ev("break_glass_used", 5)]);
    expect(entries.map((e) => e.text)).toEqual(["Go-ahead issued", "Emergency approval used"]);
  });

  it("speaks the exercise rules plainly", () => {
    const entries = entriesFrom(base(), [
      { ...event("proposal_created", "system:rule:exercise_inject", at, "system"), seq: 1 } as AuditEvent,
    ]);
    expect(entries[0]?.who).toBe("SGW rules (automatic)");
  });
});

describe("system actors in plain words", () => {
  it("names rule and agent actors without ids", () => {
    expect(systemActorName("system:rule:zone_fuel_dispatch")).toBe("SGW rules (automatic)");
    expect(systemActorName("system:approval")).toBe("SGW, after the approvals");
    expect(systemActorName("system:agent:plan_etr_01")).toBe("ETR Specialist (AI draft)");
  });
});
