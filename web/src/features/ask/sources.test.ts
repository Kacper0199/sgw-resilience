import { describe, expect, it } from "vitest";
import type { ParsedAnswer, RunView, ToolCall } from "../agent-panel/types";
import { caseWords, sourcesOf } from "./sources";

const parsed: ParsedAnswer = { kind: "llm", body: "x", lead: null, citations: [], platform: [] };
const call = (n: number, tool: string, args: Record<string, unknown>): ToolCall =>
  ({ call: n, tool, args, status: "ok" }) as ToolCall;
const run = (tools: ToolCall[]): RunView => ({ tools }) as unknown as RunView;

describe("Sources panel rows", () => {
  it("collapses a lookup two analysts made and names what was read in plain words", () => {
    const set = sourcesOf(
      parsed,
      run([
        call(1, "get_decision_case", { decision_case_id: "DC-D3-HSP-TALLOWBRANCH-WATER" }),
        call(2, "get_decision_case", { decision_case_id: "DC-D3-HSP-TALLOWBRANCH-WATER" }),
        call(3, "get_decision_case", { decision_case_id: "DC-D3-PS17-PRESSURE" }),
        call(4, "get_risk", { domain: "water", level: "asset", entity_ids: ["PS-17", "PS-23"] }),
        call(5, "get_forecast", { target: "outages", entity_id: "PS-17" }),
        call(6, "get_forecast", { target: "outages", entity_id: "PS-17" }),
      ]),
      [
        {
          kind: "decision",
          id: "DC-D3-HSP-TALLOWBRANCH-WATER",
          label: "Secure water supply to Tallowbranch hospital",
        },
      ],
    );
    expect(set.platform.map((p) => [p.title ?? p.id, p.label])).toEqual([
      ["Secure water supply to Tallowbranch hospital", "Decision deadline"],
      ["PS-17 pressure decision", "Decision deadline"],
      [null, "Outage risk at named assets"],
      ["PS-17", "Forecast"],
    ]);
  });

  it("leaves out a lookup that found nothing, such as a page not modelled for the scenario", () => {
    const set = sourcesOf(
      parsed,
      run([
        { ...call(1, "get_water_status", { zone: "all" }), empty: true },
        call(2, "get_decision_case", { decision_case_id: "DC-D3-PS17-PRESSURE" }),
      ]),
    );
    expect(set.platform.map((p) => p.tool)).toEqual(["get_decision_case"]);
  });

  it("lists the decision queue once when two analysts read it", () => {
    const set = sourcesOf(
      parsed,
      run([call(1, "list_decisions", {}), call(2, "list_decisions", { limit: 50 })]),
    );
    expect(set.platform).toHaveLength(1);
  });

  it("heads a code answer's decision rows with the decision title, not the case id", () => {
    const code: ParsedAnswer = {
      ...parsed,
      kind: "m2",
      platform: [
        { id: "DC-D3-PS17-PRESSURE", text: "DC-D3-PS17-PRESSURE: missed, no proposal before its deadline." },
        { id: "DC-D3-PS17-FUEL", text: "DC-D3-PS17-FUEL: missed, not signed by its deadline." },
        {
          id: "closed",
          text: "14 open on the Decisions page. Closed so far: 15 (12 decided on time, 3 missed).",
        },
      ],
    };
    const set = sourcesOf(code, null, [
      {
        kind: "decision",
        id: "DC-D3-PS17-PRESSURE",
        label: "Hold Cedarfall zone pressure above the state floor",
      },
    ]);
    expect(set.platform.map((p) => [p.title, p.decisionCaseId])).toEqual([
      ["Hold Cedarfall zone pressure above the state floor", "DC-D3-PS17-PRESSURE"],
      ["PS-17 fuel decision", "DC-D3-PS17-FUEL"],
    ]);
  });

  it("reads a decision case id in words when nothing names it", () => {
    expect(caseWords("DC-D2-CREWS-AIK")).toBe("Crews decision");
    expect(caseWords("DC-D3-PS17-FUEL")).toBe("PS-17 fuel decision");
  });
});
