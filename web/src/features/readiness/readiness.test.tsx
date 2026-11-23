import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NuqsAdapter } from "nuqs/adapters/react-router/v8";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { MOCK_NOW } from "@/mocks/fixtures";
import { mockState, resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { readinessItems } from "./mocks";
import { dueText, grouped, isOverdue } from "./model";
import { ReadinessView } from "./ReadinessPage";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  mockState.userId = "ops_dm_01";
});
afterEach(() => server.resetHandlers());

function show() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <NuqsAdapter>
          <ReadinessView now={MOCK_NOW} />
        </NuqsAdapter>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("readiness model", () => {
  it("groups by status and orders each group by due date", () => {
    const g = grouped(readinessItems);
    expect(g.gap.map((i) => i.item_id)).toEqual(
      [...g.gap]
        .sort((a, b) => Date.parse(a.due_utc ?? "") - Date.parse(b.due_utc ?? ""))
        .map((i) => i.item_id),
    );
    expect(g.gap.length + g.unknown.length + g.ready.length).toBe(readinessItems.length);
  });

  it("counts a missing item as overdue only after its date and never for a ready one", () => {
    const gap = readinessItems.find(
      (i) => i.status === "gap" && i.due_utc && Date.parse(i.due_utc) < Date.parse(MOCK_NOW),
    );
    expect(gap && isOverdue(gap, MOCK_NOW)).toBe(true);
    const ready = readinessItems.find((i) => i.status === "ready");
    expect(ready && isOverdue(ready, MOCK_NOW)).toBe(false);
  });

  it("writes lead times in days for weeks and hours for days", () => {
    const hours = (h: number) => new Date(Date.parse(MOCK_NOW) + h * 3_600_000).toISOString();
    expect(dueText(hours(24), MOCK_NOW)).toBe("in 24 h");
    expect(dueText(hours(96), MOCK_NOW)).toBe("in 4 d");
    expect(dueText(hours(-72), MOCK_NOW)).toBe("3 d overdue");
    expect(dueText(MOCK_NOW, MOCK_NOW)).toBe("now");
  });
});

describe("Readiness on its pre-season review", () => {
  const REVIEW = "2024-05-06T12:00:00Z";
  const atReview = readinessItems.map((i) => ({
    ...i,
    evaluated_at_utc: REVIEW,
    due_utc: i.item_id === "DC-RDY-GEN-PS52-LOADTEST" ? "2024-04-24T04:00:00Z" : "2024-06-01T04:00:00Z",
  }));

  it("reads every check at the review date with one stamp and no countdown from the replay clock", async () => {
    server.use(http.get("/api/readiness", () => HttpResponse.json(atReview)));
    show();
    expect((await screen.findByTestId("readiness-review")).textContent).toBe("Pre-season review, 6 May 2024");
    const rows = await screen.findAllByTestId("readiness-row");
    const text = rows.map((r) => r.textContent ?? "").join(" | ");
    expect(text).not.toMatch(/\d+ d overdue/);
    expect(rows.filter((r) => r.textContent?.includes("Overdue"))).toHaveLength(1);
    expect(rows[0]?.textContent).toContain("24 Apr 2024");
  });
});

describe("Readiness page", () => {
  it("opens with the key numbers, then not-ready checks, no-record checks and folded ready checks", async () => {
    show();
    const summary = await screen.findByTestId("readiness-summary");
    const ready = readinessItems.filter((i) => i.status === "ready").length;
    expect(summary.textContent).toContain("Pre-season review, 6 May 2024");
    expect(summary.textContent).toContain(`${ready} of ${readinessItems.length} ready`);
    const rows = await screen.findAllByTestId("readiness-row");
    expect(rows[0]?.textContent).toContain("Overdue");
    expect(rows[0]?.textContent).toContain("Operations");
    expect(rows.filter((r) => r.textContent?.includes("No record"))).toHaveLength(
      readinessItems.filter((i) => i.status === "unknown").length,
    );
    expect(screen.queryByText("Ready", { selector: "td *" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Ready/ }));
    expect(
      (await screen.findAllByTestId("readiness-row")).filter((r) => r.textContent?.includes("Ready")),
    ).toHaveLength(ready);
  });

  it("shows the selected check in the detail pane with its decision link target", async () => {
    show();
    const detail = await screen.findByTestId("readiness-detail");
    expect(detail.textContent).toContain(readinessItems[0]?.title);
    expect(detail.textContent).toContain("What is missing");
    expect(screen.queryByRole("button", { name: "Record result" })).toBeNull();
  });

  it("says so when the scenario has no readiness items", async () => {
    server.use(http.get("/api/readiness", () => HttpResponse.json([])));
    show();
    expect(await screen.findByText("No readiness checks yet.")).toBeDefined();
  });

  it("fails inside the page with a plain line", async () => {
    server.use(
      http.get("/api/readiness", () =>
        HttpResponse.json({ error: { code: "NOT_FOUND", message: "x" } }, { status: 404 }),
      ),
    );
    show();
    await waitFor(() => expect(screen.getByText("Couldn't load readiness.")).toBeDefined());
  });
});
