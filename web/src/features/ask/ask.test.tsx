import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";
import { ME_KEY } from "@/auth/useSession";
import { TooltipProvider } from "@/components/ui/tooltip";
import { MOCK_NOW, meFor } from "@/mocks/fixtures";
import { mockState, resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import AskPage from "./AskPage";
import { STARTERS } from "./starters";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  localStorage.clear();
  sessionStorage.setItem("sgw.mock.fast", "1");
});
afterEach(() => {
  server.resetHandlers();
  sessionStorage.clear();
});

function show(search = "") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(ME_KEY, meFor("ic_01"));
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TooltipProvider>
          <NuqsTestingAdapter searchParams={search} hasMemory>
            <AskPage />
          </NuqsTestingAdapter>
        </TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const starter = (i: number) => screen.getByRole("button", { name: STARTERS[i] });
const ask = (text: string) => {
  const box = screen.getByRole("textbox", { name: "Ask about the storm response" });
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: "Enter" });
};

describe("Ask AI", () => {
  it("opens with starter questions, no New conversation yet, no history panel and no Sources", () => {
    show();
    expect(screen.getByTestId("starters")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Where should we start?" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New conversation" })).toBeNull();
    expect(screen.queryByRole("complementary", { name: "Chat history" })).toBeNull();
    expect(screen.queryByRole("complementary", { name: "Sources" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sources" })).toBeNull();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("opens and closes the chat history from the left icon", async () => {
    show();
    const toggle = screen.getByRole("button", { name: "Show chat history" });
    fireEvent.click(toggle);
    expect(await screen.findByRole("complementary", { name: "Chat history" })).toBeInTheDocument();
    expect(screen.getByText("No chats yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide chat history" }));
    expect(screen.queryByRole("complementary", { name: "Chat history" })).toBeNull();
  });

  it("answers with one source pill per document, opens Sources by itself and shows the quoted passage", async () => {
    show();
    fireEvent.click(starter(3));
    const answer = await screen.findByTestId("answer-text", undefined, { timeout: 6000 });
    const badges = within(answer).getAllByTestId("source-badge");
    expect(badges).toHaveLength(1);
    expect(await screen.findByRole("complementary", { name: "Sources" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2 sources" })).toBeInTheDocument();
    fireEvent.click(badges[0]);
    const card = (await screen.findAllByTestId("source-card"))[0];
    expect(card).toHaveAttribute("data-active", "true");
    expect(card).toHaveTextContent("DOM 14.206 Rev K");
    expect(card).toHaveTextContent("Revise a published ETR");
  });

  it("keeps Sources closed for the chat once the person closes it, and reopens it from the toggle", async () => {
    show();
    fireEvent.click(starter(3));
    await screen.findByTestId("answer-text", undefined, { timeout: 6000 });
    fireEvent.click((await screen.findAllByRole("button", { name: "Hide sources" }))[0]);
    expect(screen.queryByRole("complementary", { name: "Sources" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Sources" }));
    expect(await screen.findByRole("complementary", { name: "Sources" })).toBeInTheDocument();
  });

  it("offers two questions to ask next and a New conversation that starts clean", async () => {
    show();
    fireEvent.click(starter(3));
    await screen.findByTestId("answer-text", undefined, { timeout: 6000 });
    const next = screen.getByRole("list", { name: "Questions to ask next" });
    expect(within(next).getAllByRole("button")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(await screen.findByTestId("starters")).toBeInTheDocument();
  });

  it("says plainly when the answer is not in the documents", async () => {
    show();
    ask("What is our 2025 vegetation management budget?");
    const box = await screen.findByTestId("abstain", undefined, { timeout: 6000 });
    expect(box).toHaveTextContent("I couldn't find this");
    expect(box).not.toHaveTextContent("Not found");
    expect(screen.queryByRole("complementary", { name: "Sources" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sources" })).toBeNull();
    expect(screen.queryByTestId("source-card")).toBeNull();
  });

  it("offers the questions to ask next in Polish after a Polish question", async () => {
    show();
    ask("Ilu klientów nie ma prądu?");
    await screen.findByTestId("answer", undefined, { timeout: 6000 });
    const next = await screen.findByRole("list", { name: "Pytania na dalej" });
    const asked = within(next)
      .getAllByRole("button")
      .map((b) => b.textContent);
    expect(asked.length).toBeGreaterThan(0);
    for (const q of asked) expect(STARTERS).not.toContain(q);
    expect(asked).toContain("Co najnowszy komunikat o huraganie oznacza dla terminu PS-17?");
  });

  it("shows damage photos inline, opens a photo's detail in place and links to the Crews page", async () => {
    show();
    ask("Show me the photos of the flooded area");
    const strip = await screen.findByTestId("answer-photos", undefined, { timeout: 6000 });
    const tiles = within(strip).getAllByTestId("answer-photo");
    expect(tiles).toHaveLength(4);
    expect(tiles[0]).toHaveAttribute("href", "/crews?photo=ladi-v2-test-0016");
    expect(within(strip).getAllByRole("img")[0]).toHaveAttribute("alt", "Flooded road near Aiken");
    expect(within(strip).getByText(/Civil Air Patrol/)).toBeInTheDocument();
    const link = within(screen.getByTestId("answer-links")).getByRole("link", { name: "All damage photos" });
    expect(link).toHaveAttribute("href", "/crews?tab=photos");
    fireEvent.click(tiles[0]);
    expect(await screen.findByTestId("photo-preview")).toBeInTheDocument();
  });

  it("answers a where-is question with page chips that open inside the app, and keeps the conversation", async () => {
    show();
    ask("Where can I find information about water?");
    const links = await screen.findByTestId("answer-links", undefined, { timeout: 6000 });
    expect(
      within(links)
        .getAllByRole("link")
        .map((a) => a.getAttribute("href")),
    ).toEqual(["/water", "/water?zone=WZ-PS17-CEDARFALL", "/map"]);
    expect(screen.queryByTestId("abstain")).toBeNull();
    const chips = screen.getByRole("list", { name: "Questions to ask next" });
    expect(within(chips).getAllByRole("button")).toHaveLength(3);
    fireEvent.click(within(chips).getByRole("button", { name: "Show the damage photos" }));
    expect(await screen.findByTestId("answer-photos", undefined, { timeout: 6000 })).toBeInTheDocument();
    expect(screen.getAllByTestId("turn")).toHaveLength(2);
  });

  it("declines an unrelated question helpfully: what Ask can do and three questions to try, no Not found", async () => {
    show();
    ask("What is the weather in Paris?");
    const text = await screen.findByTestId("answer-text", undefined, { timeout: 6000 });
    expect(text).toHaveTextContent("outside what I can help with");
    expect(screen.queryByTestId("abstain")).toBeNull();
    expect(screen.queryByText(/Not found/)).toBeNull();
    const chips = screen.getByRole("list", { name: "Questions to ask next" });
    expect(within(chips).getAllByRole("button")).toHaveLength(3);
  });

  it("asks 'did you mean' with clickable choices that ask in the same conversation", async () => {
    show();
    ask("status of ps71");
    const text = await screen.findByTestId("answer-text", undefined, { timeout: 6000 });
    expect(text).toHaveTextContent("Did you mean");
    const choices = screen.getByRole("list", { name: "Did you mean" });
    expect(within(choices).getAllByRole("button")).toHaveLength(2);
    fireEvent.click(within(choices).getByRole("button", { name: "What is the status of PS-17?" }));
    await waitFor(() => expect(screen.getAllByTestId("turn")).toHaveLength(2), { timeout: 6000 });
  });

  it("says an off-platform topic is not here, with a page link and a question to try", async () => {
    show();
    ask("tide tables for Charleston");
    const links = await screen.findByTestId("answer-links", undefined, { timeout: 6000 });
    expect(within(links).getByRole("link", { name: "Forecast page" })).toHaveAttribute("href", "/forecast");
    expect(screen.queryByTestId("abstain")).toBeNull();
    const next = screen.getByRole("list", { name: "Questions to ask next" });
    expect(within(next).getAllByRole("button")).toHaveLength(1);
  });

  it("shows findings only when the written answer did not pass its checks", async () => {
    show();
    ask("What do the procedures say about paper tickets?");
    const box = await screen.findByTestId("findings-only", undefined, { timeout: 6000 });
    expect(box).toHaveTextContent("failed its source check");
    expect(within(box).getByText("DOM 14.190 Rev B")).toBeInTheDocument();
  });

  it("marks an unverified field record next to the answer and in its source card", async () => {
    show();
    ask("Any new tickets?");
    await screen.findByTestId("answer-text", undefined, { timeout: 6000 });
    expect(screen.getByText(/Uses an unverified field report/)).toBeInTheDocument();
    const cards = await screen.findAllByTestId("source-card");
    expect(cards[0]).toHaveTextContent("Unverified field report");
  });

  it("shows one live step line while it works, then the answer with linked ids", async () => {
    sessionStorage.removeItem("sgw.mock.fast");
    mockState.userId = "ic_01";
    show();
    fireEvent.click(starter(0));
    await waitFor(
      () => expect(screen.getByTestId("steps-summary")).toHaveTextContent("Reading the decision"),
      { timeout: 4000 },
    );
    expect(screen.getAllByTestId("steps")).toHaveLength(1);
    const answer = await screen.findByTestId("answer-text", undefined, { timeout: 8000 });
    expect(screen.getByTestId("steps-summary")).toHaveTextContent(/^Checked 3 decisions/);
    await waitFor(() =>
      expect(
        within(answer)
          .getAllByTestId("ref-chip")
          .map((c) => c.textContent),
      ).toEqual([
        "latest advisory",
        "PS-17",
        "Hook up the portable generator at PS-17",
        "Dispatch the fuel truck to PS-17",
      ]),
    );
    await waitFor(() =>
      expect(
        within(answer).getByRole("link", { name: /^Hook up the portable generator at PS-17/ }),
      ).toHaveAttribute("href", "/?d=PRP-PS17-FDR2207-PRIO"),
    );
    expect(within(answer).getByRole("link", { name: /^PS-17/ })).toHaveAttribute("href", "/map?asset=PS-17");
    expect(within(answer).getByRole("link", { name: /^latest advisory/ })).toHaveAttribute(
      "href",
      "/forecast?tab=changes",
    );
  }, 15000);

  it("answers from platform data with linked ids when the assistant cannot write", async () => {
    mockState.userId = "ic_01";
    show();
    ask("Which crews are at the Sandhill yard?");
    const box = await screen.findByTestId("findings-only", undefined, { timeout: 6000 });
    expect(box).toHaveTextContent("From platform data");
    expect(box).not.toHaveTextContent("failed its source check");
    expect(await within(box).findByRole("link", { name: /^Pre-position crews/ })).toBeInTheDocument();
    expect(screen.queryByTestId("unavailable")).toBeNull();
  });

  it("lets the person stop a run", async () => {
    sessionStorage.removeItem("sgw.mock.fast");
    show();
    fireEvent.click(starter(0));
    fireEvent.click(await screen.findByRole("button", { name: "Stop response" }));
    expect(
      await screen.findByText("Stopped before the answer was written.", undefined, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("explains a refused start in plain words", async () => {
    server.use(
      http.post("/api/threads/:id/runs", () =>
        HttpResponse.json({ error: { code: "RUN_ACTIVE", message: "busy" } }, { status: 409 }),
      ),
    );
    show();
    fireEvent.click(starter(0));
    expect(await screen.findByRole("alert")).toHaveTextContent("An answer is still being written");
  });

  it("explains a role that cannot start a conversation", async () => {
    server.use(
      http.post("/api/threads", () =>
        HttpResponse.json({ error: { code: "FORBIDDEN", message: "no" } }, { status: 403 }),
      ),
    );
    show();
    fireEvent.click(starter(0));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your role can't use this.");
  });

  it("keeps the run with its plan and step details under Show steps", async () => {
    show();
    fireEvent.click(starter(2));
    await screen.findByTestId("answer-text", undefined, { timeout: 6000 });
    fireEvent.click(screen.getByRole("button", { name: /Show steps/ }));
    expect(screen.getByRole("list", { name: "Steps" })).toHaveTextContent("Checked water status");
    fireEvent.click(screen.getByRole("button", { name: "Step details" }));
    const detail = await screen.findByTestId("run-detail");
    expect(within(detail).getByRole("list", { name: "Plan" }).children).toHaveLength(3);
    const log = within(detail).getByRole("table", { name: "Step details" });
    expect(within(log).getByText("Checked water status")).toBeInTheDocument();
    expect(screen.getAllByTestId("run-row")).toHaveLength(1);
  });

  it("says so when feedback is not collected yet, and records it when it is", async () => {
    server.use(http.post("/api/threads/:t/runs/:r/feedback", () => new HttpResponse(null, { status: 404 })));
    show();
    fireEvent.click(starter(2));
    await screen.findByTestId("answer-text", undefined, { timeout: 6000 });
    fireEvent.click(screen.getByRole("button", { name: "Helpful" }));
    expect(await screen.findByText("Feedback isn't available yet.")).toBeInTheDocument();
    server.resetHandlers();
    fireEvent.click(screen.getByRole("button", { name: "Helpful" }));
    expect(await screen.findByText("Thanks for the feedback.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Helpful" })).toHaveAttribute("aria-pressed", "true");
  });

  it("restores an earlier conversation from the server's messages", async () => {
    const message = (id: string, role: "user" | "assistant", text: string) => ({
      message_id: id,
      role,
      text,
      created_at: MOCK_NOW,
      evidence_ids: [],
    });
    server.use(
      http.get("/api/threads/thr-old/messages", () =>
        HttpResponse.json([
          message("run-old.q", "user", "Which stations have generators?"),
          message("run-old.a", "assistant", "PS-38 and PS-52 have generators."),
        ]),
      ),
    );
    show("?t=thr-old");
    expect(await screen.findByText("PS-38 and PS-52 have generators.")).toBeInTheDocument();
    expect(screen.getByTestId("user-message")).toHaveTextContent("Which stations have generators?");
  });
});
