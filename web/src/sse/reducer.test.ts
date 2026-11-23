import { GOLDEN_STREAMS } from "@/contracts/msw.gen";
import type { WireFrame } from "@/contracts/wire.gen";
import { createSseParser, type SseMessage } from "./parser";
import { initialOpsState, reduceFrame, scenarioNowMs } from "./reducer";

function frames(body: string): { id?: string; frame: WireFrame }[] {
  const out: SseMessage[] = [];
  const parser = createSseParser((m) => out.push(m));
  parser.push(body);
  return out.map((m) => ({ id: m.id, frame: JSON.parse(m.data) as WireFrame }));
}

describe("SSE parser", () => {
  it("handles chunks split mid-line and ignores comments", () => {
    const out: SseMessage[] = [];
    const p = createSseParser((m) => out.push(m));
    p.push(": hello\nid: ops.1.1\nevent: led");
    p.push('ger\ndata: {"a":1}\n\n');
    expect(out).toEqual([{ id: "ops.1.1", event: "ledger", data: '{"a":1}', retry: undefined }]);
  });
});

describe("ops reducer on the golden stream", () => {
  const parsed = frames(GOLDEN_STREAMS.ops_ps17_hinge);

  it("parses every golden frame", () => {
    expect(parsed.length).toBeGreaterThan(20);
  });

  it("tracks the last event id, the head and the scenario clock", () => {
    let state = initialOpsState;
    for (const { id, frame } of parsed.slice(0, 2)) state = reduceFrame(state, frame, id, 1_000).state;
    expect(state.lastEventId).toBe("ops.1.1");
    expect(state.killLevel).toBe("K0");
    expect(state.scenarioTime).toBe("2024-09-26T03:40:00Z");
    expect(state.speed).toBe(60);
    expect(scenarioNowMs(state, 2_000)).toBe(Date.parse("2024-09-26T03:40:00Z") + 1_000 * 60);
  });

  it("invalidates proposals on decision and approval events and everything on resync", () => {
    let state = initialOpsState;
    const keys: unknown[][] = [];
    for (const { id, frame } of parsed) {
      const r = reduceFrame(state, frame, id, 1_000);
      state = r.state;
      for (const e of r.effects) keys.push([...e.invalidate]);
    }
    expect(keys).toContainEqual(["proposals"]);
    expect(keys).toContainEqual(["proposals", "PRP-PS17-FDR2207-PRIO"]);
    expect(keys).toContainEqual(["notifications"]);
    expect(keys).toContainEqual([]);
    expect(state.resyncs).toBe(1);
  });
});

describe("the scenario clock", () => {
  it("moves on heartbeats, not on the time an event happened", () => {
    const beat = {
      type: "heartbeat",
      scenario_time: "2024-09-26T15:05:00Z",
      payload: {},
    } as unknown as WireFrame;
    const stop = {
      type: "ledger",
      ledger_seq: 9,
      scenario_time: "2026-11-22T04:03:00Z",
      payload: { event_type: "KillSwitchChanged", payload: {} },
    } as unknown as WireFrame;
    let state = reduceFrame(initialOpsState, beat, "ops.1.8", 1_000).state;
    state = reduceFrame(state, stop, "ops.1.9", 2_000).state;
    expect(state.scenarioTime).toBe("2024-09-26T15:05:00Z");
  });
});

describe("read models that follow a signature", () => {
  const ledger = (eventType: string): WireFrame =>
    ({
      type: "ledger",
      ledger_seq: 7,
      scenario_time: null,
      payload: { event_type: eventType, payload: { proposal_id: "PRP-ZR-1" } },
    }) as unknown as WireFrame;

  it.each(["ApprovalRecorded", "DecisionApproved", "ProposalUpdated"])(
    "%s refreshes the water register, the Briefing and the crew targets",
    (eventType) => {
      const keys = reduceFrame(initialOpsState, ledger(eventType), "ops.1.7", 1_000).effects.map((e) => [
        ...e.invalidate,
      ]);
      expect(keys).toEqual(expect.arrayContaining([["water"], ["brief"], ["crews", "targets"]]));
    },
  );

  it("a clock change leaves them alone", () => {
    const keys = reduceFrame(initialOpsState, ledger("RiskSnapshotPublished"), "ops.1.8", 1_000).effects.map(
      (e) => [...e.invalidate],
    );
    expect(keys).not.toContainEqual(["water"]);
  });
});
