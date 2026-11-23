import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NuqsAdapter } from "nuqs/adapters/react-router/v8";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ScenarioMenu } from "@/app/layout/ScenarioMenu";
import { api } from "@/lib/api";
import { mockState, resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { peakIndex, redFlagHours, unitsInWarning, windowText } from "./hazardModel";
import { heatLibrary, wildfireLibrary } from "./mocks";
import ReadinessPage from "./ReadinessPage";
import { ReadinessTabs } from "./ReadinessTabs";

vi.mock("@/sse/OpsStreamProvider", () => ({ useOpsRestart: () => vi.fn(), useOps: () => ({}) }));
vi.mock("@/sse/useScenarioNow", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/sse/useScenarioNow")>();
  return { ...actual, useScenarioNow: () => actual.useScenario().data?.scenario_time ?? null };
});

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  mockState.userId = "exec_01";
});
afterEach(() => {
  server.resetHandlers();
  window.history.replaceState(null, "", "/");
});

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{`${loc.pathname}${loc.search}`}</output>;
}

function show(entry: string, extra?: React.ReactNode) {
  window.history.replaceState(null, "", entry);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <NuqsAdapter>
          {extra}
          <Routes>
            <Route path="/readiness" element={<ReadinessPage />} />
            <Route path="*" element={<p>elsewhere</p>} />
          </Routes>
          <Where />
        </NuqsAdapter>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("hazard library model", () => {
  it("reads the window in Eastern days with an exclusive end", () => {
    expect(windowText(heatLibrary.window_start_utc, heatLibrary.window_end_utc)).toBe("13–17 Jul 2024");
    expect(windowText(wildfireLibrary.window_start_utc, wildfireLibrary.window_end_utc)).toBe(
      "19–24 Mar 2025",
    );
  });

  it("counts units in warning, Red Flag hours and the peak index from the API values", () => {
    expect(unitsInWarning(heatLibrary)).toBe(3);
    expect(redFlagHours(wildfireLibrary)).toBe(11);
    expect(Math.round(peakIndex(wildfireLibrary))).toBe(61);
  });
});

describe("heat wave view", () => {
  it("opens from ?view=heat with one chart, one table and one action", async () => {
    show("/readiness?view=heat");
    expect(await screen.findByTestId("heat-chart")).toBeInTheDocument();
    const summary = screen.getByTestId("heat-summary");
    expect(summary.textContent).toContain("35.0 °C");
    expect(summary.textContent).toContain("3 of 5 units in warning");
    expect(summary.textContent).toContain("113% line load in still air");
    expect(screen.getAllByTestId("heat-unit-row")).toHaveLength(5);
    expect(screen.getAllByTestId("heat-unit-row")[0]?.textContent).toContain("Copperleaf transformer");
    const action = screen.getByTestId("heat-action");
    expect(within(action).getByTestId("action-title").textContent).toContain("feeder 2219");
    expect(within(action).getByTestId("action-signers").textContent).toBe("Operations");
    expect(within(action).queryByRole("button", { name: /^(sign|approve)\b/i })).toBeNull();
    expect(screen.getByRole("tab", { name: "Heat wave", selected: true })).toBeInTheDocument();
  });

  it("labels real ASOS input and synthetic output, with the files in Sources", async () => {
    show("/readiness?view=heat");
    await screen.findByTestId("heat-chart");
    const tags = screen.getAllByTestId("origin-tag").map((t) => t.getAttribute("data-origin"));
    expect(tags).toEqual(["real", "synthetic"]);
    fireEvent.click(screen.getByTestId("hazard-info"));
    const sources = await screen.findByTestId("hazard-sources");
    expect(sources.textContent).toContain("data/fixtures/heat/asos_5stn_daily.csv");
    expect(sources.textContent).toContain("data/fixtures/heat/hot_spot.csv");
    expect(within(sources).getAllByText("Real")).toHaveLength(2);
    expect(within(sources).getAllByText("Synthetic")).toHaveLength(2);
  });

  it("says so when the view does not load instead of showing an empty view", async () => {
    server.use(
      http.get("/api/hazards/library/heat", () =>
        HttpResponse.json({ error: { code: "FORBIDDEN", message: "no" } }, { status: 403 }),
      ),
    );
    show("/readiness?view=heat");
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load the heat wave.");
    expect(screen.queryByTestId("heat-chart")).toBeNull();
  });
});

describe("wildfire weather view", () => {
  it("opens from ?view=wildfire with the fire index chart, ten circuits and the Red Flag protocol", async () => {
    show("/readiness?view=wildfire");
    expect(await screen.findByTestId("fire-chart")).toBeInTheDocument();
    const summary = screen.getByTestId("wildfire-summary");
    expect(summary.textContent).toContain("2 Red Flag periods");
    expect(summary.textContent).toContain("11 h");
    expect(summary.textContent).toContain("0.69 expected ignitions");
    const rows = screen.getAllByTestId("wildfire-circuit-row");
    expect(rows).toHaveLength(10);
    expect(rows[0]?.textContent).toContain("Feeder 2218");
    expect(rows[0]?.textContent).toContain("Pickens");
    expect(rows[0]?.textContent).toContain("1.35%");
    const action = screen.getByTestId("wildfire-action");
    expect(within(action).getByTestId("action-title").textContent).toContain("Red Flag work rules");
    expect(within(action).getByTestId("action-also").textContent).toContain("Not recommended");
    expect(within(action).getByTestId("wildfire-why").textContent).toContain("13,845 acres");
  });

  it("switches back to the pre-season checks from the tab row and clears the view", async () => {
    const updates: string[] = [];
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <NuqsTestingAdapter searchParams="?view=wildfire" onUrlUpdate={(e) => updates.push(e.queryString)}>
            <ReadinessTabs />
          </NuqsTestingAdapter>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("tab", { name: "Wildfire weather", selected: true })).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Pre-season" }), { button: 0 });
    await waitFor(() => expect(updates.at(-1)).toBe(""));
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Heat wave" }), { button: 0 });
    await waitFor(() => expect(updates.at(-1)).toBe("?view=heat"));
  });
});

describe("other scenarios in the scenario menu", () => {
  it("opens a hazard view in Readiness and never moves the replay clock", async () => {
    await api.login("ops_dm_01", "demo");
    const posts: string[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.method !== "GET") posts.push(new URL(request.url).pathname);
    });
    show("/", <ScenarioMenu />);
    fireEvent.click(await screen.findByTestId("mode-strip"));
    const group = await screen.findByTestId("other-scenarios");
    expect(within(group).getByRole("link", { name: /^Heat/ })).toHaveAttribute(
      "href",
      "/readiness?view=heat",
    );
    expect(within(group).getByRole("link", { name: /^Wildfire/ })).toHaveAttribute(
      "href",
      "/readiness?view=wildfire",
    );
    fireEvent.click(within(group).getByRole("link", { name: /^Wildfire/ }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/readiness?view=wildfire"));
    expect(screen.queryByTestId("jump-dialog")).toBeNull();
    expect(posts.filter((p) => p.includes("scenario") || p.includes("clock"))).toEqual([]);
    server.events.removeAllListeners();
  });
});
