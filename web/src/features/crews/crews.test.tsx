import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { CrewsTable } from "./CrewsTable";
import { DamageQueue, visibleMiss } from "./DamageQueue";
import { deltaPercent, reportingArea, yardName } from "./format";
import { GeneratorsContainer } from "./GeneratorsContainer";
import damage from "./mocks/damage.json";
import ladi from "./mocks/ladi-report.json";
import plan from "./mocks/plan.json";
import { PlanOptions } from "./PlanOptions";
import { thumbUrl } from "./thumbs";
import type { DamageCase } from "./types";
import { YardsContainer } from "./YardsContainer";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => resetMock());
afterEach(() => server.resetHandlers());

function show(ui: React.ReactElement, searchParams = "") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <MemoryRouter>
          <NuqsTestingAdapter searchParams={searchParams}>{ui}</NuqsTestingAdapter>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("reporting area", () => {
  const regions = [
    { region_id: "SC-45003", name: "Aiken County" },
    { region_id: "GA-13245", name: "Richmond County" },
    { region_id: "SC-45019", name: "Charleston County" },
  ];

  it("names the counties the crew roster reports from, so it is not read as the whole service area", () => {
    const crews = [{ region_id: "SC-45003" }, { region_id: "GA-13245" }, { region_id: "SC-45003" }];
    expect(reportingArea(crews, regions)).toBe("Aiken and Richmond");
    expect(reportingArea([{ region_id: "SC-45003" }], regions)).toBe("Aiken");
  });

  it("says nothing when the counties are unknown", () => {
    expect(reportingArea([{ region_id: null }, {}], regions)).toBeNull();
    expect(reportingArea([{ region_id: "SC-45003" }], undefined)).toBeNull();
  });
});

describe("format", () => {
  it("shows deltas against the baseline with a real minus sign", () => {
    expect(deltaPercent(70, 100)).toBe("−30%");
    expect(deltaPercent(108, 100)).toBe("+8.0%");
    expect(deltaPercent(100, 100)).toBe("same");
    expect(yardName("STG-AIK-SANDHILL-YARD")).toEqual({ name: "Sandhill yard", county: "AIK" });
  });
});

describe("Plan options", () => {
  it("puts the standard plan first, beside three options, with no recommendation", async () => {
    show(<PlanOptions />);
    const table = await screen.findByTestId("plan-table");
    const heads = within(table)
      .getAllByRole("columnheader")
      .map((h) => h.textContent ?? "");
    expect(heads[1]).toMatch(/^Standard plan/);
    expect(heads[2]).toMatch(/^A: Same cost, better placed/);
    expect(heads[3]).toMatch(/^B: Pre-stage for a big storm/);
    expect(heads[4]).toMatch(/^C: Own crews first/);
    expect(screen.queryByText(/recommended/i)).not.toBeInTheDocument();
  });

  it("shows expected delay, spend and the cost of idle crews from the plan document", async () => {
    show(<PlanOptions />);
    await screen.findByTestId("plan-table");
    const delay = screen.getByTestId("plan-row-expected");
    expect(within(delay).getByText("14.1 M")).toBeInTheDocument();
    expect(within(delay).getByText("9.9 M")).toBeInTheDocument();
    expect(within(delay).getByText("−30%")).toBeInTheDocument();
    expect(within(screen.getByTestId("plan-row-early")).getByText("165 crews")).toBeInTheDocument();
    expect(within(screen.getByTestId("plan-row-idle")).getByText("4,480")).toBeInTheDocument();
    expect(screen.getByTestId("plan-row-aid")).toHaveTextContent(/\$\d/);
  });

  it("keeps VSS, EVPI and the Helene gap behind Info", async () => {
    show(<PlanOptions />);
    await screen.findByTestId("plan-table");
    fireEvent.click(screen.getByRole("button", { name: "About these numbers" }));
    const { vss, evpi } = plan;
    const fmt = (n: number) => Math.round(n).toLocaleString("en-US");
    const facts = await screen.findByTestId("plan-facts");
    expect(facts).toHaveTextContent(`${fmt(vss.p50.value)} customer-hours`);
    expect(facts).toHaveTextContent(`95% range ${fmt(vss.p50.ci_low)} to ${fmt(vss.p50.ci_high)}`);
    expect(facts).toHaveTextContent(`${fmt(evpi.out_of_sample)}`);
    expect(screen.getByTestId("plan-caveat")).toHaveTextContent(
      "the real need is 4.3 times the median forecast, outside the 0.45 to 2.21 times the plans were built for",
    );
  });

  it("preselects no option and keeps the yard limits in the one Info", async () => {
    show(<PlanOptions />);
    await screen.findByTestId("plan-table");
    expect(screen.queryByText("Selected")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("button", { pressed: true })).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "About these numbers" }));
    expect(await screen.findByTestId("plan-limits")).toHaveTextContent("±20% per yard");
  });

  it("shows an error state when the plan does not load", async () => {
    server.use(http.get("/api/crews/plan", () => new HttpResponse(null, { status: 500 })));
    show(<PlanOptions />);
    expect(await screen.findByText("Couldn't load the crew plan.")).toBeInTheDocument();
  });
});

describe("Staging yards", () => {
  it("shows the crews each option puts at every yard, side by side, with nothing selected", async () => {
    show(<YardsContainer />);
    const rows = await screen.findAllByTestId("yard-row");
    expect(rows).toHaveLength(11);
    const heads = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toEqual(["Yard", "Crews now", "Standard", "A", "B", "C"]);
    const sandhill = rows.find((r) => r.textContent?.includes("Sandhill")) as HTMLElement;
    const yard = plan.plans.find((p) => p.plan_id === "COA-A")?.yards["STG-AIK-SANDHILL-YARD"];
    expect(sandhill).toHaveTextContent(String((yard?.own_groups ?? 0) + (yard?.mutual_aid_groups ?? 0)));
    expect(rows.some((r) => r.getAttribute("aria-current") === "true")).toBe(false);
  });

  it("marks the yard a link points to", async () => {
    show(<YardsContainer focus="STG-RCH-MILLPOND-YARD" />);
    const rows = await screen.findAllByTestId("yard-row");
    const marked = rows.filter((r) => r.getAttribute("aria-current") === "true");
    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveTextContent("Millpond yard");
  });
});

describe("Crews table", () => {
  it("sorts by a column header and exposes the sort state", async () => {
    show(<CrewsTable />);
    await screen.findByRole("table", { name: "Crews (sortable)" });
    const ids = () => screen.getAllByTestId("crew-row").map((r) => r.getAttribute("data-row-id"));
    expect(ids()[0]).toBe("CRW-HARRIER-0103");
    const sortState = () => screen.getByRole("columnheader", { name: /People/ }).getAttribute("aria-sort");
    fireEvent.click(screen.getByRole("button", { name: /People/ }));
    await waitFor(() => expect(sortState()).toBe("ascending"));
    expect(screen.getAllByTestId("crew-row").at(-1)).toHaveTextContent("Talon 11");
    fireEvent.click(screen.getByRole("button", { name: /People/ }));
    await waitFor(() => expect(sortState()).toBe("descending"));
    expect(screen.getAllByTestId("crew-row")[0]).toHaveTextContent("Talon 11");
  });

  it("names the field system's destination for a crew on the way without an SGW assignment", async () => {
    server.use(
      http.get("/api/crews", () =>
        HttpResponse.json([
          {
            crew_id: "CRW-MA-BITTERN-0108",
            status: "enroute",
            location_id: "FDR-ALLS-2201",
            headcount: 40,
            shift_end: null,
            provenance: {
              source: "fsm-crews",
              model_id: null,
              rule_id: null,
              as_of: "2024-09-27T10:05:00Z",
              label: "S",
            },
            region_id: "SC-45003",
            assignment: null,
            block_reason: null,
            actions: ["assign", "block"],
          },
        ]),
      ),
    );
    show(<CrewsTable />);
    const row = await screen.findByTestId("crew-row");
    const assigned = within(row).getByTestId("crew-assigned");
    expect(assigned).not.toHaveTextContent("—");
    expect(assigned).toHaveAttribute("title", "Sent there by the field system");
  });

  it("says when no crew is reporting", async () => {
    server.use(http.get("/api/crews", () => HttpResponse.json([])));
    show(<CrewsTable />);
    expect(await screen.findByText("No crews have reported yet.")).toBeInTheDocument();
  });
});

describe("Generators", () => {
  it("lists generators with the hook-up and fuel delivery times from the numbers file", async () => {
    show(<GeneratorsContainer />);
    const rows = await screen.findAllByTestId("generator-row");
    expect(rows).toHaveLength(4);
    expect(screen.getByText("2 h 30 m")).toBeInTheDocument();
    expect(screen.getByText("1 h 30 m")).toBeInTheDocument();
    expect(screen.getByText("Halberd generator").closest("tr")).toHaveTextContent("Portable");
  });
});

describe("Damage assessment queue", () => {
  const cases = damage.cases as DamageCase[];

  it("names the one visible miss from the data, not from a hard-coded string", () => {
    const miss = visibleMiss(cases);
    expect(miss?.caseId).toBe("D2-GENERATOR-FAILS-H30");
    expect(miss?.text).toBe(
      "The worst-damaged case (complete, section FDR-AIK-2214-S1) ranks only 4th of 4 damaged cases.",
    );
    const fixed = cases.map((c) => (c.case_id === "D2-GENERATOR-FAILS-H30" ? { ...c, case_rank: 0 } : c));
    expect(visibleMiss(fixed)).toBeNull();
  });

  it("orders cases by score in two tiers and states the miss and the tier check", async () => {
    show(<DamageQueue />);
    const rows = await screen.findAllByTestId("damage-case");
    expect(
      rows.map(
        (r) =>
          r
            .querySelector("[title]")
            ?.getAttribute("title")
            ?.match(/score (\d\.\d\d)/)?.[1],
      ),
    ).toEqual(["0.38", "0.32", "0.23", "0.20", "0.04", "0.02"]);
    expect(rows[3]).toHaveAttribute("data-miss", "true");
    fireEvent.click(screen.getByRole("button", { name: "About the damage model" }));
    expect(await screen.findByTestId("visible-miss")).toHaveTextContent("ranks only 4th of 4 damaged cases");
    expect(screen.getByTestId("visible-miss")).toHaveTextContent("4 of 13 pairs are in the wrong order");
    expect(screen.getByTestId("two-tier")).toHaveTextContent("Two checks pass: every moderate-or-worse case");
    expect(screen.getByTestId("two-tier")).toHaveTextContent("lowest 0.20, controls up to 0.13");
    expect(screen.getByTestId("damage-note")).toHaveTextContent("not SGW territory");
  });

  it("shows five repo thumbnails per case and a provenance line with the published accuracy", async () => {
    show(<DamageQueue />);
    await screen.findAllByTestId("damage-case");
    const first = screen.getAllByTestId("damage-case")[0] as HTMLElement;
    expect(within(first).getAllByRole("button", { name: /^Open photo/ })).toHaveLength(5);
    expect(within(first).getByTestId("case-review")).toHaveTextContent("Waiting for review");
    expect(thumbUrl("ladi-v2-test-0006")).toBe("/api/damage/thumbs/ladi-v2-test-0006");
    const reference = ladi.metrics.find((m) => m.metric === "ladi_v2.small_reference.test_map");
    fireEvent.click(screen.getByRole("button", { name: "About the damage model" }));
    expect(
      await screen.findByText(
        new RegExp(`published score ${reference?.value.toFixed(1)} \\(mAP, not measured by SGW\\)`),
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/CC BY 4\.0/)).toBeInTheDocument();
  });

  it("switches to the highest-scoring photos with their signals and suggested action", async () => {
    show(<DamageQueue />);
    await screen.findAllByTestId("damage-case");
    fireEvent.click(screen.getByRole("radio", { name: "Photos" }));
    const photos = await screen.findAllByTestId("damage-photo");
    expect(photos).toHaveLength(12);
    expect(photos[0]).toHaveTextContent("Tree damage");
    expect(within(photos[0] as HTMLElement).queryByRole("link")).not.toBeInTheDocument();
  });

  it("opens a photo in the preview with its scores, moves with the arrow keys and closes on Escape", async () => {
    show(<DamageQueue />);
    await screen.findAllByTestId("damage-case");
    fireEvent.click(screen.getAllByRole("button", { name: /^Open photo/ })[0] as HTMLElement);
    const preview = await screen.findByTestId("photo-preview");
    expect(await within(preview).findByTestId("photo-full")).toHaveAttribute(
      "src",
      "/api/damage/thumbs/ladi-v2-test-0006",
    );
    expect(within(preview).getByRole("list", { name: "What the model sees" })).toHaveTextContent("%");
    expect(within(preview).getByText(/1 of \d+/)).toBeInTheDocument();
    expect(within(preview).queryByRole("link")).not.toBeInTheDocument();
    fireEvent.keyDown(preview, { key: "ArrowRight" });
    await waitFor(() =>
      expect(within(preview).getByTestId("photo-full")).toHaveAttribute(
        "src",
        "/api/damage/thumbs/ladi-v2-test-0034",
      ),
    );
    fireEvent.keyDown(preview, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("photo-preview")).not.toBeInTheDocument());
  });

  it("opens the photo a link names (?photo=), as Ask's photo links do", async () => {
    show(<DamageQueue />, "?photo=ladi-v2-test-0034");
    const preview = await screen.findByTestId("photo-preview");
    expect(await within(preview).findByTestId("photo-full")).toHaveAttribute(
      "src",
      "/api/damage/thumbs/ladi-v2-test-0034",
    );
  });

  it("shows an empty state when nothing waits for review", async () => {
    server.use(http.get("/api/damage/queue", () => HttpResponse.json({ ...damage, cases: [] })));
    show(<DamageQueue />);
    expect(await screen.findByText("No photos are waiting for review.")).toBeInTheDocument();
  });
});
