import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import type * as React from "react";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ME_KEY } from "@/auth/useSession";
import { GLOSSARY } from "@/content/glossary";
import { meFor } from "@/mocks/fixtures";
import { mockState, resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { DataTab } from "./DataTab";
import { ageText, durationMs, firstSentence, humanize, list, plural, tokens, usd } from "./format";
import { ModelsTab } from "./ModelsTab";
import { resetControl } from "./mocks";
import runsJson from "./mocks/agent-runs.json";
import evalOutage from "./mocks/eval-outage.json";
import feeds from "./mocks/feeds.json";
import usageJson from "./mocks/usage.json";
import { factsFor, formatValue, specFor } from "./modelFacts";
import { RunsTab } from "./RunsTab";
import { SafetyTab } from "./SafetyTab";
import type { EvalRow } from "./types";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  resetControl();
});
afterEach(() => server.resetHandlers());

function show(ui: React.ReactElement, userId = "ops_dm_01") {
  mockState.userId = userId;
  mockState.stepUpUntil = 0;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(ME_KEY, meFor(userId));
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <NuqsTestingAdapter>{ui}</NuqsTestingAdapter>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const statusLine = () => screen.getByTestId("status-line").textContent ?? "";
const saysLine = (text: string) => waitFor(() => expect(statusLine()).toContain(text));
const outageRows = evalOutage.eval_report.metrics as EvalRow[];
const metric = (suffix: string) => outageRows.find((r) => r.metric.endsWith(suffix)) as EvalRow;

describe("format", () => {
  it("writes ages, ids and money in plain words", () => {
    expect(ageText(null)).toBe("No data yet");
    expect(ageText(55)).toBe("55 s");
    expect(ageText(900)).toBe("15 min");
    expect(ageText(7200)).toBe("2 h");
    expect(humanize("nws-alerts")).toBe("NWS alerts");
    expect(humanize("asos-obs")).toBe("ASOS observations");
    expect(humanize("llm_down")).toBe("LLM down");
    expect(durationMs(820)).toBe("820 ms");
    expect(durationMs(null)).toBe("Running");
    expect(tokens(540)).toBe("540");
    expect(tokens(14_210)).toBe("14k");
    expect(usd(0.004)).toBe("<$0.01");
    expect(usd(2.254)).toBe("$2.25");
    expect(plural(1, "check")).toBe("1 check");
    expect(list(["a", "b", "c"])).toBe("a, b and c");
    expect(firstSentence("Pull every adapter; outbox rows commit together. More.")).toBe(
      "Pull every adapter; outbox rows commit together.",
    );
  });

  it("keeps every Health and Readiness toggletip within 25 words", () => {
    for (const key of [
      "feed_freshness",
      "pipeline_run",
      "lineage",
      "dq_check",
      "model_card",
      "ai_run",
      "ai_trace",
      "degraded_mode",
      "kill_switch",
      "two_function_restore",
      "readiness",
      "readiness_status",
    ] as const)
      expect(GLOSSARY[key].text.split(/\s+/).length, key).toBeLessThanOrEqual(25);
  });
});

describe("model facts", () => {
  it("formats each fact the way its metric reads, from the report's own values", () => {
    const facts = factsFor(specFor("a2-excl-helene"), outageRows);
    const byLabel = Object.fromEntries(facts.map((f) => [f.label, f]));
    expect(byLabel["Storms where the total was forecast too low"]?.value).toBe(
      formatValue(
        metric("S5.storms_under_predicted_total").value,
        "of_n",
        metric("S5.storms_under_predicted_total"),
      ),
    );
    expect(byLabel["Outages forecast, as a share of those observed"]?.value).toBe(
      `${Math.round(metric("S5.pooled_forecast_over_observed").value * 100)}%`,
    );
    expect(byLabel["Needed to replace the curve"]?.value).toBe("Below target");
    expect(byLabel["Needed to replace the curve"]?.mark).toBeNull();
    expect(byLabel["The same, for the eight largest storms"]?.mark).toBe("below");
  });

  it("falls back to the first scored rows for a model it has no card for", () => {
    const rows = [
      {
        metric: "x.in_sample.err",
        value: 1,
        unit: "relative",
        n: 1,
        split: "s",
        label: "C",
        baseline_name: null,
        baseline_value: null,
        threshold: null,
        direction: "lower_is_better",
        passed: true,
      },
      {
        metric: "x.score",
        value: 0.5,
        unit: "relative",
        n: 1,
        split: "s",
        label: "C",
        baseline_name: null,
        baseline_value: null,
        threshold: null,
        direction: "lower_is_better",
        passed: false,
      },
    ] satisfies EvalRow[];
    const facts = factsFor(undefined, rows);
    expect(facts).toHaveLength(1);
    expect(facts[0]).toMatchObject({ label: "Score", mark: "below" });
  });
});

describe("Data tab", () => {
  it("leads with one plain line, then sources, pipeline and checks", async () => {
    show(<DataTab />);
    const late = feeds.filter((f) => f.stale);
    await saysLine("Some data needs attention");
    const line = statusLine();
    expect(line).toContain(late[0]?.display_name ?? "");
    expect(await screen.findAllByTestId("feed-row")).toHaveLength(feeds.length);
    expect(within(screen.getAllByTestId("feed-row").at(-1) as HTMLElement).getByText("Late")).toBeDefined();
    expect(await screen.findAllByTestId("asset-row")).not.toHaveLength(0);
    expect((await screen.findByTestId("checks-summary")).textContent).toMatch(
      /checks: \d+ passed, 1 warning$/,
    );
  });

  it("opens an asset's lineage one click deeper and keeps passed checks folded", async () => {
    show(<DataTab />);
    const rows = await screen.findAllByTestId("asset-row");
    expect(screen.queryByTestId("lineage-row")).toBeNull();
    fireEvent.click(within(rows[0] as HTMLElement).getByRole("button", { name: /Data flow for/ }));
    const lineage = await screen.findByTestId("lineage-row");
    expect(lineage.textContent).toContain("Comes from");
    expect(lineage.textContent).toContain("Used by");
    expect(screen.queryByRole("table", { name: "Checks that passed" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Passed checks/ }));
    expect(await screen.findByRole("table", { name: "Checks that passed" })).toBeDefined();
  });

  it("adds no status line when nothing is late or failing", async () => {
    server.use(
      http.get("/api/feeds/health", () => HttpResponse.json(feeds.map((f) => ({ ...f, stale: false })))),
      http.get("/api/dq/checks", () => HttpResponse.json([])),
    );
    show(<DataTab />);
    expect(await screen.findAllByTestId("feed-row")).toHaveLength(feeds.length);
    expect(screen.queryByTestId("status-line")).toBeNull();
  });

  it("names the stage it is loading and fails inside the card, not the page", async () => {
    server.use(
      http.get("/api/feeds/health", () =>
        HttpResponse.json({ error: { code: "X", message: "x" } }, { status: 500 }),
      ),
    );
    show(<DataTab />);
    expect(screen.getAllByRole("status", { name: /Loading/ }).length).toBeGreaterThan(0);
    expect(await screen.findByText("Couldn't load data sources.")).toBeDefined();
    await saysLine("Couldn't load data status");
  });
});

describe("Models tab", () => {
  it("states the fitted curve leads, the machine-learning variants were beaten and large storms are under-called", async () => {
    show(<ModelsTab />);
    const cards = await screen.findAllByRole("region", { name: /Outage forecast/ });
    const card = cards[0] as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "About this model" }));
    const about = await screen.findByRole("dialog", { name: "About this model" });
    expect(about.textContent).toContain("fitted wind-fragility curve");
    expect(about.textContent).toContain("did not beat it");
    expect(about.textContent).toContain("under-calls large storms");
    await waitFor(() => expect(within(card).getAllByTestId("model-fact").length).toBeGreaterThan(0));
    const largest = within(card)
      .getByText("The same, for the eight largest storms")
      .closest("div") as HTMLElement;
    expect(largest.textContent).toContain(
      `${Math.round(metric("S5.pooled_forecast_over_observed_large8").value * 100)}%`,
    );
    expect(largest.textContent).toContain("Below target");
  });

  it("says in one line which models are below target", async () => {
    show(<ModelsTab />);
    await saysLine("below target");
    const line = statusLine();
    expect(line).toContain("Water fault detector");
    expect(line).toContain("Outage forecast");
  });

  it("shows the model each AI step uses to administrators only", async () => {
    const { unmount } = show(<ModelsTab />, "ops_dm_01");
    expect(await screen.findByTestId("ai-config-hidden")).toBeDefined();
    unmount();
    show(<ModelsTab />, "admin_01");
    const rows = await screen.findAllByTestId("ai-node-row");
    expect(rows.length).toBeGreaterThan(0);
    expect(screen.getByTestId("ai-node-summary").textContent).toMatch(/on Sonnet.*on Haiku/);
    for (const r of rows) {
      expect(r.textContent).not.toMatch(/prompt/i);
      expect(r.className).not.toMatch(/hover:|cursor-pointer/);
    }
    expect(
      within(rows.find((r) => r.textContent?.includes("Answer from procedures")) as HTMLElement).getByText(
        "Sonnet",
      ),
    ).toBeDefined();
  });
});

describe("AI runs tab", () => {
  it("counts failed runs, lists status, duration and cost, and opens the trace", async () => {
    show(<RunsTab />, "exec_01");
    const failed = runsJson.filter((r) => r.status === "failed").length;
    await waitFor(async () => await saysLine(`${failed} of ${runsJson.length} recent requests failed`));
    const rows = await screen.findAllByTestId("agent-run-row");
    expect(rows).toHaveLength(runsJson.length);
    expect(rows[0]?.textContent).toContain("Replay, no cost");
    const billed = runsJson.find((r) => r.billed);
    expect(rows.find((r) => r.querySelector(`[title="${billed?.run_id}"]`))?.textContent).toContain("$");
    fireEvent.click(within(rows[1] as HTMLElement).getByRole("button", { name: /Show steps/ }));
    expect((await screen.findAllByTestId("trace-step")).length).toBeGreaterThan(1);
    expect(await screen.findByText(/Open run details/, {}, { timeout: 200 }).catch(() => null)).toBeNull();
  });

  it("shows cost by model to command, executive and platform, and a quiet note to others", async () => {
    const { unmount } = show(<RunsTab />, "exec_01");
    expect(await screen.findAllByTestId("usage-row")).toHaveLength(usageJson.rows.length);
    expect(screen.getByTestId("usage-total").textContent).toContain(usd(usageJson.total.cost_usd));
    unmount();
    show(<RunsTab />, "ops_dm_01");
    expect(await screen.findByTestId("usage-hidden")).toBeDefined();
    expect((await screen.findAllByTestId("agent-run-row")).length).toBeGreaterThan(0);
  });

  it("says the run list is not on this server yet when the route is missing", async () => {
    server.use(
      http.get("/api/runs", () =>
        HttpResponse.json({ error: { code: "NOT_FOUND", message: "x" } }, { status: 404 }),
      ),
    );
    show(<RunsTab />, "exec_01");
    await saysLine("AI activity isn't available yet");
  });
});

describe("Safety tab", () => {
  it("starts with Normal operation and marks the first mode and stop level as now", async () => {
    show(<SafetyTab />, "ic_01");
    await saysLine("Normal operation");
    const modes = await screen.findAllByTestId("mode-row");
    expect(modes.filter((r) => r.getAttribute("aria-current") === "true")).toHaveLength(1);
    expect(modes[0]?.getAttribute("aria-current")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "What each stop level does" }));
    const levels = await screen.findAllByTestId("kill-level");
    expect(levels[0]?.getAttribute("aria-current")).toBe("true");
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
  });

  it("raises the stop level after a step-up password, then reads the new mode back", async () => {
    show(<SafetyTab />, "ic_01");
    fireEvent.click(await screen.findByRole("button", { name: "Raise stop level" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("New stop level"), { target: { value: "K2" } });
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Rehearsal" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Raise stop level" }));
    const password = await within(dialog).findByLabelText("Enter your password to continue");
    fireEvent.change(password, { target: { value: "demo" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await saysLine("AI stopped");
    fireEvent.click(screen.getByRole("button", { name: "What each stop level does" }));
    const now = (await screen.findAllByTestId("kill-level")).filter(
      (r) => r.getAttribute("aria-current") === "true",
    );
    expect(now[0]?.textContent).toContain("AI stopped");
    expect(
      screen.getAllByTestId("mode-row").find((r) => r.getAttribute("aria-current") === "true")?.textContent,
    ).toContain("Deterministic only");
  });

  it("refuses a wrong step-up password and keeps the dialog open", async () => {
    show(<SafetyTab />, "ic_01");
    fireEvent.click(await screen.findByRole("button", { name: "Raise stop level" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Rehearsal" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Raise stop level" }));
    fireEvent.change(await within(dialog).findByLabelText("Enter your password to continue"), {
      target: { value: "wrong" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("Wrong password");
    expect(screen.getByRole("dialog")).toBeDefined();
  });

  it("restores only with two different teams: the first signature waits, the same team cannot sign again", async () => {
    server.use(http.get("/api/me", () => HttpResponse.json(meFor(mockState.userId ?? "ic_01"))));
    const first = show(<SafetyTab />, "ic_01");
    fireEvent.click(await screen.findByRole("button", { name: "Raise stop level" }));
    let dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Rehearsal" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Raise stop level" }));
    fireEvent.change(await within(dialog).findByLabelText("Enter your password to continue"), {
      target: { value: "demo" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.click(await screen.findByRole("button", { name: "Resume" }));
    dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Checked and clear" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign to resume" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const pending = await screen.findByTestId("pending-restore");
    expect(pending.textContent).toContain("waiting for a second team to sign");
    expect((screen.getByRole("button", { name: /Sign as/ }) as HTMLButtonElement).disabled).toBe(true);
    first.unmount();

    show(<SafetyTab />, "wtr_comp_01");
    const second = (await screen.findByRole("button", { name: /Sign as/ })) as HTMLButtonElement;
    expect(second.disabled).toBe(false);
    mockState.stepUpUntil = Date.now() + 60_000;
    fireEvent.click(second);
    dialog = await screen.findByRole("dialog");
    expect((within(dialog).getByLabelText("Lower to") as HTMLSelectElement).disabled).toBe(true);
    expect(dialog.textContent).toContain("asked to lower the stop level to Normal");
    expect(dialog.textContent).not.toMatch(/ic_01|K0/);
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Second check done" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign to resume" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await saysLine("Normal operation");
    expect(screen.queryByTestId("pending-restore")).toBeNull();
  });

  it("reads an unreadable stop switch as stopped", async () => {
    server.use(
      http.get("/api/control/capabilities", () =>
        HttpResponse.json({
          kill_level: "K1",
          degraded_mode: "M0",
          control_readable: false,
          capabilities: {},
          active_signals: [],
          pending_restore: null,
          mode_ladder: [],
        }),
      ),
    );
    show(<SafetyTab />, "ic_01");
    await saysLine("Couldn't load the stop level");
  });
});
