import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import type * as React from "react";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ME_KEY } from "@/auth/useSession";
import { meFor } from "@/mocks/fixtures";
import { mockState, resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { DataTab } from "./DataTab";
import { resetControl, resetStoppedRuns } from "./mocks";
import { RunsTab } from "./RunsTab";
import { SafetyTab } from "./SafetyTab";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  resetControl();
  resetStoppedRuns();
});
afterEach(() => server.resetHandlers());

function show(ui: React.ReactElement, userId: string) {
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

describe("health controls follow the permissions the API enforces", () => {
  it("hides the stop and mode controls from compliance, who only signs a restore", async () => {
    show(<SafetyTab />, "wtr_comp_01");
    await screen.findAllByTestId("mode-row");
    expect(screen.queryByRole("button", { name: "Raise stop level" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Set mode" })).toBeNull();
  });

  it("shows them to the Incident Commander", async () => {
    show(<SafetyTab />, "ic_01");
    expect(await screen.findByRole("button", { name: "Raise stop level" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Set mode" })).toBeDefined();
  });

  it("lets the data owner stop a run that waits for sign-off, with a reason", async () => {
    show(<RunsTab />, "ml_01");
    const stop = await screen.findByRole("button", { name: /^Stop request/ });
    fireEvent.click(stop);
    const dialog = await screen.findByTestId("reason-dialog");
    const confirm = within(dialog).getByRole("button", { name: "Stop request" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Nobody will sign" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(screen.queryByTestId("reason-dialog")).toBeNull());
    await waitFor(() => expect(screen.queryByRole("button", { name: /^Stop request/ })).toBeNull());
  });

  it("gives the Duty Manager no Stop on runs", async () => {
    show(<RunsTab />, "ops_dm_01");
    await screen.findAllByTestId("agent-run-row");
    expect(screen.queryByRole("button", { name: /^Stop request/ })).toBeNull();
  });

  it("offers Load now to the data and platform teams only", async () => {
    for (const user of ["ml_01", "admin_01"]) {
      const view = show(<DataTab />, user);
      expect((await screen.findAllByRole("button", { name: /^Load now: / })).length).toBeGreaterThan(0);
      view.unmount();
    }
    for (const user of ["ic_01", "ops_dm_01", "wtr_comp_01"]) {
      const view = show(<DataTab />, user);
      await screen.findAllByTestId("asset-row");
      expect(screen.queryByRole("button", { name: /^Load now: / })).toBeNull();
      view.unmount();
    }
  });
});
