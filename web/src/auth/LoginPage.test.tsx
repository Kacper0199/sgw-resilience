import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll } from "vitest";
import { mockState, resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { LoginPage } from "./LoginPage";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
afterEach(() => {
  server.resetHandlers();
  resetMock();
});

const renderLogin = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

const notDemo = () => server.use(http.get("/api/auth/config", () => HttpResponse.json({ demo_mode: false })));
const openPeople = async () => {
  fireEvent.click(await screen.findByRole("button", { name: /Demo people/ }));
  return screen.findByRole("listbox", { name: "Demo people" });
};

describe("login page", () => {
  it("offers the Demo people chooser and the demo password note only in demo mode", async () => {
    renderLogin();
    const list = await openPeople();
    expect(within(list).getAllByRole("option")).toHaveLength(7);
    expect(screen.getByRole("button", { name: "Other accounts (4)" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByText("Demo password is 123. Demo only.")).toBeInTheDocument();
  });

  it("fills the user ID and the demo password when a person is picked, and signs in as them", async () => {
    renderLogin();
    const list = await openPeople();
    fireEvent.click(within(list).getByRole("option", { name: /Water Incident Lead/ }));
    expect(screen.getByLabelText("User ID")).toHaveValue("wtr_lead_01");
    expect(screen.getByLabelText("Password", { exact: true })).toHaveValue("123");
    expect(screen.getByText(/signs as Water operations/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(mockState.userId).toBe("wtr_lead_01"));
  });

  it("shows no password hint and fills no password when the server gives no demo password", async () => {
    server.use(http.get("/api/auth/config", () => HttpResponse.json({ demo_mode: true })));
    renderLogin();
    const list = await openPeople();
    expect(screen.queryByText(/Demo password/)).not.toBeInTheDocument();
    fireEvent.click(within(list).getByRole("option", { name: /Water Incident Lead/ }));
    expect(screen.getByLabelText("User ID")).toHaveValue("wtr_lead_01");
    expect(screen.getByLabelText("Password", { exact: true })).toHaveValue("");
    await waitFor(() => expect(screen.getByLabelText("Password", { exact: true })).toHaveFocus());
  });

  it("folds the four other accounts under one button", async () => {
    renderLogin();
    await openPeople();
    const more = screen.getByRole("button", { name: "Other accounts (4)" });
    fireEvent.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    const others = screen.getByRole("listbox", { name: "Other accounts" });
    fireEvent.click(within(others).getByRole("option", { name: /Data and Models Owner/ }));
    expect(screen.getByLabelText("User ID")).toHaveValue("ml_01");
  });

  it("moves with the arrow keys and closes on Escape with focus back on the button", async () => {
    renderLogin();
    const trigger = await screen.findByRole("button", { name: /Demo people/ });
    fireEvent.click(trigger);
    const options = within(await screen.findByRole("listbox", { name: "Demo people" })).getAllByRole(
      "option",
    );
    await waitFor(() => expect(options[0]).toHaveFocus());
    fireEvent.keyDown(options[0] as HTMLElement, { key: "ArrowDown" });
    expect(options[1]).toHaveFocus();
    fireEvent.keyDown(options[1] as HTMLElement, { key: "Escape" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("shows only user ID and password, and no demo password, when demo mode is off", async () => {
    notDemo();
    renderLogin();
    expect(await screen.findByLabelText("User ID")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Demo people/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Demo password/)).not.toBeInTheDocument();
  });

  it("treats a missing config endpoint as not demo", async () => {
    server.use(http.get("/api/auth/config", () => new HttpResponse(null, { status: 404 })));
    renderLogin();
    expect(await screen.findByLabelText("User ID")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /Demo people/ })).not.toBeInTheDocument(),
    );
  });

  it("signs in with a typed user id", async () => {
    notDemo();
    renderLogin();
    fireEvent.change(await screen.findByLabelText("User ID"), { target: { value: "wtr_lead_01" } });
    fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "demo" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(mockState.userId).toBe("wtr_lead_01"));
  });

  it("shows the server's reason as a sentence and marks both fields invalid", async () => {
    notDemo();
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json(
          { error: { code: "UNAUTHENTICATED", message: "invalid user id or password" } },
          { status: 401 },
        ),
      ),
    );
    renderLogin();
    fireEvent.change(await screen.findByLabelText("User ID"), { target: { value: "ic_01" } });
    fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid user ID or password.");
    expect(screen.getByLabelText("User ID")).toHaveAttribute("aria-invalid", "true");
  });

  it("asks for a person or a password instead of sending an empty form", async () => {
    notDemo();
    renderLogin();
    fireEvent.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a person or enter a user ID.");
    expect(screen.getByLabelText("User ID")).toHaveFocus();
    fireEvent.change(screen.getByLabelText("User ID"), { target: { value: "ic_01" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter your password.");
    expect(mockState.userId).not.toBe("ic_01");
  });

  it("shows and hides the password", async () => {
    notDemo();
    renderLogin();
    const field = await screen.findByLabelText("Password", { exact: true });
    expect(field).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(field).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Hide password" })).toBeInTheDocument();
  });
});
