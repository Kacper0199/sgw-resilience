import { makeSitrep } from "@/features/brief/mocks/data";
import { MOCK_NOW } from "@/mocks/fixtures";
import type { MockScript } from "./scripts";

export interface Beat {
  after: number;
  type: string;
  payload: Record<string, unknown>;
}

export interface TimedFrame {
  seq: number;
  at: number;
  type: string;
  payload: Record<string, unknown>;
}

const step = (node: string, status: "start" | "end"): Beat => ({
  after: 40,
  type: "step",
  payload: { node, status },
});
const agent = (type: "agent_start" | "agent_end", node: string, after: number): Beat => ({
  after,
  type,
  payload: { node, status: type === "agent_start" ? "start" : "end" },
});

export function copilotBeats(question: string, s: MockScript): Beat[] {
  const beats: Beat[] = [
    { after: 0, type: "run_start", payload: { graph: "copilot", input_keys: ["question"] } },
    step("load_context", "start"),
    { after: 30, type: "artifact", payload: { kind: "message", role: "user", text: question } },
    step("load_context", "end"),
    agent("agent_start", "route_intent", 60),
    agent("agent_end", "route_intent", 420),
    agent("agent_start", "investigate", 60),
  ];
  s.tools.forEach((t, call) => {
    beats.push({ after: 320, type: "tool_start", payload: { tool: t.tool, args: t.args, call } });
    beats.push({ after: 380, type: "tool_end", payload: { tool: t.tool, call, status: "ok" } });
  });
  beats.push(agent("agent_end", "investigate", 300));
  beats.push(step("respond", "start"));
  beats.push({
    after: 30,
    type: "artifact",
    payload: {
      kind: "message",
      role: "assistant",
      text: s.text,
      path: s.path,
      reason: s.reason ?? null,
      citations: s.citations,
      evidence_ids: s.evidenceIds,
      references: s.references,
      ...(s.extras ?? {}),
      slots_shown: {},
      tainted: s.tainted,
      write_attempts: 0,
    },
  });
  beats.push(step("respond", "end"), step("audit", "start"), step("audit", "end"));
  beats.push({ after: 30, type: "run_end", payload: { status: "ended" } });
  return beats;
}

export function sitrepBeats(): Beat[] {
  const draft = makeSitrep("pending", false);
  return [
    { after: 0, type: "run_start", payload: { graph: "sitrep", input_keys: [] } },
    step("load_context", "start"),
    step("load_context", "end"),
    step("input_guard", "start"),
    step("input_guard", "end"),
    step("sitrep_evidence", "start"),
    step("sitrep_evidence", "end"),
    agent("agent_start", "sitrep", 120),
    agent("agent_end", "sitrep", 700),
    step("verify", "start"),
    step("verify", "end"),
    step("sitrep_draft", "start"),
    {
      after: 60,
      type: "artifact",
      payload: {
        kind: "sitrep_draft",
        tier: draft.tier,
        promotion: "by a person",
        path: "llm",
        rendered: draft.text,
        slots: draft.slots,
        tainted: false,
      },
    },
    step("sitrep_draft", "end"),
    step("audit", "start"),
    step("audit", "end"),
    { after: 30, type: "run_end", payload: { status: "draft_ready" } },
  ];
}

/** Places each beat on the clock: `at` is milliseconds after the run started, `ts` is derived from it. */
export function schedule(beats: Beat[]): TimedFrame[] {
  const fast = typeof sessionStorage !== "undefined" && sessionStorage.getItem("sgw.mock.fast") !== null;
  let t = 0;
  return beats.map((b, seq) => {
    t += fast ? b.after * 0.02 : b.after;
    return { seq, at: t, type: b.type, payload: b.payload };
  });
}

export const runTs = (startedAt: number, at: number): string => new Date(startedAt + at).toISOString();
export const MOCK_SCENARIO_TIME = MOCK_NOW;
