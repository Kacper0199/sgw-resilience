import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ME_KEY } from "@/auth/useSession";
import { TooltipProvider } from "@/components/ui/tooltip";
import { meFor } from "@/mocks/fixtures";
import { mockState, resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { ScorecardTab } from "../after-action/ScorecardTab";
import { axis, earliest, latest, percent, stillOutText, when } from "./format";
import fixture from "./mock/etr.json";
import { draftRunHandler, etrMock, mockSign, resetEtrMock } from "./mocks";
import { PublishedEtr } from "./PublishedEtr";
import { RestorationTab } from "./RestorationTab";
import { ReviewDraft } from "./ReviewDraft";
import type { EtrView } from "./types";
import { etrRefetch } from "./useEtr";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  resetEtrMock();
});
afterEach(() => server.resetHandlers());

function show(user: string, ui: React.ReactNode) {
  mockState.userId = user;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(ME_KEY, meFor(user));
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TooltipProvider>{ui}</TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const view = fixture as EtrView;

describe("Restoration times", () => {
  it("shows the whole service area and one row per area, latest first", async () => {
    show("exec_01", <RestorationTab />);
    const tab = await screen.findByTestId("restoration-tab");
    const whole = view.whole;
    expect(whole).not.toBeNull();
    expect(within(tab).getAllByText(when(whole?.p50_utc ?? "")).length).toBeGreaterThan(0);
    expect(within(tab).getByText(percent(whole?.still_out_ppm ?? 0))).toBeInTheDocument();
    expect(tab).toHaveTextContent(`customers at ${when(view.issued_at ?? "")}`);
    expect(screen.getByRole("columnheader", { name: /Out at estimate/ })).toBeInTheDocument();
    const rows = screen.getAllByTestId("etr-row");
    expect(rows).toHaveLength(view.areas.length);
    expect(within(rows[0]).getByText(view.areas[0].name)).toBeInTheDocument();
  });

  it("offers no controls to people outside the proposer list", async () => {
    show("ic_01", <RestorationTab />);
    await screen.findByTestId("restoration-tab");
    expect(screen.queryByRole("button", { name: /draft global etr|publish/i })).toBeNull();
    expect(screen.getByText("Not published yet.")).toBeInTheDocument();
  });

  it("lets the planner draft, waits for both signatures, then publishes", async () => {
    server.use(draftRunHandler);
    show("plan_etr_01", <RestorationTab />);
    fireEvent.click(await screen.findByRole("button", { name: "Draft global ETR" }));
    expect(await screen.findByText("Waiting for Command and Operations to sign.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view decision/i })).toHaveAttribute(
      "href",
      "/?d=PRP-ETR-MOCK0001",
    );
    mockSign("command");
    mockSign("operations");
    const publish = await screen.findByRole("button", { name: "Publish" }, { timeout: 8000 });
    fireEvent.click(publish);
    await waitFor(() => expect(etrMock.publication?.state).toBe("executed"));
    expect(await screen.findByText(/^Published /, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /draft global etr|publish/i })).toBeNull();
  }, 15000);

  it("reads a published ETR against actuals from the scenario clock and offers a revision", async () => {
    const whole = view.whole as NonNullable<EtrView["whole"]>;
    const [first, second] = view.areas;
    server.use(
      http.get("/api/etr", () =>
        HttpResponse.json({
          ...view,
          as_of: "2024-09-30T12:00:00Z",
          actual_as_of: "2024-09-30T12:00:00Z",
          can_draft: true,
          whole: {
            ...whole,
            p50_utc: "2024-10-02T00:54:00Z",
            actual_out_now: 168_598,
            actual_still_out_ppm: 105_082,
            outcome: "waiting",
          },
          areas: [
            { ...first, restored_utc: "2024-09-28T22:00:00Z", outcome: "restored_early" },
            { ...second, p90_utc: "2024-09-30T02:00:00Z", outcome: "late", restored_utc: null },
          ],
          publication: {
            ...(etrMock.publication ?? {}),
            proposal_id: "PRP-ETR-MOCK0001",
            run_id: "run-etr",
            run_status: "done",
            state: "executed",
            proposed_by: "plan_etr_01",
            estimate_id: whole.estimate_id,
            p50_utc: "2024-10-02T00:54:00Z",
            required_functions: ["command", "operations"],
            signed_functions: ["command", "operations"],
            created_at: "2024-09-28T17:40:00Z",
            published_at: "2024-09-28T18:00:00Z",
            published_by: "plan_etr_01",
            audit_seq: 7,
          },
          revision: {
            due: true,
            ahead_h: 36,
            reason: "Restoration runs 36 h ahead of the published estimate.",
            rule: "DOM 14.206 Rev K section 6.4.2",
            rule_name: "ETR revision rule",
            published_p50_utc: "2024-10-02T00:54:00Z",
            revised_p50_utc: "2024-09-30T12:54:00Z",
          },
        }),
      ),
    );
    show("plan_etr_01", <RestorationTab />);
    expect(await screen.findByRole("button", { name: "Revise global ETR" })).toBeInTheDocument();
    expect(screen.getByTestId("etr-revision")).toHaveTextContent("36 h ahead");
    expect(screen.getByTestId("etr-revision")).toHaveTextContent("ETR revision rule");
    expect(screen.getByTestId("etr-revision")).not.toHaveTextContent("DOM 14.206");
    const revised = screen.getByTestId("etr-revised");
    expect(revised).toHaveTextContent(when("2024-09-30T12:54:00Z"));
    expect(revised).toHaveTextContent(`Was ${when("2024-10-02T00:54:00Z")}`);
    const tab = screen.getByTestId("restoration-tab");
    expect(within(tab).getByText("in 36 h 54 m")).toBeInTheDocument();
    expect(within(tab).getByText("168,598 customers now")).toBeInTheDocument();
    const status = screen.getAllByTestId("etr-p50-status").map((n) => n.textContent);
    expect(status).toContain(`Restored ${when("2024-09-28T22:00:00Z")}, early`);
    expect(status).toContain("Late, latest likely 10 h ago");
    expect(screen.getByText(/Out now: outage feed at/)).toBeInTheDocument();
    expect(screen.queryByText(/P50/)).toBeNull();
  });

  it("never shows a share still out at or below the target for an area not yet restored", () => {
    expect(stillOutText({ ppm: 104_000, restored: false })).toBe("11%");
    expect(stillOutText({ ppm: 96_000, restored: true })).toBe("10%");
    expect(stillOutText({ ppm: 0, restored: false })).toBe("0%");
  });

  it("says when the first estimate comes before any is issued", async () => {
    server.use(
      http.get("/api/etr", () =>
        HttpResponse.json({
          ...view,
          whole: null,
          areas: [],
          issued_at: null,
          next_issue_utc: "2024-09-28T17:30:00Z",
        }),
      ),
    );
    show("plan_etr_01", <RestorationTab />);
    expect(await screen.findByText("No restoration estimate yet.")).toBeInTheDocument();
    expect(screen.getByText(`First estimate ${when("2024-09-28T17:30:00Z")}.`)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows an error, never an empty state, when the read fails", async () => {
    server.use(
      http.get("/api/etr", () => HttpResponse.json({ error: { code: "X", message: "x" } }, { status: 403 })),
    );
    show("plan_etr_01", <RestorationTab />);
    expect(await screen.findByText("Restoration times did not load.")).toBeInTheDocument();
  });

  it("polls fast while drafting or publishing and slowly while signatures are open", () => {
    const pub = { ...(etrMock.publication ?? {}), state: "proposed" } as EtrView["publication"];
    expect(etrRefetch({ ...view, drafting: true }, false)).toBe(1500);
    expect(etrRefetch({ ...view, publication: pub }, false)).toBe(5000);
    expect(etrRefetch({ ...view, publication: null }, false)).toBe(false);
  });

  it("places times on one axis from the earliest P10 to the latest P90", () => {
    const at = axis("2024-09-28T00:00:00Z", "2024-09-29T00:00:00Z");
    expect(at("2024-09-28T12:00:00Z")).toBe(50);
    expect(at("2024-09-30T00:00:00Z")).toBe(100);
    expect(earliest(["2024-09-29T00:00:00Z", "2024-09-28T06:00:00Z"])).toBe("2024-09-28T06:00:00.000Z");
    expect(latest(["2024-09-29T00:00:00Z", "2024-09-28T06:00:00Z"])).toBe("2024-09-29T00:00:00.000Z");
  });
});

describe("After-action blocks", () => {
  it("shows the published ETR only after publication", async () => {
    const card = { name: "x", label: "S", actual_label: "simulated", metrics: [], estimates: [] };
    const { unmount } = show("audit_01", <PublishedEtr card={card} />);
    await waitFor(() => expect(mockState.userId).toBe("audit_01"));
    expect(screen.queryByTestId("published-etr")).toBeNull();
    unmount();
    etrMock.publication = {
      proposal_id: "PRP-ETR-MOCK0001",
      run_id: "run-etr-mock0001",
      run_status: "done",
      state: "executed",
      proposed_by: "plan_etr_01",
      estimate_id: view.whole?.estimate_id ?? "",
      p50_utc: view.whole?.p50_utc ?? "",
      required_functions: ["command", "operations"],
      signed_functions: ["command", "operations"],
      created_at: view.as_of,
      published_at: view.as_of,
      published_by: "plan_etr_01",
      audit_seq: 812,
    };
    show("audit_01", <PublishedEtr card={card} />);
    const block = await screen.findByTestId("published-etr");
    expect(within(block).getByText(when(view.whole?.p50_utc ?? ""))).toBeInTheDocument();
    expect(within(block).getByText(/signed by Command and Operations/)).toBeInTheDocument();
    expect(within(block).queryByText("Compared with actual")).toBeNull();
  });

  it("lets the auditor draft the review and shows the summary", async () => {
    show("audit_01", <ReviewDraft />);
    fireEvent.click(await screen.findByRole("button", { name: "Draft report" }));
    fireEvent.click(await screen.findByRole("button", { name: "Show text" }));
    expect(await screen.findByTestId("review-summary")).toHaveTextContent("Two of six deadlines were met.");
    expect(screen.getByRole("button", { name: "Download" })).toBeInTheDocument();
  });

  it("hides the block from people who may not draft when there is no draft", async () => {
    show("ops_dm_01", <ReviewDraft />);
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId("review-draft")).toBeNull();
  });

  it("renders estimates whose actual is still ahead instead of crashing", () => {
    const unresolved = {
      estimate_id: "ETR-X",
      region_id: "GLOBAL",
      scope: "global" as const,
      as_of_utc: "2024-09-28T17:30:00Z",
      actual_utc: null,
      p50_error_h: null,
      abs_error_h: null,
      analog_abs_error_h: null,
      in_p25_p75: null,
      in_p10_p90: null,
    };
    const card = { name: "x", label: "S", actual_label: "simulated", metrics: [], estimates: [unresolved] };
    show("audit_01", <ScorecardTab card={card} />);
    expect(screen.getByText("Accuracy is known once power is restored.")).toBeInTheDocument();
  });
});
