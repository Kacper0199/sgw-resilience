import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import type * as React from "react";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { Sidebar } from "@/app/layout/Sidebar";
import { ME_KEY } from "@/auth/useSession";
import { TooltipProvider } from "@/components/ui/tooltip";
import { CaseHeader } from "@/features/decisions/CaseHeader";
import type { ProposalCard } from "@/lib/api";
import { meFor } from "@/mocks/fixtures";
import { mockState, resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { resetNotificationReads } from "./mocks";
import NotificationsPage from "./NotificationsPage";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  resetNotificationReads();
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
        <NuqsTestingAdapter>
          <TooltipProvider>{ui}</TooltipProvider>
        </NuqsTestingAdapter>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const rows = () => screen.getAllByTestId("notification");

describe("notifications page", () => {
  it("lists the person's items, unread first marked, and marks one read on open", async () => {
    show(<NotificationsPage />, "ic_01");
    await screen.findAllByTestId("notification");
    expect(rows().map((r) => r.textContent)).toEqual(
      expect.arrayContaining([expect.stringContaining("Decision waiting on you")]),
    );
    expect(rows().every((r) => r.dataset.read === "false")).toBe(true);
    expect(rows()[0]).toHaveAttribute("href", "/decisions/PRP-PS17-FDR2207-PRIO");
    fireEvent.click(rows()[0] as HTMLElement);
    await waitFor(() => expect(rows()[0]?.dataset.read).toBe("true"));
  });

  it("marks everything read and hides the button", async () => {
    show(<NotificationsPage />, "log_01");
    fireEvent.click(await screen.findByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(rows().every((r) => r.dataset.read === "true")).toBe(true));
    expect(screen.queryByRole("button", { name: "Mark all read" })).toBeNull();
  });

  it("says when there is nothing, and shows a load failure as an error, not as empty", async () => {
    const view = show(<NotificationsPage />, "plan_etr_01");
    server.use(http.get("/api/notifications", () => HttpResponse.json({ items: [], unread: 0 })));
    expect(await screen.findByText("Nothing for you right now.")).toBeDefined();
    view.unmount();
    server.use(
      http.get("/api/notifications", () =>
        HttpResponse.json({ error: { code: "BOOM", message: "down" } }, { status: 500 }),
      ),
    );
    show(<NotificationsPage />, "plan_etr_01");
    expect((await screen.findByRole("alert")).textContent).toContain("Notifications did not load.");
    expect(screen.queryByText("Nothing for you right now.")).toBeNull();
  });
});

describe("controls follow the permissions the API enforces", () => {
  it("shows the unread count in the nav and Admin only to the admin", async () => {
    show(<Sidebar collapsed={false} onToggle={() => {}} counts={{ notifications: 3 }} />, "ic_01");
    expect(await screen.findByRole("link", { name: /Notifications/ })).toHaveTextContent("3");
    await waitFor(() => expect(screen.queryByRole("link", { name: /Admin/ })).toBeNull());
  });

  it("offers Admin to the platform admin", async () => {
    show(<Sidebar collapsed={false} onToggle={() => {}} />, "admin_01");
    expect(await screen.findByRole("link", { name: /Admin/ })).toBeDefined();
  });

  it("lets the proposer withdraw an open decision with a reason", async () => {
    const card = mockState.cards.find((c) => c.proposed_by.user_id === "ops_dm_01") as ProposalCard;
    show(<CaseHeader card={card} now="2024-09-27T01:00:00Z" />, "ops_dm_01");
    fireEvent.click(await screen.findByRole("button", { name: "Withdraw…" }));
    const dialog = await screen.findByTestId("reason-dialog");
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Duplicate request" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Withdraw" }));
    await waitFor(() => expect(screen.queryByTestId("reason-dialog")).toBeNull());
    expect(card.state).toBe("withdrawn");
  });

  it("offers no Withdraw to someone who neither proposed nor signed", async () => {
    const card = mockState.cards.find((c) => c.proposed_by.user_id === "ops_dm_01") as ProposalCard;
    show(<CaseHeader card={card} now="2024-09-27T01:00:00Z" />, "exec_01");
    await screen.findByRole("heading", { name: card.title });
    expect(screen.queryByRole("button", { name: /Withdraw/ })).toBeNull();
  });
});
