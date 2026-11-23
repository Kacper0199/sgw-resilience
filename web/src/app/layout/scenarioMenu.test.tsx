import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { MemoryRouter, useLocation } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { ScenarioMenu } from "./ScenarioMenu";
import { canMoveClock, directionOf } from "./scenarioJump";

const restart = vi.fn();

vi.mock("@/sse/OpsStreamProvider", () => ({ useOpsRestart: () => restart }));
vi.mock("@/sse/useScenarioNow", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/sse/useScenarioNow")>();
  return { ...actual, useScenarioNow: () => actual.useScenario().data?.scenario_time ?? null };
});

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  restart.mockClear();
});
afterEach(() => server.resetHandlers());

function Where() {
  const at = useLocation();
  return <output data-testid="where">{at.pathname + at.search}</output>;
}

function show(entry = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  window.history.replaceState(null, "", entry);
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <ScenarioMenu />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return qc;
}

async function openMenu() {
  fireEvent.click(await screen.findByTestId("mode-strip"));
  return screen.findByTestId("scenario-menu");
}

describe("scenario menu", () => {
  it("says what is replayed, when and from which data", async () => {
    await api.login("audit_01", "demo");
    show();
    expect((await screen.findByTestId("mode-strip")).textContent).toContain("23 Sep – 6 Oct 2024");
    const menu = await openMenu();
    expect(within(menu).getByTestId("scenario-period").textContent).toBe("23 Sep – 6 Oct 2024, Eastern time");
    expect(within(menu).getByTestId("key-moments").textContent).toContain("12 hurricane advisories");
    expect(within(menu).getByTestId("key-moments").textContent).toContain("Landfall");
    const sources = within(menu).getByTestId("data-sources");
    expect(within(sources).getAllByText("Real").length).toBeGreaterThan(0);
    expect(within(sources).getByText("Synthetic")).toBeInTheDocument();
    expect(within(menu).getByRole("link", { name: "Sources and licences" })).toHaveAttribute(
      "href",
      "/help#data-sources",
    );
  });

  it("offers no jump to a role that cannot move the clock", async () => {
    await api.login("audit_01", "demo");
    show();
    const menu = await openMenu();
    await waitFor(() => expect(within(menu).getByTestId("data-sources")).toBeInTheDocument());
    expect(within(menu).queryByText("Jump to")).toBeNull();
    expect(within(menu).queryByTestId("jump-list")).toBeNull();
  });

  it("lets a presenter jump after confirming, then refreshes the whole app", async () => {
    await api.login("ops_dm_01", "demo");
    const qc = show();
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    const menu = await openMenu();
    const list = await within(menu).findByTestId("jump-list");
    expect(within(list).getAllByRole("button")).toHaveLength(7);
    fireEvent.click(within(list).getByRole("button", { name: /^5 AM advisory/ }));
    const dialog = await screen.findByTestId("jump-dialog");
    expect(dialog.textContent).toContain("signatures are voided");
    expect(dialog.textContent).toContain("Going back does not undo decisions already recorded.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Jump clock only" }));
    expect(await within(dialog).findByRole("button", { name: /Jumping/ })).toBeDisabled();
    await waitFor(() => expect(screen.queryByTestId("jump-dialog")).toBeNull());
    expect(restart).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalled();
    expect(qc.getQueryData<{ scenario_time: string }>(["scenario"])?.scenario_time).toBe(
      "2024-09-26T09:05:00Z",
    );
  });

  it("keeps the dialog open with the reason when the jump fails", async () => {
    await api.login("ops_dm_01", "demo");
    server.use(
      http.post("/api/scenario", () =>
        HttpResponse.json(
          { error: { code: "CLOCK", message: "scenario_time outside the window" } },
          { status: 422 },
        ),
      ),
    );
    show();
    const menu = await openMenu();
    fireEvent.click(
      within(await within(menu).findByTestId("jump-list")).getAllByRole("button")[0] as HTMLElement,
    );
    const dialog = await screen.findByTestId("jump-dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Jump clock only" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("outside the window");
    expect(restart).not.toHaveBeenCalled();
  });
});

describe("replay clock and demo moments", () => {
  it("lets a clock operator play, set the speed and pause", async () => {
    await api.login("ops_dm_01", "demo");
    const qc = show();
    const menu = await openMenu();
    const controls = await within(menu).findByTestId("replay-controls");
    fireEvent.click(within(controls).getByRole("button", { name: "Play" }));
    await waitFor(() => expect(qc.getQueryData<{ speed: number }>(["scenario"])?.speed).toBe(60));
    expect(within(controls).getByRole("button", { name: "60×" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(controls).getByRole("button", { name: "900×" }));
    await waitFor(() => expect(qc.getQueryData<{ speed: number }>(["scenario"])?.speed).toBe(900));
    fireEvent.click(within(controls).getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(qc.getQueryData<{ speed: number }>(["scenario"])?.speed).toBe(0));
    expect(restart).toHaveBeenCalledTimes(3);
  });

  it("shows no replay controls to a role that cannot move the clock", async () => {
    await api.login("audit_01", "demo");
    show();
    const menu = await openMenu();
    await waitFor(() => expect(within(menu).getByTestId("data-sources")).toBeInTheDocument());
    expect(within(menu).queryByTestId("replay-controls")).toBeNull();
  });

  it("loads a moment's saved state after confirming and refreshes everything", async () => {
    await api.login("ic_01", "demo");
    const qc = show();
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    const menu = await openMenu();
    const list = await within(menu).findByTestId("jump-list");
    fireEvent.click(within(list).getByRole("button", { name: /^Morning after landfall/ }));
    const dialog = await screen.findByTestId("jump-dialog");
    expect(dialog.textContent).toContain("saved state");
    fireEvent.click(within(dialog).getByRole("button", { name: "Load moment" }));
    expect(await within(dialog).findByRole("button", { name: /Loading/ })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Jump clock only" })).toBeDisabled();
    await waitFor(() => expect(screen.queryByTestId("jump-dialog")).toBeNull());
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(restart).toHaveBeenCalledTimes(1);
  });

  it("offers no Load moment when the server cannot load moments", async () => {
    await api.login("ic_01", "demo");
    server.use(
      http.get("/api/scenario", async () => {
        const { scenario } = await import("@/mocks/fixtures");
        return HttpResponse.json({ ...scenario, loads_moments: false });
      }),
    );
    show();
    const menu = await openMenu();
    fireEvent.click(
      within(await within(menu).findByTestId("jump-list")).getAllByRole("button")[0] as HTMLElement,
    );
    const dialog = await screen.findByTestId("jump-dialog");
    expect(within(dialog).queryByRole("button", { name: "Load moment" })).toBeNull();
    expect(dialog.textContent).not.toContain("saved state");
  });
});

describe("clock permission", () => {
  it("matches the API rule: command, operations or the presenter role", () => {
    expect(canMoveClock({ function: "command", roles: [] })).toBe(true);
    expect(canMoveClock({ function: "operations", roles: [] })).toBe(true);
    expect(canMoveClock({ function: "audit", roles: ["presenter"] })).toBe(true);
    expect(canMoveClock({ function: "platform", roles: ["platform_admin"] })).toBe(false);
    expect(canMoveClock(null)).toBe(false);
    expect(directionOf("2024-09-26T09:05:00Z", "2024-09-27T01:00:00Z")).toBe("back");
  });
});
