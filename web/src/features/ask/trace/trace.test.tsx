import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PERSONAS } from "@/auth/personas";
import { ME_KEY } from "@/auth/useSession";
import { meFor } from "@/mocks/fixtures";
import { mockState } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { adaptTrace } from "./adaptTrace";
import { liveFailedRun, multiAgentRun } from "./fixtures";
import { canSeeTrace } from "./permission";
import { TraceSheet } from "./TraceSheet";
import type { WireRun } from "./wire";

beforeAll(() => server.listen());
afterAll(() => server.close());

describe("adaptTrace", () => {
  const trace = adaptTrace(multiAgentRun("run-1"));

  it("orders the phases of the graph and hides plumbing nodes", () => {
    expect(trace.phases.map((p) => p.id)).toEqual([
      "question",
      "plan",
      "workers",
      "answer",
      "checks",
      "links",
    ]);
  });

  it("puts each worker in its own lane with its tools and AI call", () => {
    const lanes = trace.phases.find((p) => p.id === "workers")?.lanes ?? [];
    expect(lanes.map((l) => l.label)).toEqual(["Water", "Grid and crews", "Policy and evidence"]);
    const water = lanes[0];
    expect(water?.tools.map((t) => [t.verb, t.arg, t.tag])).toEqual([
      ["Read water status", "PS-17", null],
      ["Checked sensors", "PS-17", "A7 detector"],
    ]);
    expect(water?.llm).toHaveLength(1);
    expect(water?.llm[0]).toMatchObject({ model: "claude-sonnet-5-5", mode: "replay", cacheRead: 1640 });
    expect(lanes[2]?.tools.map((t) => t.outcome)).toEqual(["ok", "refused"]);
  });

  it("takes the specialists' time from the slowest lane, not the sum", () => {
    const workers = trace.phases.find((p) => p.id === "workers");
    expect(workers?.ms).toBe(6240);
  });

  it("sums the totals and counts the checks", () => {
    expect(trace.totals).toMatchObject({
      llmCalls: 6,
      cacheRead: 8300,
      billed: false,
      modes: ["replay"],
      checksPassed: 2,
      checksTotal: 2,
    });
  });

  it("marks a failed check and a billed live run", () => {
    const live = adaptTrace(liveFailedRun("run-2"));
    expect(live.totals).toMatchObject({ billed: true, modes: ["live"], checksPassed: 1, checksTotal: 2 });
    expect(live.totals.costMicros).toBeGreaterThan(0);
  });

  it("reads a run from today's graph, with no workers or tool rows, as a flat list of phases", () => {
    const today: WireRun = {
      ...multiAgentRun("run-3"),
      steps: [
        {
          seq: 1,
          kind: "graph_step",
          node: "load_context",
          at: null,
          model: null,
          mode: null,
          decision: null,
          tokens_in: 0,
          tokens_out: 0,
          cost_usd_micros: 0,
          latency_ms: null,
        },
        {
          seq: 2,
          kind: "llm_call",
          node: "investigate",
          at: null,
          model: "claude-sonnet-5-5",
          mode: "live",
          decision: null,
          tokens_in: 900,
          tokens_out: 80,
          cost_usd_micros: 7000,
          latency_ms: 2100,
        },
        {
          seq: 3,
          kind: "graph_step",
          node: "investigate",
          at: null,
          model: null,
          mode: null,
          decision: null,
          tokens_in: 0,
          tokens_out: 0,
          cost_usd_micros: 0,
          latency_ms: null,
        },
      ],
    };
    const flat = adaptTrace(today);
    expect(flat.phases.map((p) => p.label)).toEqual(["Look things up"]);
    expect(flat.phases[0]?.llm).toHaveLength(1);
    expect(flat.phases[0]?.ms).toBe(2100);
  });
});

describe("who sees how an answer was made", () => {
  const sees = (userId: string) => canSeeTrace(meFor(userId));

  it("shows it to the admin, the data and models owner and the auditor", () => {
    expect(["admin_01", "ml_01", "audit_01"].map(sees)).toEqual([true, true, true]);
  });

  it("keeps it from every other seeded person", () => {
    const others = PERSONAS.filter((p) => !["platform", "data", "audit"].includes(p.function));
    expect(others.length).toBeGreaterThan(5);
    expect(others.filter((p) => sees(p.user_id))).toEqual([]);
  });

  it("is off before sign-in", () => {
    expect(canSeeTrace(null)).toBe(false);
    expect(canSeeTrace(undefined)).toBe(false);
  });
});

function show(userId: string, search = "?trace=RUN-0047") {
  mockState.userId = userId;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(ME_KEY, meFor(userId));
  return render(
    <QueryClientProvider client={qc}>
      <NuqsTestingAdapter searchParams={search}>
        <TraceSheet />
      </NuqsTestingAdapter>
    </QueryClientProvider>,
  );
}

describe("the trace sheet", () => {
  it("opens for the admin with totals, lanes and checks", async () => {
    show("admin_01");
    const sheet = await screen.findByTestId("trace-sheet");
    expect(within(sheet).getByRole("heading", { name: "How this answer was made" })).toBeInTheDocument();
    expect(await within(sheet).findByTestId("trace-totals")).toHaveTextContent("11.1 s");
    expect(within(sheet).getAllByTestId("trace-lane")).toHaveLength(3);
    expect(
      within(sheet)
        .getAllByTestId("trace-check")
        .map((c) => c.getAttribute("data-passed")),
    ).toEqual(["true", "true"]);
    expect(within(sheet).getByText("Refused")).toBeInTheDocument();
  });

  it("stays closed for operations", () => {
    show("ops_dm_01");
    expect(screen.queryByTestId("trace-sheet")).toBeNull();
  });
});
