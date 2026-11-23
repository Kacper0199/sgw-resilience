import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import type * as React from "react";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { server } from "@/mocks/server";
import { Lifelines } from "../map/Lifelines";
import { facilityDecisions } from "../map/lifelineSummary";
import { BacktestTab } from "./BacktestTab";
import { CountiesTab } from "./CountiesTab";
import { forecastPeak } from "./data";
import { PlanChangeTab } from "./PlanChangeTab";
import { WhatIfTab } from "./WhatIfTab";

vi.mock("./FanChart", () => ({
  FanChart: ({ counties }: { counties: { name: string }[] }) => (
    <ul data-testid="fan-chart-stub">
      {counties.map((c) => (
        <li key={c.name}>{c.name}</li>
      ))}
    </ul>
  ),
}));

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
afterEach(() => server.resetHandlers());

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <NuqsTestingAdapter>
        <MemoryRouter>{ui}</MemoryRouter>
      </NuqsTestingAdapter>
    </QueryClientProvider>,
  );
}

describe("plan change", () => {
  it("shows the PS-17 share moving from 13 to 37 of 40 scenarios and the act-now line", async () => {
    wrap(<PlanChangeTab advisory="N+1" />);
    const row = (await screen.findAllByTestId("plan-action")).find((r) =>
      r.textContent?.includes("portable generator"),
    );
    expect(row).toBeDefined();
    expect(row?.textContent).toContain("13 of 40 scenarios");
    expect(row?.textContent).toContain("37 of 40 scenarios");
    expect(within(row as HTMLElement).getByTestId("crossed").textContent).toContain("(32 of 40)");
    expect(screen.getAllByTestId("delta")[0]?.textContent).toBe("+301,558");
  });

  it("says there is nothing to compare for the first advisory, without asking the API", async () => {
    const asked: string[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.url.includes("/plan-diff")) asked.push(request.url);
    });
    wrap(<PlanChangeTab advisory="N-7" />);
    expect(await screen.findByText(/First advisory/)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    server.events.removeAllListeners();
    expect(asked).toEqual([]);
  });
});

describe("forecast peak", () => {
  it("sums the county medians, the same definition the Briefing uses", () => {
    const fan = (q0500: number, mean: number) => ({
      q0500,
      mean,
      q0025: 0,
      q0100: 0,
      q0250: 0,
      q0750: 0,
      q0900: 0,
      q0975: 0,
      fips: "1",
      name: "A",
      customers: 1,
    });
    expect(forecastPeak([fan(10, 40), fan(5, 20)])).toBe(15);
  });
});

describe("what if", () => {
  it("lists the baseline and the three scenarios with their change from the baseline", async () => {
    wrap(<WhatIfTab />);
    const rows = await screen.findAllByTestId("whatif-row");
    expect(rows).toHaveLength(4);
    expect(rows[1]?.textContent).toContain("Storm track 40 km further east");
    expect(rows[1]?.textContent).toContain("+17%");
    expect(rows[3]?.textContent).toContain("same as baseline");
  });
});

describe("backtest tab", () => {
  it("puts the table before the summary and keeps the caveat from the report", async () => {
    wrap(<BacktestTab />);
    const table = await screen.findByTestId("backtest-table");
    const summary = screen.getAllByTestId("backtest-summary")[0] as HTMLElement;
    expect(table.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(table).getAllByTestId("backtest-row")).toHaveLength(4);
    expect(screen.getByTestId("coverage-caveat").textContent).toContain("Helene: 29%");
  });

  it("reads the 24-storm report in the same table", async () => {
    wrap(<BacktestTab report="outage_loso_v2" />);
    expect(await screen.findAllByTestId("backtest-row")).toHaveLength(24);
    const under = screen
      .getAllByTestId("backtest-summary")
      .find((r) => r.textContent?.includes("forecast total fell below"));
    expect(under?.textContent).toContain("Below target");
  });

  it("says so when the report is not served on this stack", async () => {
    server.use(
      http.get("/api/models/:name/evaluation", () =>
        HttpResponse.json({ error: { code: "NOT_FOUND", message: "no" } }, { status: 404 }),
      ),
    );
    wrap(<BacktestTab />);
    expect(await screen.findByText(/The track record isn't available yet/)).toBeInTheDocument();
  });
});

describe("counties", () => {
  it("charts the 12 counties with the highest 80% upper bound", async () => {
    wrap(<CountiesTab advisory="N+1" />);
    const chart = await screen.findByTestId("fan-chart-stub");
    expect(within(chart).getAllByRole("listitem")).toHaveLength(12);
    expect(within(chart).getAllByRole("listitem")[0]?.textContent).toBe("Greenville");
  });

  it("once observed titles the tab forecast vs actual and adds the actual peak per county", async () => {
    wrap(<CountiesTab advisory="N+1" observed />);
    expect(
      await screen.findByText(/Forecast vs actual: the 12 counties forecast to be hit hardest/),
    ).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Actual/ })).toBeInTheDocument();
    expect(screen.queryByText(/at most risk/)).toBeNull();
  });

  it("explains an advisory without a forecast", async () => {
    wrap(<CountiesTab advisory="N+99" />);
    expect(await screen.findByText(/No county forecast for this advisory yet/)).toBeInTheDocument();
  });
});

describe("lifelines", () => {
  it("counts the lifelines and lists the critical facilities with their county risk", async () => {
    wrap(<Lifelines asOf="2024-09-26T15:00:00Z" />);
    const panel = await screen.findByTestId("lifelines");
    await waitFor(() => expect(within(panel).getByText("Water pump stations")).toBeInTheDocument());
    expect(within(panel).getByText("PS-17")).toBeInTheDocument();
    await waitFor(() => expect(within(panel).getAllByText(/outage risk$/).length).toBeGreaterThan(0));
    expect(screen.queryByTestId("riskiest-counties")).toBeNull();
  });
});

describe("open decisions at a facility", () => {
  const item = (id: string, target_ids: string[], params: Record<string, unknown> = {}) => ({
    id,
    card: { target_ids, params } as never,
  });
  const generator = item("PS-17 generator", ["PS-17"]);
  const tanker = item("hospital tanker", ["WTK-CORDGRASS-2"], { destination_id: "HSP-AIK-TALLOWBRANCH" });

  it("links the hospital to its own water decision, not the pump station's", () => {
    const found = facilityDecisions("HSP-AIK-TALLOWBRANCH", ["PS-17"], [generator, tanker]);
    expect(found.map((i) => i.id)).toEqual(["hospital tanker"]);
  });

  it("falls back to the serving pump station when nothing acts on the facility", () => {
    const found = facilityDecisions("HSP-AIK-TALLOWBRANCH", ["PS-17"], [generator]);
    expect(found.map((i) => i.id)).toEqual(["PS-17 generator"]);
  });
});
