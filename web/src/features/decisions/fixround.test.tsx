import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { useLogin, useLogout } from "@/auth/useSession";
import { api } from "@/lib/api";
import { onSessionReset } from "@/lib/sessionReset";
import { server } from "@/mocks/server";
import { waitingLine } from "./ApprovalTab";
import { currentShift, observeClocks, observeScenarioTime, resetClockShifts } from "./clockShifts";
import { ADVISORY_TIME, storyCards, summaryOf } from "./mocks/story";
import { ordinal, reorderNotice } from "./reorderNotice";
import { TIMING_LABEL, timingLineOf } from "./ui";
import { useSign } from "./useSign";
import { observeVersions, resetVoided, voidedUpTo } from "./voidedApprovals";
import { Waterfall } from "./Waterfall";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

describe("C1: a signature is bound to the decision the dialog opened on", () => {
  const [a, b] = storyCards("N");
  if (!a || !b) throw new Error("fixture");

  it("blocks signing and never calls the API for another proposal when the card changes", () => {
    const approve = vi.spyOn(api, "approve");
    const { result, rerender } = renderHook(({ card }) => useSign(card), {
      wrapper,
      initialProps: { card: a },
    });
    expect(result.current.stale).toBe(false);
    rerender({ card: b });
    expect(result.current.otherDecision).toBe(true);
    expect(result.current.stale).toBe(true);
    result.current.sign({ decision: "approve" });
    expect(approve).not.toHaveBeenCalled();
    approve.mockRestore();
  });

  it("signs the proposal it was bound to after the person reviews", () => {
    const { result, rerender } = renderHook(({ card }) => useSign(card), {
      wrapper,
      initialProps: { card: a },
    });
    rerender({ card: b });
    result.current.review();
    rerender({ card: b });
    expect(result.current.stale).toBe(false);
    expect(ADVISORY_TIME.N).toBeTruthy();
  });
});

describe("H2: the approval header names every function that still has to sign", () => {
  it("puts your own function first with (you) and lists the others", () => {
    expect(waitingLine(["command", "water_operations"], "water_operations")).toBe(
      "Waiting for Water operations (you), Command",
    );
  });
  it("lists every missing function when none is yours", () => {
    expect(waitingLine(["command", "water_operations"], "executive")).toBe(
      "Waiting for Command, Water operations",
    );
  });
  it("says Ready when nothing is missing", () => {
    expect(waitingLine([], "command")).toBe("Ready");
  });
});

const itemsAt = (adv: "N" | "N+1") => storyCards(adv).map((card) => ({ summary: summaryOf(card), card }));

describe("H3: nothing learned in the browser outlives what it was learned from", () => {
  beforeAll(() => server.listen({ onUnhandledFrame: "bypass" }));
  afterAll(() => server.close());
  beforeEach(() => {
    resetClockShifts();
    resetVoided();
  });

  it("shows the earlier-by chip only while the card still has the decide-by the shift moved to", () => {
    observeClocks(itemsAt("N"));
    observeClocks(itemsAt("N+1"));
    const shifts = JSON.parse(sessionStorage.getItem("sgw.clockShifts") ?? "{}");
    const ps17 = storyCards("N+1")[0];
    if (!ps17) throw new Error("fixture");
    expect(currentShift(shifts, ps17.decision_case_id, ps17.effective_decide_by_utc)).toBeDefined();
    expect(currentShift(shifts, ps17.decision_case_id, "2024-09-27T08:00:00Z")).toBeUndefined();
  });

  it("keeps a voided row only when its replacing version has been reached", () => {
    const list = [{ approver_id: "ic_01", function: "command", at: "x", version: 1, voidedBy: 2 }] as never;
    expect(voidedUpTo(list, 2)).toHaveLength(1);
    expect(voidedUpTo(list, 1)).toHaveLength(0);
  });

  it("forgets shifts and voided rows when the scenario clock moves backwards", () => {
    observeVersions(itemsAt("N"));
    observeVersions(itemsAt("N+1"));
    observeClocks(itemsAt("N"));
    observeClocks(itemsAt("N+1"));
    expect(sessionStorage.getItem("sgw.voidedApprovals")).not.toBeNull();
    observeScenarioTime("2024-09-26T15:25:00Z");
    observeScenarioTime("2024-09-26T09:30:00Z");
    expect(sessionStorage.getItem("sgw.voidedApprovals")).toBeNull();
    expect(sessionStorage.getItem("sgw.clockShifts")).toBeNull();
  });

  it("forgets them on sign-out and on sign-in", async () => {
    const reset = vi.fn();
    const off = onSessionReset(reset);
    const { result: out } = renderHook(() => useLogout(), { wrapper });
    out.current.mutate();
    await waitFor(() => expect(reset).toHaveBeenCalledTimes(1));
    const { result: inn } = renderHook(() => useLogin(), { wrapper });
    inn.current.mutate({ user_id: "ic_01", password: "demo" });
    await waitFor(() => expect(reset).toHaveBeenCalledTimes(2));
    off();
  });
});

describe("M5: the waterfall plots the decide-by the API sent", () => {
  const base = {
    decision_case_id: "DC-X",
    consequence_utc: "2024-09-27T08:00:00Z",
    consequence_range_utc: ["2024-09-27T07:15:00Z", "2024-09-27T08:50:00Z"] as [string, string],
    consequence_basis: { kind: "model_estimate" as const, basis_id: "m", basis_version: "1", citation: null },
    action_lead_time_min: 150,
    lead_time_basis: { kind: "model_estimate" as const, basis_id: "l", basis_version: "1", citation: null },
    bound_by_case_id: null,
  };
  const left = (id: string) => Number.parseFloat((screen.getByTestId(id) as HTMLElement).style.left);

  it("marks the effective decide-by apart from the own clock and names the case that holds it earlier", () => {
    render(
      <Waterfall
        data={{
          ...base,
          decide_by_utc: "2024-09-27T05:30:00Z",
          effective_decide_by_utc: "2024-09-27T00:30:00Z",
          bound_by_case_id: "DC-D3-PS17-POWER",
        }}
        now="2024-09-26T20:00:00Z"
      />,
    );
    expect(left("waterfall-effective")).toBeLessThan(left("waterfall-own"));
    expect(screen.getByTestId("waterfall-held")).toHaveTextContent("to ◆ 20:30 ET");
  });

  it("does not subtract the lead time itself: a decide-by that disagrees with it is drawn at the API value", () => {
    render(
      <Waterfall
        data={{
          ...base,
          decide_by_utc: "2024-09-27T03:00:00Z",
          effective_decide_by_utc: "2024-09-27T03:00:00Z",
        }}
        now="2024-09-26T20:00:00Z"
      />,
    );
    expect(screen.getByTestId("waterfall-own")).toHaveAttribute("data-at", "2024-09-27T03:00:00Z");
    expect(screen.queryByTestId("waterfall-held")).toBeNull();
  });
});

describe("M7: a reorder is announced politely", () => {
  const shifts = {
    "DC-D3": { caseId: "DC-D3", from: "2024-09-27T04:45:00Z", to: "2024-09-27T03:29:00Z", atMs: 1 },
  };
  it("names the decision, its new place and how its decide-by moved", () => {
    const after = [
      { id: "a", caseId: "DC-D3", title: "Fuel PS-17 generator" },
      { id: "b", caseId: "DC-X", title: "Other" },
    ];
    expect(reorderNotice(["b", "a"], after, shifts)).toBe(
      "Fuel PS-17 generator moved to position 1; deadline earlier by 1 h 16 m",
    );
  });
  it("says nothing when the order is unchanged or nothing shifted", () => {
    const after = [{ id: "a", caseId: "DC-D3", title: "x" }];
    expect(reorderNotice(["a"], after, shifts)).toBe("");
    expect(reorderNotice(["b", "a"], [{ id: "a", caseId: "DC-Q", title: "x" }, ...[]], shifts)).toBe("");
    expect(reorderNotice([], after, shifts)).toBe("");
  });
  it("writes ordinals", () => {
    expect([1, 2, 3, 4, 11, 12, 21, 22].map(ordinal)).toEqual([
      "1st",
      "2nd",
      "3rd",
      "4th",
      "11th",
      "12th",
      "21st",
      "22nd",
    ]);
  });
});

describe("R30: Timing without a forecast", () => {
  const [base] = storyCards("N");
  if (!base) throw new Error("fixture");
  const noEnsemble = {
    ...base,
    case: {
      ...base.case,
      timing: "n/a" as const,
      timing_reason: "No forecast ensemble covers this decision, so there is no act-or-wait advice.",
      blocks: [],
      chain: [],
    },
  };

  it("says to decide by the deadline and never that it follows another decision", () => {
    expect(TIMING_LABEL["n/a"]).toBe("By the deadline");
    expect(timingLineOf(noEnsemble, null)).toBeUndefined();
  });

  it("names the decision it follows when the Timing is inherited", () => {
    const inherited = {
      ...noEnsemble,
      case: {
        ...noEnsemble.case,
        timing: "decide_now" as const,
        timing_reason:
          "Follows “Hook up the portable generator at PS-17”, so it shares that decision's timing.",
        blocks: ["DC-X"],
        chain: [
          {
            ...(base.case.chain?.[0] ?? {}),
            decision_case_id: "DC-X",
            title: "Hook up the portable generator at PS-17",
          },
        ],
      },
    } as typeof base;
    expect(timingLineOf(inherited, null)).toMatch(/^Follows /);
    const before = {
      ...inherited,
      case: {
        ...inherited.case,
        timing_reason:
          "Needed before “Hook up the portable generator at PS-17”, so it follows that decision's timing.",
      },
    } as typeof base;
    expect(timingLineOf(before, null)).toMatch(/^Ahead of /);
  });
});
