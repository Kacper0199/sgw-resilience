import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ProposalCard } from "@/lib/api";
import { MOCK_NOW } from "@/mocks/fixtures";
import { mockState, resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { AdvisoryContainer } from "./AdvisoryContainer";
import { ClocksContainer } from "./ClocksContainer";
import { anomalyLabel, backupPower, generatorOrdered, percentPpm, psi, zoneName } from "./format";
import { replayAnomalies } from "./mocks";
import { SensorContainer } from "./SensorContainer";
import { orderCases } from "./useWater";
import { ZonesContainer } from "./ZonesContainer";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  mockState.userId = "wtr_lead_01";
});
afterEach(() => server.resetHandlers());

function show(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <NuqsTestingAdapter>
          <MemoryRouter>{ui}</MemoryRouter>
        </NuqsTestingAdapter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("format", () => {
  it("turns zone ids, tenths of psi and ppm into plain labels", () => {
    expect(zoneName("WZ-PS17-CEDARFALL")).toBe("Cedarfall");
    expect(psi(620)).toBe("62.0 psi");
    expect(percentPpm(81137)).toBe("8.1%");
    expect(percentPpm(152482)).toBe("15.2%");
    expect(anomalyLabel("pressure_level_inconsistent")).toBe("Pressure and tank level disagree");
    expect(anomalyLabel("some_new_class")).toBe("Some new class");
  });
});

describe("Backup power", () => {
  const zone = {
    zone_id: "WZ-PS52-DEERWATER",
    pump_station_id: "PS-52",
    pressure_psi_x10: 620,
    floor_psi_x10: 250,
    critical_facility_ids: [],
    on_backup_power: false,
  };

  it("names a station's own generator instead of reporting no backup power", () => {
    expect(backupPower({ ...zone, onsite_generator_id: "GEN-PS52-DEERWATER" })).toEqual({
      label: "Generator on site",
      warn: false,
    });
    expect(backupPower({ ...zone, onsite_generator_id: null })).toEqual({
      label: "No backup power",
      warn: true,
    });
    expect(backupPower(zone)).toEqual({ label: "No backup power", warn: true });
  });

  it("says an executed generator hookup is not running yet instead of no backup power", () => {
    const hookup = { state: "executed", params: { station_id: "PS-17", generator_id: "MGEN-HALBERD-500" } };
    expect(generatorOrdered("PS-17", [hookup])).toBe(true);
    expect(generatorOrdered("PS-17", [{ ...hookup, state: "approved" }])).toBe(false);
    expect(backupPower({ ...zone, onsite_generator_id: null }, true)).toEqual({
      label: "Generator not running yet",
      warn: true,
    });
  });

  it("follows the generator's reported state", () => {
    const own = { ...zone, onsite_generator_id: "GEN-PS52-DEERWATER" };
    expect(backupPower({ ...own, on_backup_power: true, generator_state: "running" })).toEqual({
      label: "On backup power",
      warn: false,
    });
    expect(backupPower({ ...own, generator_state: "failed_run" })).toEqual({
      label: "Generator failed",
      warn: true,
    });
    expect(backupPower({ ...own, generator_state: "out_of_fuel" })).toEqual({
      label: "Generator out of fuel",
      warn: true,
    });
    expect(backupPower({ ...own, generator_state: "standby" })).toEqual({
      label: "Generator on site",
      warn: false,
    });
  });
});

describe("Pressure zones", () => {
  it("lists every zone with pressure against its minimum, and opens the abnormal zone with its steps", async () => {
    show(<ZonesContainer now={MOCK_NOW} />);
    const rows = await screen.findAllByTestId("zone-row");
    expect(rows).toHaveLength(4);
    const cedarfall = rows[0] as HTMLElement;
    expect(within(cedarfall).getByText("62.0 psi")).toBeInTheDocument();
    expect(within(cedarfall).queryByText(/minimum/)).not.toBeInTheDocument();
    expect(within(cedarfall).getByText("No backup power")).toBeInTheDocument();
    expect(cedarfall.getAttribute("data-row-id")).toBe("WZ-PS17-CEDARFALL");
    const detail = await screen.findByTestId("zone-detail");
    expect(within(detail).getByText("Next steps for Cedarfall")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        within(detail).getByRole("link", { name: /View decision: Send the fuel truck/ }),
      ).toHaveAttribute("href", "/?d=PRP-PS17-FUEL"),
    );
    expect(within(detail).getByText("Boil-water notice")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("Generator on site")).toBeInTheDocument();
    expect(screen.queryAllByTestId("zone-detail")).toHaveLength(1);
    fireEvent.click(rows[2] as HTMLElement);
    expect(
      await screen.findByText("Pressure is above the minimum. No open decision for Copperleaf."),
    ).toBeInTheDocument();
  });

  it("says so when a zone is below its minimum", async () => {
    server.use(
      http.get("/api/water/zones", () =>
        HttpResponse.json([
          {
            zone_id: "WZ-PS23-LAURELSPUR",
            pump_station_id: "PS-23",
            pressure_psi_x10: 183,
            floor_psi_x10: 250,
            critical_facility_ids: [],
            on_backup_power: false,
          },
        ]),
      ),
    );
    show(<ZonesContainer now={MOCK_NOW} />);
    expect(await screen.findByText("Below minimum (25.0 psi)")).toBeInTheDocument();
    expect(screen.getByText("18.3 psi")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /last 6 h/ })).not.toBeInTheDocument();
  });

  it("draws a pressure line only when the zone carries real history", async () => {
    server.use(
      http.get("/api/water/zones", () =>
        HttpResponse.json([
          {
            zone_id: "WZ-PS23-LAURELSPUR",
            pump_station_id: "PS-23",
            pressure_psi_x10: 620,
            floor_psi_x10: 250,
            critical_facility_ids: [],
            on_backup_power: true,
            pressure_history_psi_x10: [626, 624, 623, 621, 620, 620],
          },
          {
            zone_id: "WZ-PS38-COPPERLEAF",
            pump_station_id: "PS-38",
            pressure_psi_x10: 620,
            floor_psi_x10: 250,
            critical_facility_ids: [],
            on_backup_power: true,
          },
        ]),
      ),
    );
    show(<ZonesContainer now={MOCK_NOW} />);
    await screen.findAllByTestId("zone-row");
    expect(screen.getAllByRole("img", { name: /last 6 h/ })).toHaveLength(1);
    expect(screen.getByRole("img", { name: "Pressure in Laurelspur, last 6 h" })).toBeInTheDocument();
  });

  it("shows an error state, not an empty table, when the API fails", async () => {
    server.use(http.get("/api/water/zones", () => new HttpResponse(null, { status: 500 })));
    show(<ZonesContainer now={MOCK_NOW} />);
    expect(await screen.findByText("Couldn't load pressure zones.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("PS-17 clocks", () => {
  const card = (
    id: string,
    caseId: string,
    path: boolean,
    prereq: string[],
    decideBy: string,
  ): ProposalCard => {
    const base = mockState.cards.find((c) => c.decision_case_id === "DC-D3-PS17-POWER") as ProposalCard;
    return {
      ...base,
      proposal_id: id,
      decision_case_id: caseId,
      effective_decide_by_utc: decideBy,
      case: { ...base.case, decision_case_id: caseId, on_critical_path: path, prerequisite_ids: prereq },
    };
  };

  it("orders the critical path by prerequisite, not by clock, and keeps other cases apart", () => {
    const fuel = card("A", "DC-FUEL", true, [], "2024-09-28T14:59:00Z");
    const power = card("B", "DC-POWER", true, ["DC-FUEL"], "2024-09-27T03:29:00Z");
    const pressure = card("C", "DC-PRESSURE", true, ["DC-POWER"], "2024-09-27T05:59:00Z");
    const other = card("D", "DC-OTHER", false, [], "2024-09-27T02:00:00Z");
    const { chain, others } = orderCases([pressure, other, power, fuel]);
    expect(chain.map((c) => c.proposal_id)).toEqual(["A", "B", "C"]);
    expect(others.map((c) => c.proposal_id)).toEqual(["D"]);
  });

  it("numbers the chain and links into each decision", async () => {
    show(<ClocksContainer now={MOCK_NOW} />);
    const items = await screen.findAllByTestId("water-case");
    expect(items.length).toBeGreaterThanOrEqual(4);
    const chain = screen.getByRole("list", { name: "Critical path, in order" });
    const steps = within(chain).getAllByTestId("water-case");
    expect(steps).toHaveLength(3);
    expect(within(steps[0] as HTMLElement).getByText("in 59 m")).toBeInTheDocument();
    expect(within(steps[1] as HTMLElement).getByText("in 2 h 29 m")).toBeInTheDocument();
    expect(within(steps[1] as HTMLElement).getByRole("link", { name: /^View decision/ })).toHaveAttribute(
      "href",
      "/?d=PRP-PS17-FDR2207-PRIO",
    );
  });

  it("shows an empty state when no water decision is open", async () => {
    server.use(http.get("/api/proposals", () => HttpResponse.json([])));
    show(<ClocksContainer now={MOCK_NOW} />);
    expect(await screen.findByText("No open water decisions.")).toBeInTheDocument();
  });
});

describe("Boil-water notices", () => {
  it("shows the previous and latest chance against the policy trigger from the API", async () => {
    show(<AdvisoryContainer now={MOCK_NOW} />);
    const strip = await screen.findByTestId("probability-strip");
    expect(strip).toHaveAttribute(
      "aria-label",
      "Previous advisory 05:00 ET 8.1%, latest advisory 11:00 ET 15.2%, notice trigger 10%, crossed",
    );
    const why = screen.getByTestId("bwa-why");
    expect(within(why).getByText("27.0% → 44.2%")).toBeInTheDocument();
    expect(within(why).getByText("30.0% → 34.5%")).toBeInTheDocument();
    expect(within(why).getByText("6.5%")).toBeInTheDocument();
  });

  it("cites the SC clauses on the row and the whole rule book (SC and GA) one click away", async () => {
    show(<AdvisoryContainer now={MOCK_NOW} />);
    const cards = await screen.findAllByTestId("clause-card");
    expect(cards.map((c) => within(c).getAllByRole("button")[0]?.textContent)).toEqual([
      "Advisory before landfallSouth Carolina",
      "Normal service pressureSouth Carolina",
    ]);
    fireEvent.click(screen.getByRole("button", { name: /All rules/ }));
    expect(await screen.findByRole("radio", { name: /South Carolina/ })).toHaveTextContent("11");
    expect(screen.getByRole("radio", { name: /Georgia/ })).toHaveTextContent("4");
    fireEvent.click(screen.getByRole("radio", { name: /Georgia/ }));
    expect(await screen.findByText("Advisory after pressure loss")).toBeInTheDocument();
  });

  it("opens the first rule, folds it again and keeps the decision links", async () => {
    show(<AdvisoryContainer now={MOCK_NOW} />);
    const toggle = await screen.findByRole("button", { name: /Advisory before landfall/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /Normal service pressure/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(
      screen.getByRole("link", { name: /^View decision: Boil-water notice, Cedarfall/ }),
    ).toHaveAttribute("href", "/?d=PRP-BWN-READY");
    expect(screen.getByText("Waiting for sign-off")).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("does not draw a trigger mark when the policy is not available", async () => {
    server.use(http.get("/api/policies", () => new HttpResponse(null, { status: 500 })));
    show(<AdvisoryContainer now={MOCK_NOW} />);
    const strip = await screen.findByTestId("probability-strip");
    expect(strip.getAttribute("aria-label")).toBe(
      "Previous advisory 05:00 ET 8.1%, latest advisory 11:00 ET 15.2%",
    );
  });
});

describe("Boil-water notices the reader cannot load", () => {
  const forbidden = () =>
    HttpResponse.json(
      { error: { code: "WATER_DOMAIN_REQUIRED", message: "the register is shown to water", details: {} } },
      { status: 403 },
    );

  it("says there is no access instead of 'no notice is due' on a 403", async () => {
    server.use(http.get("/api/water/advisories", forbidden));
    show(<AdvisoryContainer now={MOCK_NOW} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You don't have access to boil-water notices.",
    );
    expect(screen.queryByText(/No boil-water notice is due/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("says the notices did not load on a 5xx, with a retry", async () => {
    server.use(http.get("/api/water/advisories", () => new HttpResponse(null, { status: 503 })));
    show(<AdvisoryContainer now={MOCK_NOW} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load boil-water notices.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("Sensor checks", () => {
  it("states the measured recall as below target and shows where it misses, worst first", async () => {
    show(<SensorContainer />);
    expect(await screen.findByTestId("recall-statement")).toHaveTextContent(
      "Caught 82 of 115 test faults (71%). Below the 80% target.",
    );
    expect(screen.getByTestId("measure-bar")).toHaveAttribute(
      "aria-label",
      "Measured 71%, 95% range 62% to 79%, target 80%, Alarm only 15%",
    );
    const rows = screen.getAllByTestId("fault-row");
    expect(rows).toHaveLength(6);
    expect(rows[0]).toHaveTextContent("Hidden leak (tank stays full)");
    expect(rows[0]).toHaveTextContent("4 of 23");
    expect(rows[5]).toHaveTextContent("Pump trip");
    expect(screen.getByText(/needs flow metering/)).toBeInTheDocument();
    expect(screen.getByText("24 of 36")).toBeInTheDocument();
    expect(screen.getByText("target: all flagged")).toBeInTheDocument();
  });

  it("lists open alerts once the detectors have raised them", async () => {
    server.use(http.get("/api/anomalies", () => HttpResponse.json(replayAnomalies)));
    show(<SensorContainer />);
    const list = await screen.findByRole("list", { name: "Open sensor alerts" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(within(list).getAllByText("Pressure loss")).toHaveLength(2);
    expect(within(list).getByText("PT-PS17-DISCH")).toBeInTheDocument();
  });

  it("shows no alerts before the first detection", async () => {
    show(<SensorContainer />);
    expect(await screen.findByText("No sensor needs attention right now.")).toBeInTheDocument();
  });
});
