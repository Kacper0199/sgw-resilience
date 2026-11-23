import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { crewName } from "@/lib/names";
import { resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { AssignedCrews } from "./AssignedCrews";
import { CrewsTable } from "./CrewsTable";
import { crewStatusLabel } from "./dispatch";
import { resetDispatch } from "./mocks";
import type { CrewItem } from "./types";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  resetDispatch();
});
afterEach(() => server.resetHandlers());

const as = (userId: string) => sessionStorage.setItem("sgw.mock.user", userId);

function show(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const row = (crewId: string) =>
  screen.getAllByTestId("crew-row").find((r) => r.getAttribute("data-row-id") === crewId) as HTMLElement;

async function choose(crewId: string, item: string) {
  const trigger = within(row(crewId)).getByRole("button", { name: `Actions for ${crewName(crewId)}` });
  fireEvent.keyDown(trigger, { key: "Enter" });
  fireEvent.click(await screen.findByRole("menuitem", { name: item }));
}

describe("crew status in words", () => {
  const base: CrewItem = {
    crew_id: "CRW-X",
    status: "available",
    location_id: null,
    headcount: 24,
    shift_end: null,
  };
  const assignment = {
    assignment_id: "ASG-0000000000000001",
    target_kind: "yard" as const,
    target_id: "STG-AIK-SANDHILL-YARD",
    target_label: "Sandhill yard",
    state: "proposed" as const,
    required_function: "logistics" as const,
    proposed_by: "ops_dm_01",
    proposed_at: "2024-09-26T15:05:00Z",
    decision_proposal_id: null,
    decided_by: null,
    decided_at: null,
  };
  it("names who must sign, then the assignment, then the field status", () => {
    expect(crewStatusLabel(base)).toBe("Available");
    expect(crewStatusLabel({ ...base, assignment })).toBe("Waiting for Logistics");
    expect(crewStatusLabel({ ...base, assignment: { ...assignment, state: "assigned" } })).toBe("Assigned");
    expect(
      crewStatusLabel({ ...base, status: "enroute", assignment: { ...assignment, state: "assigned" } }),
    ).toBe("On the way");
    expect(crewStatusLabel({ ...base, status: "blocked", assignment })).toBe("Blocked");
  });
});

describe("dispatch from the crews table", () => {
  it("gives a read-only persona no menu and no action column", async () => {
    as("exec_01");
    show(<CrewsTable />);
    await screen.findByRole("table", { name: "Crews (sortable)" });
    expect(screen.queryByTestId("crew-menu")).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Actions" })).not.toBeInTheDocument();
  });

  it("assigns with the one dialog, then logistics signs and the crew moves", async () => {
    as("ops_dm_01");
    const view = show(<CrewsTable />);
    await screen.findByRole("table", { name: "Crews (sortable)" });
    await choose("CRW-HARRIER-0103", "Assign…");
    const dialog = await screen.findByTestId("dispatch-dialog");
    const select = await within(dialog).findByLabelText("Assign to");
    await waitFor(() =>
      expect(within(dialog).getByRole("option", { name: "Sandhill yard" })).toBeInTheDocument(),
    );
    fireEvent.change(select, { target: { value: "decision:DC-D3-PS17-POWER" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(row("CRW-HARRIER-0103")).toHaveTextContent("Waiting for Logistics"));
    expect(row("CRW-HARRIER-0103")).toHaveTextContent("Hook up the portable generator at PS-17");
    expect(within(row("CRW-HARRIER-0103")).getByRole("link")).toHaveAttribute(
      "href",
      "/decisions/PRP-PS17-FDR2207-PRIO",
    );
    view.unmount();

    as("log_01");
    show(<CrewsTable />);
    await screen.findByRole("table", { name: "Crews (sortable)" });
    await choose("CRW-HARRIER-0103", "Sign assignment");
    await waitFor(() => expect(row("CRW-HARRIER-0103")).toHaveTextContent("Assigned"));
    await choose("CRW-HARRIER-0103", "Mark on the way");
    await waitFor(() => expect(row("CRW-HARRIER-0103")).toHaveTextContent("On the way"));
    await choose("CRW-HARRIER-0103", "Mark on site");
    await waitFor(() => expect(row("CRW-HARRIER-0103")).toHaveTextContent("On site"));
  });

  it("marks a crew blocked with a reason and clears it", async () => {
    as("ops_dm_02");
    show(<CrewsTable />);
    await screen.findByRole("table", { name: "Crews (sortable)" });
    await choose("CRW-MERLIN-0102", "Mark blocked…");
    const dialog = await screen.findByTestId("dispatch-dialog");
    fireEvent.change(within(dialog).getByLabelText("Reason"), {
      target: { value: "wind_above_bucket_limit" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Mark blocked" }));
    await waitFor(() =>
      expect(row("CRW-MERLIN-0102")).toHaveTextContent("Wind too strong for bucket trucks"),
    );
    await choose("CRW-MERLIN-0102", "Clear block");
    await waitFor(() => expect(row("CRW-MERLIN-0102")).toHaveTextContent("Available"));
  });

  it("marks the crew a link points to", async () => {
    as("exec_01");
    show(<CrewsTable focus="CRW-OSPREY-07" />);
    await screen.findByRole("table", { name: "Crews (sortable)" });
    expect(row("CRW-OSPREY-07")).toHaveAttribute("aria-current", "true");
  });
});

describe("crews on the decision pane", () => {
  it("lists the crews assigned to the decision, and nothing when there are none", async () => {
    as("ops_dm_02");
    const { container } = show(<AssignedCrews caseId="DC-D3-PS17-POWER" />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    await fetch("/api/crews/CRW-HARRIER-0103/assignments", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ target_kind: "decision", target_id: "DC-D3-PS17-POWER" }),
    });
    show(<AssignedCrews caseId="DC-D3-PS17-POWER" />);
    const line = await screen.findByTestId("assigned-crews");
    expect(line).toHaveTextContent("Harrier 3");
    expect(line).toHaveTextContent("Waiting for Logistics");
    expect(within(line).getByRole("link")).toHaveAttribute("href", "/crews?crew=CRW-HARRIER-0103");
  });
});
