import { describe, expect, it } from "vitest";
import type { WireFrame } from "@/contracts/wire.gen";
import { emptyRun, reduceRunFrame } from "../agent-panel/reduceRun";
import { liveStep, plForm } from "./StepsLine";

const frame = (type: string, payload: Record<string, unknown>, seq: number): WireFrame =>
  ({ type, payload, seq, ts: "2024-09-26T15:05:00Z", run_id: "r1", thread_id: "t1" }) as unknown as WireFrame;

const play = (...frames: [string, Record<string, unknown>][]) =>
  frames.reduce(
    (run, [type, payload], i) => reduceRunFrame(run, frame(type, payload, i)),
    emptyRun("r1", "t1", "copilot", "q"),
  );

describe("liveStep names what the run is really doing", () => {
  it("reads the question first", () => {
    expect(liveStep(play(["agent_start", { node: "route_intent", status: "start" }]))).toBe(
      "Reading the question…",
    );
  });
  it("names the planner, then the running analyst, then its lookup", () => {
    expect(liveStep(play(["agent_start", { node: "plan", status: "start" }]))).toBe(
      "Choosing what to check…",
    );
    const water = play(
      ["agent_start", { node: "plan", status: "start" }],
      ["agent_end", { node: "plan", status: "end" }],
      ["agent_start", { node: "worker", status: "start" }],
      ["step", { node: "worker:water", status: "start" }],
    );
    expect(liveStep(water)).toBe("Checking water service…");
    const lookup = reduceRunFrame(
      water,
      frame("tool_start", { tool: "get_water_status", args: {}, call: 1101, worker: "water" }, 9),
    );
    expect(liveStep(lookup)).toBe("Checking pump stations and tanks…");
  });
  it("says when it writes the answer", () => {
    expect(liveStep(play(["agent_start", { node: "synthesise", status: "start" }]))).toBe(
      "Writing the answer…",
    );
  });
});

describe("the steps line follows a Polish question", () => {
  it("counts in Polish with the right plural forms", () => {
    expect(plForm(1)).toBe(0);
    expect(plForm(3)).toBe(1);
    expect(plForm(12)).toBe(2);
    expect(plForm(22)).toBe(1);
    expect(plForm(5)).toBe(2);
    expect(liveStep(play(["agent_start", { node: "synthesise", status: "start" }]), "pl")).toBe(
      "Piszę odpowiedź…",
    );
  });
});
