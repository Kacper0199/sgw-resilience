import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { delay, HttpResponse, http } from "msw";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach, vi } from "vitest";
import { ME_KEY } from "@/auth/useSession";
import { TooltipProvider } from "@/components/ui/tooltip";
import { api, type Me, setUnauthorizedHandler } from "@/lib/api";
import { freshCards, MOCK_NOW, toSummary } from "@/mocks/fixtures";
import { mockState, resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { Inspector } from "./Inspector";
import { buildQueue } from "./queueModel";
import { severityOf } from "./ui";
import type { QueueItem } from "./useQueue";

const ID = "PRP-PS17-FDR2207-PRIO";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
vi.mock("@/features/map/MapContainer", () => ({ default: () => null }));
beforeEach(() => resetMock());
afterEach(() => {
  server.resetHandlers();
  setUnauthorizedHandler(null);
});

function setup(me: Me) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(ME_KEY, me);
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TooltipProvider>
          <Inspector id={ID} now={MOCK_NOW} tab="deadline" onTab={() => {}} onClose={() => {}} />
        </TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return qc;
}

const bumpServerCard = () => {
  const card = mockState.cards.find((c) => c.proposal_id === ID);
  if (!card) throw new Error("fixture card missing");
  card.proposal_version = 2;
  card.action_hash = "b".repeat(64);
};

async function openSignDialog() {
  fireEvent.click(await screen.findByRole("button", { name: /^Sign as / }));
  return screen.findByRole("dialog");
}

describe("queue model", () => {
  const item = (id: string, decideBy: string, fns: string[], approvals: string[] = []) =>
    ({
      summary: {
        proposal_id: id,
        state: "in_review",
        effective_decide_by_utc: decideBy,
        functions_required: fns,
        approvals: approvals.map((f) => ({ function: f, decision: "approve" })),
      },
      card: undefined,
    }) as unknown as QueueItem;
  const me = { function: "command" } as Me;

  it("pins the signer's own items first and keeps decide-by order inside groups", () => {
    const items = [
      item("late", "2024-09-27T09:00:00Z", ["logistics"]),
      item("mine-late", "2024-09-27T06:00:00Z", ["command"]),
      item("early", "2024-09-27T02:00:00Z", ["logistics"]),
      item("mine-early", "2024-09-27T03:00:00Z", ["command"]),
    ];
    const q = buildQueue(items, me, "all", "all");
    expect(q.order).toEqual(["mine-early", "mine-late", "early", "late"]);
    expect(buildQueue(items, me, "waiting", "all").order).toEqual(["mine-early", "mine-late"]);
  });
  it("does not treat an already signed function as waiting on the signer", () => {
    const q = buildQueue([item("x", "2024-09-27T03:00:00Z", ["command"], ["command"])], me, "waiting", "all");
    expect(q.order).toEqual([]);
  });
});

describe("severity source", () => {
  it("shows the severity the API sent", () => {
    expect(severityOf({ severity: "critical" })).toBe("critical");
  });
  it("reads a payload without severity as unknown instead of working it out", () => {
    expect(severityOf({})).toBe("unknown_stale");
  });
  it("mock summaries carry the severity of their card", () => {
    for (const c of freshCards()) expect(toSummary(c).severity).toBe(c.severity);
  });
});

describe("approval flow against the mocked API", () => {
  it("signs, then shows the other team as missing", async () => {
    const me = await api.login("ic_01", "demo");
    setup(me);
    fireEvent.click(await screen.findByRole("button", { name: /^Sign as / }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign" }));
    await waitFor(() => expect(mockState.cards.find((c) => c.proposal_id === ID)?.approvals).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await screen.findByText("1 of 2")).toBeInTheDocument();
  });

  it("asks for the password when the API requires a step-up, then retries", async () => {
    const me = await api.login("ic_01", "demo");
    mockState.stepUpUntil = 0;
    setup(me);
    fireEvent.click(await screen.findByRole("button", { name: /^Sign as / }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign" }));
    const field = await within(dialog).findByLabelText("Enter your password to sign");
    fireEvent.change(field, { target: { value: "demo" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign" }));
    await waitFor(() => expect(mockState.cards.find((c) => c.proposal_id === ID)?.approvals).toHaveLength(1));
  });

  it("explains in place why a function that does not sign cannot sign", async () => {
    const me = await api.login("exec_01", "demo");
    setup(me);
    expect(await screen.findByText(/not one of the teams that sign this decision/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Sign as / })).toBeNull();
  });

  it("keeps the dialog, the field and the session when the step-up password is wrong", async () => {
    const me = await api.login("ic_01", "demo");
    mockState.stepUpUntil = 0;
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    const qc = setup(me);
    const dialog = await openSignDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign" }));
    const field = await within(dialog).findByLabelText("Enter your password to sign");
    fireEvent.change(field, { target: { value: "wrong" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign" }));
    expect(await within(dialog).findByText("Wrong password.")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Enter your password to sign")).toBeInTheDocument();
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(qc.getQueryData(ME_KEY)).toBe(me);
    expect(mockState.cards.find((c) => c.proposal_id === ID)?.approvals).toHaveLength(0);
  });

  it("blocks signing when the card changes while the dialog is open, until the person reviews it", async () => {
    const me = await api.login("ic_01", "demo");
    const qc = setup(me);
    const dialog = await openSignDialog();
    bumpServerCard();
    await qc.invalidateQueries({ queryKey: ["proposals"] });
    const review = await within(dialog).findByRole("button", { name: "Review v2" });
    expect(within(dialog).queryByRole("button", { name: "Sign" })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("alert")).toHaveTextContent("changed to version 2");
    fireEvent.click(review);
    fireEvent.click(await within(dialog).findByRole("button", { name: "Sign" }));
    await waitFor(() => expect(mockState.cards.find((c) => c.proposal_id === ID)?.approvals).toHaveLength(1));
  });

  it("shows the stale notice on a 412 and then asks for a review of the new version", async () => {
    const me = await api.login("ic_01", "demo");
    setup(me);
    const dialog = await openSignDialog();
    bumpServerCard();
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign" }));
    expect(await within(dialog).findByText(/changed to version 2/)).toBeInTheDocument();
    expect(await within(dialog).findByRole("button", { name: "Review v2" })).toBeInTheDocument();
    expect(mockState.cards.find((c) => c.proposal_id === ID)?.approvals).toHaveLength(0);
  });

  it("locks Cancel while a signature is in flight", async () => {
    const me = await api.login("ic_01", "demo");
    server.use(
      http.post("/api/proposals/:id/approvals", async () => {
        await delay(250);
        return HttpResponse.json({
          approval_id: "A-1",
          proposal_state: "in_review",
          remaining_functions: ["water_operations"],
        });
      }),
    );
    setup(me);
    const dialog = await openSignDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign" }));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
