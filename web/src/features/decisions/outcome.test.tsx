import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ME_KEY } from "@/auth/useSession";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ProposalCard } from "@/lib/api";
import { freshCards, meFor } from "@/mocks/fixtures";
import { CaseHeader } from "./CaseHeader";
import { clockStatus } from "./DecisionClock";
import { closedLabel, decisionStatus } from "./ui";

const card = (over: Partial<ProposalCard>) =>
  ({
    state: "executed",
    approvals: [],
    effective_decide_by_utc: "2024-09-27T03:29:00Z",
    outcome: null,
    ...over,
  }) as ProposalCard;

describe("closed decisions read one outcome from the server", () => {
  it("names on time, late and missed", () => {
    expect(closedLabel(card({ state: "executed", outcome: "on_time" }))).toBe("On time");
    expect(closedLabel(card({ state: "approved", outcome: "late" }))).toBe("Late");
    expect(closedLabel(card({ state: "expired", outcome: "missed" }))).toBe("Missed");
  });

  it("never calls an unsigned expired decision decided", () => {
    expect(closedLabel(card({ state: "expired" }))).toBe("Missed");
    expect(clockStatus(card({ state: "expired", outcome: "missed" }), "2024-09-30T12:00:00Z")).toEqual({
      status: "missed",
      label: "Missed",
    });
  });

  it("keeps sent back and withdrawn as they are", () => {
    expect(closedLabel(card({ state: "rejected" }))).toBe("Sent back");
    expect(closedLabel(card({ state: "withdrawn" }))).toBe("Withdrawn");
  });

  it("marks a decision signed on time as met and a late one as missed", () => {
    expect(clockStatus(card({ outcome: "on_time" }), "2024-09-30T12:00:00Z")).toEqual({
      status: "met",
      label: "On time",
    });
    expect(clockStatus(card({ outcome: "late" }), "2024-09-30T12:00:00Z").label).toBe("Late");
  });
});

describe("a closed decision shows its outcome, never a severity that moves with the zone", () => {
  it("reads the outcome where open decisions read severity", () => {
    expect(decisionStatus(card({ state: "executed", outcome: "on_time", severity: "severe" }))).toEqual({
      level: "normal",
      label: "On time",
    });
    expect(decisionStatus(card({ state: "approved", outcome: "late", severity: "normal" }))).toEqual({
      level: "elevated",
      label: "Late",
    });
    expect(decisionStatus(card({ state: "expired", outcome: "missed", severity: "severe" }))).toEqual({
      level: "critical",
      label: "Missed",
    });
    expect(decisionStatus(card({ state: "withdrawn", severity: "severe" }))).toEqual({
      level: "advisory",
      label: "Withdrawn",
    });
    expect(decisionStatus(card({ state: "in_review", severity: "elevated" }))).toEqual({
      level: "elevated",
      label: undefined,
    });
  });
});

describe("the case header of a closed decision", () => {
  it("shows the outcome and the deadline, never a countdown or Overdue", () => {
    const base = freshCards()[0];
    if (!base) throw new Error("fixture");
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(ME_KEY, meFor("ops_dm_01"));
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <TooltipProvider>
            <CaseHeader
              card={{
                ...base,
                state: "executed",
                outcome: "on_time",
                severity: "severe",
                case: {
                  ...base.case,
                  clock: { ...base.case.clock, consequence_utc: "2024-09-30T06:29:00Z" },
                },
                decided_at_utc: "2024-09-26T15:05:00Z",
                effective_decide_by_utc: "2024-09-27T03:29:00Z",
              }}
              now="2024-09-30T12:00:00Z"
            />
          </TooltipProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const header = screen.getByTestId("case-header");
    expect(header.textContent).toContain("On time");
    expect(header.textContent).toContain("Sep 26 23:29 ET");
    expect(header.textContent).toContain("Sep 30 02:29 ET");
    expect(header.textContent).not.toMatch(/Overdue|ago|in \d|By the deadline|Severe/);
  });
});
