import type { WireFrame } from "@/contracts/wire.gen";
import { buildTurns } from "./buildTurns";
import { copilotDelegations } from "./delegations";
import { inferPath, NOT_IN_DOCS, parseAnswer, splitMarkers } from "./parseAnswer";
import { emptyRun, reduceRunFrame } from "./reduceRun";
import type { RunView } from "./types";

const T0 = Date.parse("2024-09-27T01:00:00Z");
let seq = 0;
const frame = (type: string, payload: Record<string, unknown>, ms = 0): WireFrame =>
  ({
    v: 1,
    type,
    seq: seq++,
    ledger_seq: null,
    run_id: "run-1",
    ns: [],
    ts: new Date(T0 + ms).toISOString(),
    scenario_time: "2024-09-27T01:00:00Z",
    run_mode: "replay",
    classification: "C1",
    payload,
  }) as WireFrame;

const fold = (frames: WireFrame[]): RunView =>
  frames.reduce((run, f) => reduceRunFrame(run, f), emptyRun("run-1", "thr-1", "copilot", null));

function copilotFrames(answer: Record<string, unknown>): WireFrame[] {
  seq = 0;
  return [
    frame("run_start", { graph: "copilot" }),
    frame("step", { node: "load_context", status: "start" }, 10),
    frame("artifact", { kind: "message", role: "user", text: "Which stations have generators?" }, 20),
    frame("step", { node: "load_context", status: "end" }, 30),
    frame("agent_start", { node: "route_intent", status: "start" }, 40),
    frame("agent_end", { node: "route_intent", status: "end" }, 400),
    frame("agent_start", { node: "investigate", status: "start" }, 450),
    frame("tool_start", { tool: "get_water_status", args: {}, call: 0 }, 800),
    frame("tool_end", { tool: "get_water_status", call: 0, status: "ok" }, 810),
    frame("agent_end", { node: "investigate", status: "end" }, 900),
    frame("artifact", { kind: "message", role: "assistant", ...answer }, 950),
    frame("run_end", { status: "ended" }, 1000),
  ];
}

describe("reduceRunFrame", () => {
  it("folds a copilot stream into nodes, tools, steps and the answer", () => {
    const run = fold(
      copilotFrames({
        text: "PS-38 and PS-52.",
        path: "llm",
        citations: ["DOM 14.206 Rev K"],
        evidence_ids: ["E1"],
      }),
    );
    expect(run.status).toBe("done");
    expect(run.question).toBe("Which stations have generators?");
    expect(run.nodes.map((n) => [n.node, n.status])).toEqual([
      ["load_context", "done"],
      ["route_intent", "done"],
      ["investigate", "done"],
    ]);
    expect(run.tools).toEqual([{ call: 0, tool: "get_water_status", args: {}, status: "ok" }]);
    expect(run.answer).toMatchObject({
      path: "llm",
      citationIds: ["DOM 14.206 Rev K"],
      evidenceIds: ["E1"],
      tainted: false,
    });
    expect(run.log.map((e) => e.label)).toEqual([
      "Read the question",
      "Work out what was asked",
      "Checked water status",
      "Look things up",
      "Answer ready",
      "Done",
    ]);
  });

  it("shows a running tool until its end frame and keeps arguments", () => {
    seq = 0;
    const midway = [
      frame("run_start", {}),
      frame("tool_start", { tool: "search_procedures", args: { query: "paper tickets" }, call: 0 }),
    ].reduce((r, f) => reduceRunFrame(r, f), emptyRun("run-1", "thr-1", "copilot", "q"));
    expect(midway.status).toBe("running");
    expect(midway.tools[0]).toMatchObject({ status: "running", args: { query: "paper tickets" } });
  });

  it("marks a refused tool and keeps the run going", () => {
    seq = 0;
    const run = [
      frame("run_start", {}),
      frame("tool_start", { tool: "draft_proposal", args: {}, call: 0 }),
      frame("tool_end", { tool: "draft_proposal", call: 0, status: "refused" }),
    ].reduce((r, f) => reduceRunFrame(r, f), emptyRun("run-1", "thr-1", "copilot", "q"));
    expect(run.tools[0].status).toBe("refused");
    expect(run.status).toBe("running");
  });

  it("ends as error, cancelled or paused from the terminal frames", () => {
    seq = 0;
    const base = emptyRun("run-1", "thr-1", "copilot", "q");
    expect(
      reduceRunFrame(base, frame("run_error", { error: "ValueError", message: "bad as_of" })).error,
    ).toBe("bad as_of");
    expect(reduceRunFrame(base, frame("run_end", { status: "cancelled" })).status).toBe("cancelled");
    expect(reduceRunFrame(base, frame("run_paused", {})).status).toBe("paused");
  });

  it("records the sitrep draft artifact and ignores heartbeats and unknown frames", () => {
    seq = 0;
    const draft = frame("artifact", {
      kind: "sitrep_draft",
      tier: "T1",
      promotion: "by a person",
      path: "llm",
      rendered: "text",
      slots: { a: "1" },
      tainted: false,
    });
    const run = [frame("heartbeat", {}), frame("resync", {}), draft].reduce(
      (r, f) => reduceRunFrame(r, f),
      emptyRun("run-1", "thr-1", "sitrep", null),
    );
    expect(run.draft).toMatchObject({ tier: "T1", rendered: "text", slots: { a: "1" } });
    expect(run.status).toBe("running");
  });

  it("keeps the last SSE id for reconnects", () => {
    seq = 0;
    const run = reduceRunFrame(
      emptyRun("run-1", "thr-1", "copilot", "q"),
      frame("step", { node: "audit", status: "start" }),
      "run:run-1.1.7",
    );
    expect(run.lastEventId).toBe("run:run-1.1.7");
  });
});

describe("delegation cards", () => {
  it("shows the investigator's tools and, once answered, what it read and cited", () => {
    const run = fold(
      copilotFrames({ text: "x", path: "llm", citations: ["DOM 14.206 Rev K"], evidence_ids: ["E1", "E2"] }),
    );
    const [reader, investigator] = copilotDelegations(run);
    expect(reader).toMatchObject({ id: "route_intent", status: "done", tools: [] });
    expect(investigator.tools).toHaveLength(1);
    expect(investigator.findings).toEqual({ evidenceIds: ["E1", "E2"], citationIds: ["DOM 14.206 Rev K"] });
  });

  it("waits for a specialist that has not started", () => {
    const run = emptyRun("run-1", "thr-1", "copilot", "q");
    expect(copilotDelegations(run).map((d) => d.status)).toEqual(["waiting", "waiting"]);
  });
});

describe("parseAnswer", () => {
  const sources =
    '[1] DOM 14.206 Rev K, 6.0 PROCEDURE; 7.0 RECORDS, pp. 2-4: "6.4.2 Revise a published ETR when the P50 moves."\n' +
    '[2] [field record, unverified] MAL-TKT-ALT-240927-118, Control box; Order, pp. 1-2: "Delivery of diesel, route via Copperleaf Road."';

  it("splits sentences from numbered sources and flags unverified field records", () => {
    const p = parseAnswer(`Revise it.[1] A ticket exists.[2]\n\nSources:\n${sources}`, "llm");
    expect(p.kind).toBe("llm");
    expect(p.body).toBe("Revise it.[1] A ticket exists.[2]");
    expect(p.citations).toHaveLength(2);
    expect(p.citations[0]).toMatchObject({
      n: 1,
      citationId: "DOM 14.206 Rev K",
      section: "6.0 PROCEDURE; 7.0 RECORDS",
      pages: "pp. 2-4",
      unverified: false,
    });
    expect(p.citations[1]).toMatchObject({ n: 2, unverified: true, citationId: "MAL-TKT-ALT-240927-118" });
  });

  it("reads the findings-only list: platform rows and cited passages", () => {
    const text = `Evidence gathered for this question (no model text):\n[E1] Generator hookup at PS-17: decide by 03:29Z\n${sources.split("\n")[0]}`;
    const p = parseAnswer(text, "m2");
    expect(p.kind).toBe("m2");
    expect(p.lead).toContain("no model text");
    expect(p.platform).toEqual([{ id: "E1", text: "Generator hookup at PS-17: decide by 03:29Z" }]);
    expect(p.citations).toHaveLength(1);
  });

  it("infers the path from the fixed wording when the server names none", () => {
    expect(inferPath(NOT_IN_DOCS)).toBe("not_in_documents");
    expect(
      inferPath("This is not in the documents or platform data the copilot can read. It is read-only."),
    ).toBe("not_in_documents");
    expect(inferPath("Evidence gathered for this question (no model text):")).toBe("m2");
    expect(inferPath("PS-38 has a generator.")).toBe("llm");
  });

  it("keeps an answer without a sources block as plain text", () => {
    const p = parseAnswer("PS-38 and PS-52 have generators.");
    expect(p).toMatchObject({ kind: "llm", body: "PS-38 and PS-52 have generators.", citations: [] });
  });

  it("turns known marks into source segments and leaves unknown ones as text", () => {
    const parts = splitMarkers("A.[1] B [7] C.[2]", new Set([1, 2]));
    expect(parts.map((s) => (s.kind === "source" ? `#${s.n}` : s.text))).toEqual([
      "A.",
      "#1",
      " B [7] C.",
      "#2",
    ]);
  });
});

describe("buildTurns", () => {
  const msg = (id: string, role: "user" | "assistant", text: string, at: string) => ({
    message_id: id,
    role,
    text,
    created_at: at,
    evidence_ids: [],
  });

  it("groups the server's messages by run and orders them by time", () => {
    const turns = buildTurns(
      [
        msg("run-b.q", "user", "second", "2024-09-27T01:05:00Z"),
        msg("run-a.q", "user", "first", "2024-09-27T01:00:00Z"),
        msg("run-a.a", "assistant", "answer one", "2024-09-27T01:00:03Z"),
      ],
      new Map(),
    );
    expect(turns.map((t) => [t.runId, t.question, t.answerText])).toEqual([
      ["run-a", "first", "answer one"],
      ["run-b", "second", null],
    ]);
  });

  it("joins a live run to its server message and lets the run's own answer win", () => {
    const run = fold(copilotFrames({ text: "live text", path: "llm", citations: [], evidence_ids: ["E1"] }));
    const turns = buildTurns(
      [msg("run-1.q", "user", "Which stations have generators?", "2024-09-27T01:00:00Z")],
      new Map([[run.runId, run]]),
    );
    expect(turns).toHaveLength(1);
    expect(turns[0]).toMatchObject({ answerText: "live text", evidenceIds: ["E1"] });
    expect(turns[0].run?.runId).toBe("run-1");
  });

  it("still shows a run the server no longer lists", () => {
    const run = fold(copilotFrames({ text: "kept", path: "llm" }));
    const turns = buildTurns([], new Map([[run.runId, run]]));
    expect(turns).toHaveLength(1);
    expect(turns[0].answerText).toBe("kept");
  });
});
