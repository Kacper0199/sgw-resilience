import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NuqsAdapter } from "nuqs/adapters/react-router/v8";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ME_KEY } from "@/auth/useSession";
import { TooltipProvider } from "@/components/ui/tooltip";
import { MOCK_NOW, meFor } from "@/mocks/fixtures";
import { mockState, resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { resetReadinessResults } from "./mocks";
import { ReadinessView } from "./ReadinessPage";

const LOAD_TEST = "DC-RDY-GEN-PS52-LOADTEST";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  resetReadinessResults();
  mockState.userId = "ops_dm_01";
});
afterEach(() => server.resetHandlers());

function show(item = LOAD_TEST) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(ME_KEY, meFor(mockState.userId ?? ""));
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[`/readiness?item=${item}`]}>
          <NuqsAdapter>
            <ReadinessView now={MOCK_NOW} />
          </NuqsAdapter>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const detail = () => screen.getByTestId("readiness-detail");

describe("recording a readiness result", () => {
  it("offers Record result to the owner and saves it at the pre-season review", async () => {
    show();
    const button = await within(await screen.findByTestId("readiness-detail")).findByRole("button", {
      name: "Record result",
    });
    expect(screen.getByTestId("readiness-summary")).toHaveTextContent("2 of 6 ready");
    fireEvent.click(button);
    const dialog = await screen.findByTestId("record-result-dialog");
    expect(dialog).toHaveTextContent("Recorded as of the pre-season review, 6 May 2024.");
    const save = within(dialog).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Note"), {
      target: { value: "Load test passed for 2 h" },
    });
    fireEvent.change(within(dialog).getByLabelText("Evidence link (optional)"), {
      target: { value: "not a link" },
    });
    expect(save).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Evidence link (optional)"), {
      target: { value: "https://eam.example/wo/52" },
    });
    fireEvent.click(save);
    await waitFor(() => expect(screen.getByTestId("readiness-summary")).toHaveTextContent("3 of 6 ready"));
    expect(within(detail()).getByTestId("readiness-result")).toHaveTextContent("Load test passed for 2 h");
    expect(within(detail()).getByRole("link", { name: "Evidence" })).toHaveAttribute(
      "href",
      "https://eam.example/wo/52",
    );
    expect(within(detail()).getAllByText("Ready").length).toBeGreaterThan(0);
  });

  it("records a waiver as its own status, not as ready", async () => {
    show();
    fireEvent.click(
      await within(await screen.findByTestId("readiness-detail")).findByRole("button", {
        name: "Record result",
      }),
    );
    const dialog = await screen.findByTestId("record-result-dialog");
    fireEvent.click(within(dialog).getByRole("radio", { name: "Waived" }));
    fireEvent.change(within(dialog).getByLabelText("Note"), {
      target: { value: "Generator replaced in June" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(detail()).toHaveTextContent("This check was waived."));
    expect(screen.getByTestId("readiness-summary")).toHaveTextContent("2 of 6 ready");
  });

  it("shows no controls to anyone but the owner function", async () => {
    mockState.userId = "exec_01";
    show();
    await screen.findByTestId("readiness-detail");
    await waitFor(() => expect(screen.getAllByTestId("readiness-row").length).toBeGreaterThan(0));
    expect(within(detail()).queryByRole("button", { name: "Record result" })).toBeNull();
  });

  it("shows no controls while the permissions cannot be read", async () => {
    server.use(http.get("/api/me/permissions", () => HttpResponse.json({}, { status: 500 })));
    show();
    await screen.findByTestId("readiness-detail");
    expect(within(detail()).queryByRole("button", { name: "Record result" })).toBeNull();
  });

  it("says plainly when the API refuses", async () => {
    server.use(
      http.post("/api/readiness/:id", () =>
        HttpResponse.json({ error: { code: "READINESS_NOT_OWNER", message: "no" } }, { status: 403 }),
      ),
    );
    show();
    fireEvent.click(
      await within(await screen.findByTestId("readiness-detail")).findByRole("button", {
        name: "Record result",
      }),
    );
    const dialog = await screen.findByTestId("record-result-dialog");
    fireEvent.change(within(dialog).getByLabelText("Note"), { target: { value: "Load test passed" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Only the owner of this check can record its result.",
    );
  });
});
