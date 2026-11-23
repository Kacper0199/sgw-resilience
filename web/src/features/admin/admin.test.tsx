import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import { MemoryRouter } from "react-router";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";
import { POLICIES } from "@/contracts/policies.gen";
import { scenario } from "@/mocks/fixtures";
import { mockState, resetMock } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import AdminPage from "./AdminPage";
import { AiConfigTab } from "./AiConfigTab";
import { isAdmin, policyName } from "./format";
import { IntegrationsTab } from "./IntegrationsTab";
import { MetricsTab } from "./MetricsTab";
import { integrations } from "./mocks";
import aiConfig from "./mocks/ai-config.json";
import rights from "./mocks/rights.json";
import users from "./mocks/users.json";
import { PoliciesTab, policyHref } from "./PoliciesTab";
import { UsersTab } from "./UsersTab";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMock();
  mockState.userId = "admin_01";
  // biome-ignore lint/suspicious/noDocumentCookie: the session probe skips /api/me without the CSRF cookie
  document.cookie = "sgw_csrf=test; path=/";
});
afterEach(() => server.resetHandlers());

function show(ui: React.ReactElement, search = "") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <NuqsTestingAdapter searchParams={search}>
        <MemoryRouter>{ui}</MemoryRouter>
      </NuqsTestingAdapter>
    </QueryClientProvider>,
  );
}

describe("format", () => {
  it("reads policy keys as settings without their unit suffix", () => {
    expect(policyName("policy_break_glass_cosign_hours")).toBe("Emergency approval co-sign");
    expect(policyName("policy_approval_ttl_t3_min")).toBe("Approval expiry, two-team decisions");
    expect(policyName("policy_evidence_age_t1_min")).toBe("Evidence age, one-person decisions");
    expect(policyName("policy_c3_aggregation_assets")).not.toMatch(/C3/);
    expect(policyName("policy_equity_weight")).toBe("Equity weight");
  });

  it("builds the deep link a policy chip uses", () => {
    expect(policyHref("policy_envelope_pct")).toBe("/admin?tab=policies&key=policy_envelope_pct");
  });

  it("treats the platform function or the platform_admin role as admin", () => {
    expect(isAdmin({ function: "platform", roles: [] })).toBe(true);
    expect(isAdmin({ function: "data", roles: ["platform_admin"] })).toBe(true);
    expect(isAdmin({ function: "command", roles: ["incident_commander"] })).toBe(false);
    expect(isAdmin(null)).toBe(false);
  });
});

describe("Users and roles", () => {
  it("lists every person with their function and how much they may sign", async () => {
    show(<UsersTab />);
    const rows = await screen.findAllByTestId("user-row");
    expect(rows).toHaveLength(users.length);
    const commander = rows[0] as HTMLElement;
    const held = rights.find((r) => r.user_id === "ic_01")?.may_approve.length;
    expect(within(commander).getAllByText("Incident Commander").length).toBeGreaterThan(0);
    expect(within(commander).getByText(`${held} actions`)).toBeInTheDocument();
    expect(within(commander).getByText("Can approve alone in an emergency")).toBeInTheDocument();
  });

  it("opens a person's rights with tiers and whether they sign or only when escalated", async () => {
    show(<UsersTab />);
    const rows = await screen.findAllByTestId("user-row");
    fireEvent.click(rows[1] as HTMLElement);
    expect(rows[1]).toHaveAttribute("aria-current", "true");
    const list = screen.getAllByTestId("right-row");
    expect(list.length).toBeGreaterThan(0);
    expect(screen.getByTestId("person-pane")).toHaveTextContent(users[1]?.display_name ?? "");
  });

  it("pivots to who may sign each action", async () => {
    show(<UsersTab />);
    await screen.findAllByTestId("user-row");
    fireEvent.click(screen.getByRole("radio", { name: /^By action/ }));
    const row = screen
      .getAllByTestId("action-row")
      .find((r) => r.textContent?.includes("Issue a boil-water notice"));
    expect(row).toHaveTextContent("Water Incident Lead");
    expect(row).toHaveTextContent("Water Compliance Officer");
  });

  it("explains a 403 instead of showing an empty table", async () => {
    server.use(
      http.get("/api/admin/users", () =>
        HttpResponse.json({ error: { code: "ADMIN_ONLY", message: "no" } }, { status: 403 }),
      ),
    );
    show(<UsersTab />);
    expect(await screen.findByText("Only platform administrators can see users.")).toBeInTheDocument();
  });
});

describe("Policies", () => {
  it("lists every policy value with its unit and source, read-only", async () => {
    show(<PoliciesTab selectedKey={null} />);
    const rows = await screen.findAllByTestId("policy-row");
    expect(rows).toHaveLength(Object.keys(POLICIES).length);
    expect(within(screen.getByTestId("policy-table")).queryAllByRole("textbox")).toHaveLength(0);
    const key = "policy_break_glass_cosign_hours";
    const row = rows.find((r) => r.textContent?.includes(key));
    expect(row).toHaveTextContent(`${POLICIES[key as keyof typeof POLICIES].value} hours`);
  });

  it("highlights the row a policy chip points to and keeps it when filtering", async () => {
    show(<PoliciesTab selectedKey="policy_envelope_pct" />);
    const rows = await screen.findAllByTestId("policy-row");
    const selected = rows.filter((r) => r.getAttribute("aria-current") === "true");
    expect(selected).toHaveLength(1);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search settings" }), {
      target: { value: "cosign" },
    });
    expect(screen.getAllByTestId("policy-row").some((r) => r.getAttribute("aria-current") === "true")).toBe(
      true,
    );
  });

  it("says when a deep link names an unknown policy", async () => {
    show(<PoliciesTab selectedKey="policy_not_there" />);
    await screen.findAllByTestId("policy-row");
    expect(screen.getByTestId("policy-missing")).toHaveTextContent("policy_not_there");
  });

  it("filters by words in the name or source", async () => {
    show(<PoliciesTab selectedKey={null} />);
    await screen.findAllByTestId("policy-row");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search settings" }), {
      target: { value: "zzzz" },
    });
    expect(screen.getByText("No settings match.")).toBeInTheDocument();
  });
});

describe("Integrations", () => {
  it("lists tokens by scope and state, subscriptions by host and the latest deliveries", async () => {
    show(<IntegrationsTab />);
    const tokens = await screen.findAllByTestId("token-row");
    expect(tokens).toHaveLength(integrations.tokens.length);
    expect(within(tokens[0] as HTMLElement).getByText("decisions:read")).toBeInTheDocument();
    expect(within(tokens[0] as HTMLElement).getByText("Active")).toBeInTheDocument();
    expect(within(tokens[2] as HTMLElement).getByText("Revoked")).toBeInTheDocument();
    const subs = screen.getAllByTestId("sub-row");
    expect(subs).toHaveLength(integrations.subscriptions.length);
    expect(within(subs[1] as HTMLElement).getByText("Disabled")).toBeInTheDocument();
    expect(within(subs[1] as HTMLElement).getByText("The receiver answered 410 Gone")).toBeInTheDocument();
    const failed = screen.getAllByTestId("delivery-row").find((r) => r.textContent?.includes("Failed"));
    expect(failed).toHaveTextContent("8");
  });

  it("never shows a secret, a hash or a full URL", async () => {
    show(<IntegrationsTab />);
    await screen.findAllByTestId("token-row");
    expect(document.body.textContent).not.toMatch(/whsec_|sgwi_|https?:\/\//);
  });
});

describe("AI configuration", () => {
  it("shows model, effort, data ceiling, tools and the latest check for every step", async () => {
    show(<AiConfigTab />);
    const rows = await screen.findAllByTestId("ai-row");
    expect(rows).toHaveLength(aiConfig.nodes.length);
    const investigate = rows.find((r) => r.textContent?.includes("Look things up"));
    expect(investigate).toHaveTextContent("Decision deadline");
    const text = rows.find((r) => r.textContent?.includes("Explain a decision card"));
    expect(text).toHaveTextContent("None (text only)");
    expect(screen.getByTestId("ai-table").textContent).not.toMatch(
      /narrate|rag_chunk_header|get_decision_case/,
    );
    expect(screen.queryByText(/llm_nodes\.yaml/)).toBeNull();
    expect(screen.getByText(/Settings version/)).toBeInTheDocument();
    expect(screen.getByTestId("ai-table").textContent).not.toMatch(/prompt|Instructions v/i);
  });
});

describe("System metrics", () => {
  it("shows the platform's own request numbers without any terminal instructions", async () => {
    show(<MetricsTab />);
    const tab = await screen.findByTestId("metrics");
    expect(tab).toHaveTextContent("4,812");
    expect(tab).toHaveTextContent("182 ms");
    expect(await screen.findAllByTestId("metrics-route")).toHaveLength(5);
    expect(tab.textContent).not.toMatch(/uv run|obs up|server:|terminal/i);
    expect(screen.queryByRole("link", { name: /Open Grafana/ })).not.toBeInTheDocument();
  });

  it("adds the Grafana link only when monitoring answers", async () => {
    server.use(
      http.get("/api/admin/system", () =>
        HttpResponse.json({ obs_profile_up: true, grafana_url: "http://127.0.0.1:3001/" }),
      ),
    );
    show(<MetricsTab />);
    const link = await screen.findByRole("link", { name: /Open Grafana/ });
    expect(link).toHaveAttribute("href", "http://127.0.0.1:3001/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("says there are no metrics yet when the server has no system route", async () => {
    server.use(http.get("/api/admin/system", () => new HttpResponse(null, { status: 404 })));
    show(<MetricsTab />);
    expect(await screen.findByText("No system metrics yet.")).toBeInTheDocument();
  });
});

describe("Admin page", () => {
  it("opens the requested tab and policy from the URL", async () => {
    show(<AdminPage />, "?tab=policies&key=policy_envelope_pct");
    const rows = await screen.findAllByTestId("policy-row");
    expect(rows.some((r) => r.getAttribute("aria-current") === "true")).toBe(true);
    expect(screen.getByRole("tab", { name: "Policies" })).toHaveAttribute("aria-selected", "true");
  });

  it("keeps everyone but the platform team out", async () => {
    mockState.userId = "ic_01";
    show(<AdminPage />);
    expect(await screen.findByText(/Admin is for the platform team/)).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Policies" })).not.toBeInTheDocument();
  });

  it("shows the exercise banner only in exercise mode", async () => {
    server.use(http.get("/api/scenario", () => HttpResponse.json({ ...scenario, mode: "EXERCISE" })));
    show(<AdminPage />);
    expect(await screen.findByTestId("exercise-banner")).toBeInTheDocument();
  });
});
