import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";
import { ME_KEY } from "@/auth/useSession";
import { TooltipProvider } from "@/components/ui/tooltip";
import { decisionTitle } from "@/features/decisions/actionTypes";
import { freshCards, MOCK_NOW, meFor, toSummary } from "@/mocks/fixtures";
import { resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { BriefView } from "./BriefPage";
import { formatCount, shownFor } from "./format";
import { resetBriefMock } from "./mocks";
import { initialBrief, initialLiveBrief } from "./mocks/data";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  resetBriefMock();
  sessionStorage.setItem("sgw.mock.fast", "1");
});
afterEach(() => {
  server.resetHandlers();
  sessionStorage.clear();
});

function show(user = "ic_01", search = "") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(ME_KEY, meFor(user));
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TooltipProvider>
          <NuqsTestingAdapter searchParams={search} hasMemory>
            <BriefView now={MOCK_NOW} />
          </NuqsTestingAdapter>
        </TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const brief = initialBrief();

describe("Brief", () => {
  it("leads with the status word, the as-of time and the last advisory", async () => {
    show();
    const head = await screen.findByTestId("status-header");
    expect(head).toHaveTextContent("Warning");
    expect(head).toHaveTextContent(
      brief.status.reason.charAt(0).toUpperCase() + brief.status.reason.slice(1),
    );
    expect(head).toHaveTextContent("As of 21:00 ET (01:00Z), Thu 26 Sep");
    expect(head).toHaveTextContent("Latest advisory 17:00 ET, next 23:00 ET");
  });

  it("shows the four measured numbers first", async () => {
    show();
    const numbers = await screen.findByTestId("four-numbers");
    expect(numbers).toHaveAttribute("data-basis", "actual");
    expect(numbers.children).toHaveLength(4);
    for (const n of brief.numbers) {
      const cell = screen.getByTestId(`number-${n.key}`);
      expect(cell).toHaveTextContent(n.key === "customers_out" ? "Customers out now" : n.label);
      expect(cell).toHaveTextContent(formatCount(n.actual?.value ?? 0));
    }
  });

  it("switches to the forecast with its basis, and says when a number has none", async () => {
    show();
    await screen.findByTestId("four-numbers");
    fireEvent.click(screen.getByRole("radio", { name: "Forecast" }));
    const first = brief.numbers[0];
    const cell = screen.getByTestId("number-customers_out");
    expect(cell).toHaveTextContent("Forecast peak");
    expect(cell).toHaveTextContent(formatCount(first.forecast?.p50 ?? 0));
    expect(cell).toHaveTextContent(`Counts ${first.forecast?.basis}`);
    expect(screen.getByTestId("number-crews_working")).toHaveTextContent("No forecast.");
    expect(screen.getByRole("radio", { name: "Forecast" })).toBeChecked();
  });

  it("formats a missing view as plain text", () => {
    const n = { ...brief.numbers[0], forecast: null };
    expect(shownFor(n, "forecast", (s) => s)).toBeNull();
  });

  it("lists the decisions waiting for two signatures with who is missing and a link to each", async () => {
    show();
    const rows = await screen.findAllByTestId("open-clock");
    expect(rows).toHaveLength(brief.open_t3.length);
    expect(rows[0]).toHaveTextContent("Command, Water operations");
    expect(rows[0]).toHaveTextContent(decisionTitle(brief.open_t3[0].title));
    const links = within(rows[0]).getAllByRole("link");
    expect(links.length).toBeGreaterThanOrEqual(2);
    for (const l of links) expect(l).toHaveAttribute("href", `/?d=${brief.open_t3[0].proposal_id}`);
    expect(within(rows[0]).getAllByRole("link", { name: "View decision" }).length).toBeGreaterThan(0);
  });

  it("says nothing moved when no deadline has shifted, and lists a shifted one with a link", async () => {
    show();
    expect(await screen.findByTestId("nothing-changed")).toHaveTextContent("No decision deadline has moved");
    const [first] = freshCards();
    server.use(
      http.get("/api/proposals", () =>
        HttpResponse.json([
          {
            ...toSummary(first),
            clock_shift: {
              advisory_label: "N+2",
              previous_advisory_label: "N+1",
              previous_effective_decide_by_utc: "2024-09-27T04:45:00Z",
              shift_min: -76,
            },
          },
        ]),
      ),
    );
    const view = show();
    const list = await view.findByTestId("changed-list");
    expect(list).toHaveTextContent("earlier by 1 h 16 m");
    expect(within(list).getByRole("link", { name: "View decision" })).toHaveAttribute(
      "href",
      `/?d=${first.proposal_id}`,
    );
  });

  it("after the final advisory moves the advisory to history and lists no stale shifts", async () => {
    const live = initialLiveBrief();
    const [first, second] = freshCards();
    const shift = {
      advisory_label: "N+1",
      previous_advisory_label: "N",
      previous_effective_decide_by_utc: "2024-09-27T04:45:00Z",
      shift_min: -76,
    };
    server.use(
      http.get("/api/brief", () =>
        HttpResponse.json({
          ...live,
          as_of: "2024-09-30T12:00:00Z",
          last_advisory: {
            label: "N+4",
            issued_utc: "2024-09-27T09:00:00Z",
            landfall_eta_utc: null,
            next_advisory_utc: null,
          },
        }),
      ),
      http.get("/api/proposals", () =>
        HttpResponse.json([
          { ...toSummary(first), clock_shift: shift },
          { ...toSummary(second), clock_shift: shift },
        ]),
      ),
    );
    show();
    expect(await screen.findByTestId("advisory-line")).toHaveTextContent(
      "Last advisory Sep 27 05:00 ET (final)",
    );
    expect(screen.queryByText(/Latest advisory/)).toBeNull();
    expect(await screen.findByTestId("final-advisory")).toHaveTextContent(
      "The final advisory was issued Sep 27 05:00 ET. No advisories follow.",
    );
    expect(screen.queryByText("What changed at the latest advisory")).toBeNull();
    expect(screen.queryByTestId("changed-list")).toBeNull();
  });

  it("lists a decision once even when several of its proposals carry the shift", async () => {
    const [first] = freshCards();
    const shift = {
      advisory_label: "N+2",
      previous_advisory_label: "N+1",
      previous_effective_decide_by_utc: "2024-09-27T04:45:00Z",
      shift_min: -76,
    };
    server.use(
      http.get("/api/proposals", () =>
        HttpResponse.json([
          { ...toSummary(first), proposal_id: "PRP-OLD-1", state: "expired", clock_shift: shift },
          { ...toSummary(first), clock_shift: shift },
          { ...toSummary(first), proposal_id: "PRP-OLD-2", state: "expired", clock_shift: shift },
        ]),
      ),
    );
    const view = show();
    const list = await view.findByTestId("changed-list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(within(list).getByRole("link", { name: "View decision" })).toHaveAttribute(
      "href",
      `/?d=${first.proposal_id}`,
    );
  });

  it("gives one sentence per function and keeps the caveat and the exercise footer behind Info", async () => {
    show();
    const lines = await screen.findAllByTestId("function-line");
    expect(lines).toHaveLength(brief.functions.length);
    for (const l of brief.functions) expect(screen.getByText(l.sentence)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "About these numbers" }));
    expect(await screen.findByTestId("caveat")).toHaveTextContent("under-called large storms");
    expect(screen.getByTestId("brief-footer")).toHaveTextContent(
      "Exercise with synthetic data, not for operational use",
    );
  });

  it("drafts a report from its stages, then the Incident Commander promotes it", async () => {
    show("ic_01");
    expect(await screen.findByTestId("sitrep-current")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm report" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Draft a report/ }));
    const draft = await screen.findByTestId("sitrep-draft", undefined, { timeout: 6000 });
    expect(within(draft).getByTestId("sitrep-text")).toHaveTextContent("customers are without power");
    const promote = screen.getByRole("button", { name: "Confirm report" });
    expect(promote).toBeEnabled();
    fireEvent.click(promote);
    await waitFor(() => expect(screen.queryByTestId("sitrep-draft")).toBeNull());
    expect(screen.getByTestId("sitrep-current")).toHaveTextContent("confirmed by Incident Commander");
  });

  it("lets another function draft but explains in place why it cannot promote", async () => {
    show("wtr_lead_01");
    await screen.findByTestId("sitrep-current");
    fireEvent.click(screen.getByRole("button", { name: /Draft a report/ }));
    await screen.findByTestId("sitrep-draft", undefined, { timeout: 6000 });
    expect(screen.getByRole("button", { name: "Confirm report" })).toBeDisabled();
    expect(screen.getByText("Only the Incident Commander can confirm a draft.")).toBeInTheDocument();
  });

  it("offers a read-only role no drafting", async () => {
    show("exec_01");
    await screen.findByTestId("sitrep-current");
    expect(screen.queryByRole("button", { name: /Draft a report/ })).toBeNull();
  });

  it("says so plainly when the brief does not load", async () => {
    server.use(
      http.get("/api/brief", () =>
        HttpResponse.json({ error: { code: "UNAVAILABLE", message: "down" } }, { status: 503 }),
      ),
    );
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load the briefing");
  });

  it("says the brief is not available when the server has no such route yet", async () => {
    server.use(
      http.get("/api/brief", () =>
        HttpResponse.json({ error: { code: "NOT_FOUND", message: "no" } }, { status: 404 }),
      ),
    );
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("The briefing isn't available yet.");
  });
});
