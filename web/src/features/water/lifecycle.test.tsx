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
import {
  NOTICE_STEPS,
  noticeLifecycle,
  noticesInOrder,
  waitingForSignOff,
  type ZoneNotice,
} from "./lifecycle";
import { NoticeStepper } from "./NoticeStepper";
import type { BwaAdvisory } from "./types";
import { ZonesContainer } from "./ZonesContainer";

const zone = (id: string) => ({ zone_id: id });
const WZ = "WZ-PS23-LAURELSPUR";

function card(
  action: ProposalCard["action_type"],
  state: ProposalCard["state"],
  extra: Partial<ProposalCard> = {},
) {
  const base = mockState.cards[0] as ProposalCard;
  return {
    ...base,
    proposal_id: `${action}-${state}`,
    action_type: action,
    state,
    target_ids: [WZ],
    params: {},
    effective_decide_by_utc: "2024-09-27T13:17:00Z",
    ...extra,
  } as ProposalCard;
}

function row(stage: BwaAdvisory["stage"], extra: Partial<BwaAdvisory> = {}): BwaAdvisory {
  return {
    advisory_id: `BWA-${WZ}-PRESSURELOSS`,
    state: "SC",
    zone_id: WZ,
    station_id: "PS-23",
    kind: "pressure_loss",
    clause_ids: ["SC-A1", "SC-P1"],
    policy_key: "policy_pre_landfall_breach_p",
    assessments: [],
    sensitivity: [],
    due_utc: "2024-09-27T10:17:00Z",
    status: stage === "due" ? "due" : stage === "lifted" ? "lifted" : stage ? "issued" : "not_due",
    proposal_id: null,
    decision_case_id: null,
    stage,
    clean_samples: 0,
    samples_needed: 2,
    lift_proposal_id: null,
    lift_decision_case_id: null,
    ...extra,
  };
}

const stateOf = (zoneNotice: ReturnType<typeof noticeLifecycle>) =>
  Object.fromEntries((zoneNotice?.steps ?? []).map((s) => [s.key, s.state]));

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  sessionStorage.clear();
  resetMock();
  mockState.userId = "wtr_lead_01";
});
afterEach(() => {
  server.resetHandlers();
  sessionStorage.clear();
});

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

describe("noticeLifecycle", () => {
  beforeEach(() => resetMock());

  it("has five steps: due, issued, samples, lift decision, lifted", () => {
    expect(NOTICE_STEPS.map((s) => s.label)).toEqual(["Due", "Issued", "Samples", "Lift decision", "Lifted"]);
  });

  it("says nothing for a zone the register has no notice due for", () => {
    expect(noticeLifecycle(zone(WZ), [], [])).toBeUndefined();
    expect(noticeLifecycle(zone(WZ), [row(null)], [])).toBeUndefined();
  });

  it("counts only notices someone can sign as waiting for sign-off", () => {
    const due = noticeLifecycle(zone(WZ), [row("due")], []);
    expect(due && waitingForSignOff([due])).toEqual([]);
  });

  it("is due when the register says so and nothing is signed", () => {
    const n = noticeLifecycle(zone(WZ), [row("due")], []);
    expect(n?.current).toBe("due");
    expect(n?.status).toEqual({ level: "advisory", label: "Not proposed yet" });
    expect(n?.waitingForSignature).toBe(false);
    expect(n?.dueUtc).toBe("2024-09-27T10:17:00Z");
    expect(stateOf(n)).toEqual({
      due: "current",
      issued: "todo",
      samples: "todo",
      lift: "todo",
      lifted: "todo",
    });
  });

  it("waits for sign-off while the notice decision is open, with its deadline and decision", () => {
    const open = card("boil_water_notice", "proposed");
    const n = noticeLifecycle(
      zone(WZ),
      [row("due", { status: "proposed", proposal_id: open.proposal_id })],
      [open],
    );
    expect(n?.status.label).toBe("Waiting for sign-off");
    expect(n?.waitingForSignature).toBe(true);
    expect(n?.dueUtc).toBe("2024-09-27T13:17:00Z");
    expect(n?.decision?.proposal_id).toBe(open.proposal_id);
  });

  it("waits for clean samples once the notice is issued, counting those the lab reported", () => {
    const signed = card("boil_water_notice", "approved");
    const issued = noticeLifecycle(zone(WZ), [row("issued", { proposal_id: signed.proposal_id })], [signed]);
    expect(issued?.current).toBe("samples");
    expect(issued?.cleanSamples).toBe(0);
    expect(issued?.decision?.proposal_id).toBe(signed.proposal_id);
    const one = noticeLifecycle(zone(WZ), [row("samples", { clean_samples: 1 })], []);
    expect(one?.cleanSamples).toBe(1);
    expect(one?.samplesNeeded).toBe(2);
    expect(stateOf(one)).toEqual({
      due: "done",
      issued: "done",
      samples: "current",
      lift: "todo",
      lifted: "todo",
    });
    expect(one?.status.label).toBe("Waiting for clean samples");
  });

  it("asks for the lift decision the register names, with its deadline", () => {
    const lift = card("lift_boil_water_notice", "proposed", {
      effective_decide_by_utc: "2024-09-30T21:41:00Z",
    });
    const n = noticeLifecycle(
      zone(WZ),
      [row("lift_decision", { clean_samples: 2, lift_proposal_id: lift.proposal_id })],
      [card("boil_water_notice", "approved"), lift],
    );
    expect(n?.current).toBe("lift");
    expect(n?.cleanSamples).toBe(2);
    expect(n?.decision?.proposal_id).toBe(lift.proposal_id);
    expect(n?.dueUtc).toBe("2024-09-30T21:41:00Z");
    expect(n?.status.label).toBe("Lift waiting for sign-off");
  });

  it("is lifted, every step done, when the register says so", () => {
    const n = noticeLifecycle(zone(WZ), [row("lifted", { clean_samples: 2 })], []);
    expect(n?.current).toBe("lifted");
    expect(Object.values(stateOf(n))).toEqual(["done", "done", "done", "done", "done"]);
    expect(n?.status).toEqual({ level: "normal", label: "Lifted" });
  });

  it("takes the zone's row furthest along when the zone has two", () => {
    const n = noticeLifecycle(zone(WZ), [row(null, { kind: "pre_landfall" }), row("samples")], []);
    expect(n?.current).toBe("samples");
  });

  it("orders the zones that need a signature first, the lifted ones last", () => {
    const at = (id: string, stage: BwaAdvisory["stage"]) =>
      noticeLifecycle(zone(id), [row(stage, { zone_id: id })], []);
    const order = noticesInOrder(
      [at("A", "lifted"), at("B", "samples"), at("C", "lift_decision"), at("D", "due")].flatMap((n) =>
        n ? [n] : [],
      ),
    );
    expect(order.map((n) => n.zoneId)).toEqual(["D", "C", "B", "A"]);
  });

  it("shows the clean sample count on the Samples step", () => {
    show(
      <NoticeStepper
        notice={noticeLifecycle(zone(WZ), [row("samples", { clean_samples: 1 })], []) as ZoneNotice}
        zoneLabel="Laurelspur"
      />,
    );
    expect(screen.getByText("Samples 1/2")).toBeInTheDocument();
  });
});

describe("Boil-water notices at the morning after", () => {
  beforeEach(() => {
    sessionStorage.setItem("sgw.mock.zone_rules", "1");
    resetMock();
    mockState.userId = "wtr_lead_01";
  });

  it("shows one line per zone with its five steps, the zone that needs a signature first", async () => {
    show(<AdvisoryContainer now={MOCK_NOW} />);
    const rows = await screen.findAllByTestId("bwa-row");
    expect(rows.map((r) => within(r).getByRole("heading", { level: 3 }).textContent)).toEqual([
      "Laurelspur",
      "Copperleaf",
      "Deerwater",
      "Cedarfall",
    ]);
    const current = rows.map((r) => within(r).getByTestId("notice-stepper").getAttribute("data-current"));
    expect(current).toEqual(["due", "lift", "samples", "lifted"]);
    expect(within(rows[0] as HTMLElement).getByText("Waiting for sign-off")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("Lift waiting for sign-off")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("Waiting for clean samples")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("Samples 1/2")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("Samples 2/2")).toBeInTheDocument();
    expect(
      within(rows[3] as HTMLElement).getByText("Lifted", { selector: "[data-severity] span" }),
    ).toBeInTheDocument();
  });

  it("names each step's state for a screen reader and marks the current one", async () => {
    show(<AdvisoryContainer now={MOCK_NOW} />);
    const copperleaf = (await screen.findAllByTestId("notice-stepper"))[1] as HTMLElement;
    expect(copperleaf).toHaveAccessibleName("Notice steps for Copperleaf");
    const items = within(copperleaf).getAllByRole("listitem");
    expect(items.map((i) => i.getAttribute("data-state"))).toEqual([
      "done",
      "done",
      "done",
      "current",
      "todo",
    ]);
    expect(items[3]).toHaveAttribute("aria-current", "step");
    expect(items[3]).toHaveTextContent("Lift decision (now)");
  });

  it("links the open decision of each zone and keeps the rules behind Details", async () => {
    show(<AdvisoryContainer now={MOCK_NOW} />);
    const rows = await screen.findAllByTestId("bwa-row");
    const laurelspur = rows[0] as HTMLElement;
    expect(
      within(laurelspur).getByRole("link", { name: /^View decision: Boil-water notice, Laurelspur/ }),
    ).toHaveAttribute("href", "/?d=PRP-ZR-LAURELSPUR-BWA");
    expect(
      within(rows[1] as HTMLElement).getByRole("link", {
        name: /^View decision: Lift the boil-water notice, Copperleaf/,
      }),
    ).toBeInTheDocument();
    const details = within(laurelspur).getByRole("button", { name: "Details" });
    expect(details).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(details);
    expect(await within(laurelspur).findByText("Advisory after pressure loss")).toBeVisible();
  });

  it("shows the lifecycle state of every zone in the zones table and opens the first zone with something open", async () => {
    show(<ZonesContainer now={MOCK_NOW} />);
    const rows = await screen.findAllByTestId("zone-row");
    expect(rows).toHaveLength(4);
    const text = () => screen.getAllByTestId("zone-row").map((r) => r.textContent ?? "");
    await waitFor(() => expect(text()[0]).toContain("Lifted"));
    expect(text()[1]).toContain("Waiting for sign-off");
    expect(text()[2]).toContain("Lift waiting for sign-off");
    expect(text()[3]).toContain("Waiting for clean samples");
    const detail = await screen.findByTestId("zone-detail");
    expect(within(detail).getByText("Next steps for Cedarfall")).toBeInTheDocument();
    expect(within(detail).getByTestId("notice-stepper")).toHaveAttribute("data-current", "lifted");
    expect(screen.queryAllByTestId("zone-detail")).toHaveLength(1);
  });

  it("lists the tanker and the restoration order under the zone they serve, in plain words", async () => {
    show(<ZonesContainer now={MOCK_NOW} />);
    const first = (await screen.findAllByTestId("zone-row"))[0] as HTMLElement;
    await waitFor(() => expect(first.textContent).toContain("Lifted"));
    const cedarfall = await waitFor(() => {
      const found = screen
        .getAllByTestId("zone-detail")
        .find((d) => d.textContent?.includes("Next steps for Cedarfall"));
      expect(found).toBeDefined();
      return found as HTMLElement;
    });
    expect(within(cedarfall).getByText("Send a water tanker to Tallowbranch hospital")).toBeInTheDocument();
    expect(
      within(cedarfall).getByText("Set the restoration order of feeder 2219 and feeder 2207"),
    ).toBeInTheDocument();
    expect(within(cedarfall).queryByText(/FDR-AIK/)).not.toBeInTheDocument();
  });

  it("says nothing is due when the API has no advisories and no zone needs a notice", async () => {
    sessionStorage.clear();
    resetMock();
    mockState.userId = "wtr_lead_01";
    server.use(http.get("/api/water/advisories", () => HttpResponse.json({ advisories: [] })));
    server.use(http.get("/api/proposals", () => HttpResponse.json([])));
    show(<AdvisoryContainer now={MOCK_NOW} />);
    expect(await screen.findByText("No boil-water notice is due or in force.")).toBeInTheDocument();
  });
});
