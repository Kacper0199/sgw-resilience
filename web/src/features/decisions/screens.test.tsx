import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ME_KEY } from "@/auth/useSession";
import { TooltipProvider } from "@/components/ui/tooltip";
import { api, type Me, setUnauthorizedHandler } from "@/lib/api";
import { mockState, resetMock, runStory } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { ApprovalTab } from "./ApprovalTab";
import { buildChain } from "./chain";
import { resetClockShifts } from "./clockShifts";
import { Inspector } from "./Inspector";
import { ADVISORY_TIME, advanceStory, storyCards, summaryOf } from "./mocks/story";
import { PathTab } from "./PathTab";
import { observeVersions, resetVoided } from "./voidedApprovals";
import { Waterfall } from "./Waterfall";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  runStory.start("N");
  resetClockShifts();
  resetVoided();
});
afterEach(() => {
  server.resetHandlers();
  setUnauthorizedHandler(null);
});

vi.mock("@/features/map/MapContainer", () => ({ default: () => null }));

const wrap = (me: Me | null, ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (me) qc.setQueryData(ME_KEY, me);
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TooltipProvider>{ui}</TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return qc;
};

const itemsAt = (adv: "N" | "N+1") => storyCards(adv).map((card) => ({ summary: summaryOf(card), card }));

describe("Waterfall", () => {
  it("draws Now, the range and the lead time on an ET and Z axis", async () => {
    const card = storyCards("N+1")[0];
    if (!card) throw new Error("fixture");
    const data = await (async () => {
      const c = card.case.clock;
      return {
        decision_case_id: card.decision_case_id,
        consequence_utc: c.consequence_utc,
        consequence_range_utc: [c.consequence_p10_utc, c.consequence_p90_utc] as [string, string],
        consequence_basis: c.consequence_basis,
        action_lead_time_min: c.action_lead_time_min,
        lead_time_basis: c.lead_time_basis,
        decide_by_utc: c.decide_by_utc,
        effective_decide_by_utc: card.effective_decide_by_utc,
        bound_by_case_id: null,
      };
    })();
    render(<Waterfall data={data} now={ADVISORY_TIME["N+1"]} />);
    expect(screen.getByTestId("waterfall-now")).toBeInTheDocument();
    expect(screen.getByText("2 h 30 m")).toBeInTheDocument();
    expect(screen.getByText(/Now .*15:25Z/)).toBeInTheDocument();
    expect(screen.getByText(/ET \(UTC\)/)).toBeInTheDocument();
  });
});

describe("Path tab", () => {
  const select = () => {};
  it("keeps the link ink while slack is positive and turns it red only when negative", () => {
    const ok = buildChain(itemsAt("N+1"), "PRP-PS17-FDR2207-PRIO", ADVISORY_TIME["N+1"]);
    const { unmount } = render(
      <MemoryRouter>
        <TooltipProvider>
          <PathTab
            chain={ok}
            selectedId="PRP-PS17-FDR2207-PRIO"
            now={ADVISORY_TIME["N+1"]}
            onSelect={select}
          />
        </TooltipProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("chain-link")).toHaveAttribute("data-negative", "false");
    expect(screen.getByText(/7 h 4 m to spare/)).toBeInTheDocument();
    unmount();
    const late = buildChain(itemsAt("N+1"), "PRP-PS17-FDR2207-PRIO", "2024-09-26T23:30:00Z");
    render(
      <MemoryRouter>
        <TooltipProvider>
          <PathTab
            chain={late}
            selectedId="PRP-PS17-FDR2207-PRIO"
            now="2024-09-26T23:30:00Z"
            onSelect={select}
          />
        </TooltipProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("chain-link")).toHaveAttribute("data-negative", "true");
    expect(screen.getByText(/short by/)).toBeInTheDocument();
  });

  it("draws one link per prerequisite and reddens only the one without slack", () => {
    const items = itemsAt("N+1").map((i) =>
      i.summary.proposal_id === "PRP-PS17-FDR2207-PRIO" && i.card
        ? {
            ...i,
            card: {
              ...i.card,
              case: { ...i.card.case, prerequisite_ids: ["DC-D2-CREWS-AIK", "DC-D1-MUTUAL-AID"] },
            },
          }
        : i,
    );
    const now = "2024-09-26T23:00:00Z";
    const chain = buildChain(items, "PRP-PS17-FDR2207-PRIO", now);
    render(
      <MemoryRouter>
        <TooltipProvider>
          <PathTab chain={chain} selectedId="PRP-PS17-FDR2207-PRIO" now={now} onSelect={select} />
        </TooltipProvider>
      </MemoryRouter>,
    );
    const links = screen.getAllByTestId("chain-link");
    expect(links).toHaveLength(2);
    expect(links.map((l) => l.getAttribute("data-negative")).sort()).toEqual(["false", "true"]);
  });

  it("selects the other case from Blocks and Blocked by", () => {
    const chain = buildChain(itemsAt("N+1"), "PRP-PS17-FDR2207-PRIO", ADVISORY_TIME["N+1"]);
    const picked: string[] = [];
    render(
      <MemoryRouter>
        <TooltipProvider>
          <PathTab
            chain={chain}
            selectedId="PRP-PS17-FDR2207-PRIO"
            now={ADVISORY_TIME["N+1"]}
            onSelect={(id) => picked.push(id)}
          />
        </TooltipProvider>
      </MemoryRouter>,
    );
    const blockedBy = screen.getByText("Depends on", { exact: true }).parentElement as HTMLElement;
    fireEvent.click(within(blockedBy).getByRole("button"));
    expect(picked).toEqual(["PRP-CREW-AIK-0926A"]);
  });
});

describe("Approval tab", () => {
  it("opens with whose turn it is, then shows the signed row with person, time and version", async () => {
    const me = await api.login("log_01", "demo");
    const crews = mockState.cards.find((c) => c.proposal_id === "PRP-CREW-AIK-0926A");
    if (!crews) throw new Error("fixture");
    wrap(me, <ApprovalTab card={crews} />);
    expect(screen.getByTestId("approval-head")).toHaveTextContent("Waiting for Logistics (you)");
    const rows = screen.getAllByTestId("signature-row");
    expect(rows[0]).toHaveTextContent("Incident Commander");
    expect(rows[0]).toHaveTextContent("09:12Z");
    expect(rows[0]).toHaveTextContent("v1");
  });

  it("strikes the voided signature and shows the version banner after N+1", async () => {
    const me = await api.login("ic_01", "demo");
    observeVersions(mockState.cards.map((card) => ({ summary: summaryOf(card), card })));
    advanceStory("N+1", { cards: mockState.cards, scenario: { scenario_time: "" }, emit: () => {} });
    observeVersions(mockState.cards.map((card) => ({ summary: summaryOf(card), card })));
    wrap(
      me,
      <Inspector
        id="PRP-CREW-AIK-0926A"
        now={ADVISORY_TIME["N+1"]}
        tab="signatures"
        onTab={() => {}}
        onClose={() => {}}
      />,
    );
    expect(await screen.findByTestId("void-banner")).toHaveTextContent(
      "Version 2 replaced an earlier version",
    );
    expect(screen.getByTestId("void-banner")).toHaveTextContent(
      "What changed: Crews at STG-AIK-SANDHILL-YARD",
    );
    const voided = await screen.findByTestId("voided-row");
    expect(voided).toHaveTextContent("No longer valid as of v2");
    expect(voided.querySelector(".line-through")).not.toBeNull();
  });
});

describe("break-glass", () => {
  it("is a secondary text action that needs a reason and names the co-sign window", async () => {
    const me = await api.login("ic_01", "demo");
    wrap(
      me,
      <Inspector
        id="PRP-PS17-FDR2207-PRIO"
        now={ADVISORY_TIME.N}
        tab="deadline"
        onTab={() => {}}
        onClose={() => {}}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Approve alone…" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("within 24 hours");
    const go = within(dialog).getByRole("button", { name: /^Approve alone$/ });
    expect(go).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Why is this an emergency?"), {
      target: { value: "Generator failed at PS-17" },
    });
    expect(go).toBeEnabled();
    fireEvent.click(go);
    await waitFor(() =>
      expect(
        mockState.cards.find((c) => c.proposal_id === "PRP-PS17-FDR2207-PRIO")?.break_glass?.reason,
      ).toBe("Generator failed at PS-17"),
    );
  });

  it("is not offered to other functions", async () => {
    const me = await api.login("wtr_lead_01", "demo");
    wrap(
      me,
      <Inspector
        id="PRP-PS17-FDR2207-PRIO"
        now={ADVISORY_TIME.N}
        tab="deadline"
        onTab={() => {}}
        onClose={() => {}}
      />,
    );
    await screen.findByRole("button", { name: /^Sign as / });
    expect(screen.queryByRole("button", { name: "Approve alone…" })).not.toBeInTheDocument();
  });
});

describe("L8: co-sign asks for the password like any signature", () => {
  it("opens the step-up prompt, then records the co-signature", async () => {
    const ic = await api.login("ic_01", "demo");
    const card = mockState.cards.find((c) => c.proposal_id === "PRP-PS17-FDR2207-PRIO");
    if (!card) throw new Error("fixture");
    card.state = "approved";
    card.break_glass = {
      proposal_id: card.proposal_id,
      ic_id: ic.user_id,
      reason: "Generator failed",
      used_at_utc: ADVISORY_TIME.N,
      cosign_due_utc: "2024-09-27T09:30:00Z",
      cosigned_by: null,
      cosigned_at_utc: null,
      flagged_for_after_action: true,
    };
    const me = await api.login("wtr_lead_01", "demo");
    mockState.stepUpUntil = 0;
    wrap(
      me,
      <Inspector
        id={card.proposal_id}
        now={ADVISORY_TIME.N}
        tab="signatures"
        onTab={() => {}}
        onClose={() => {}}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Co-sign as Water operations/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Co-sign" }));
    const field = await within(dialog).findByLabelText("Enter your password to sign");
    fireEvent.change(field, { target: { value: "demo" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign" }));
    await waitFor(() => expect(card.break_glass?.cosigned_by).toBe("wtr_lead_01"));
  });
});

describe("Inspector tabs", () => {
  it("shows the CE breakdown and attached records on the deadline tab of the priority card", async () => {
    const me = await api.login("ic_01", "demo");
    wrap(
      me,
      <Inspector
        id="PRP-PS17-FDR2207-PRIO"
        now={ADVISORY_TIME.N}
        tab="deadline"
        onTab={() => {}}
        onClose={() => {}}
      />,
    );
    expect(await screen.findByTestId("ce-breakdown")).toBeInTheDocument();
    expect(screen.getAllByTestId("evidence-item").length).toBeGreaterThanOrEqual(2);
  });

  it("shows the ledger timeline on the history tab", async () => {
    const me = await api.login("ic_01", "demo");
    wrap(
      me,
      <Inspector
        id="PRP-CREW-AIK-0926A"
        now={ADVISORY_TIME.N}
        tab="history"
        onTab={() => {}}
        onClose={() => {}}
      />,
    );
    const timeline = await screen.findByTestId("timeline");
    expect(timeline).toHaveTextContent("Signature recorded");
    expect(timeline).toHaveTextContent("Incident Commander");
  });
});
