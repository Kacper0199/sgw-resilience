import { execSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { type APIRequestContext, expect, type Page, request as pwRequest, test } from "@playwright/test";
import { login, USER } from "./support/login";

/**
 * G1 live thin slice (PS-17): runs against the real stack (`uv run sgw up --demo`, `uv run sgw seed --demo`) through
 * the Vite proxy. The scenario clock and the water run are driven through the API, as the golden path does; every
 * decision the test signs, and every page it checks, goes through the browser.
 */
const BASE = `http://127.0.0.1:${process.env.SGW_E2E_PORT ?? 61800}`;
const ADVISORY_N = "2024-09-26T09:05:00Z";
const ADVISORY_N1 = "2024-09-26T15:05:00Z";
const CREW_TITLE = "Pre-position crews at Sandhill and Millpond yards";
const PS17_TITLE = "Hook up the portable generator at PS-17";

function demoEnv(): Record<string, string> {
  const common = execSync("git rev-parse --path-format=absolute --git-common-dir", {
    encoding: "utf8",
  }).trim();
  const candidates = [
    process.env.SGW_DEMO_ENV,
    resolve(common, "..", "var", "demo.env"),
    resolve("..", "var", "demo.env"),
  ];
  const file = candidates.find((c): c is string => Boolean(c) && existsSync(c as string));
  if (!file) throw new Error("var/demo.env not found; run `uv run sgw bootstrap`");
  const out: Record<string, string> = {};
  for (const line of readFileSync(file, "utf8").split("\n")) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (m) out[m[1]] = m[2];
  }
  return out;
}

const password = (user: string): string => {
  const env = demoEnv();
  return env[`DEMO_PASSWORD_${user.toUpperCase()}`] ?? env.DEMO_PASSWORD ?? "";
};

async function apiAs(
  user: string,
): Promise<{ ctx: APIRequestContext; post: (path: string, body: unknown) => Promise<unknown> }> {
  const ctx = await pwRequest.newContext({ baseURL: BASE, extraHTTPHeaders: { Origin: BASE } });
  const login = await ctx.post("/api/auth/login", { data: { user_id: user, password: password(user) } });
  expect(login.ok(), `login as ${user}`).toBeTruthy();
  const csrf = (await ctx.storageState()).cookies.find((c) => c.name === "sgw_csrf")?.value ?? "";
  const post = async (path: string, body: unknown) => {
    const res = await ctx.post(path, { data: body, headers: { "X-CSRF-Token": csrf } });
    expect(res.ok(), `${path}: ${res.status()}`).toBeTruthy();
    return res.json();
  };
  return { ctx, post };
}

async function seek(time: string): Promise<void> {
  const ops = await apiAs("ops_dm_01");
  await ops.post("/api/scenario", { action: "seek", scenario_time: time });
  await ops.ctx.dispose();
  await new Promise((r) => setTimeout(r, 7000));
}

async function runWaterContinuity(advisory: string): Promise<void> {
  const ops = await apiAs("ops_dm_01");
  const open = (await (await ops.ctx.get("/api/proposals")).json()) as {
    decision_case_id: string;
    state: string;
  }[];
  if (open.some((p) => p.decision_case_id === "DC-D3-PS17-POWER" && p.state !== "expired")) {
    await ops.ctx.dispose();
    return;
  }
  const thread = (await ops.post("/api/threads", { module: "water" })) as { thread_id: string };
  await ops.post(`/api/threads/${thread.thread_id}/runs`, { graph: "water_continuity", input: { advisory } });
  const stream = await ops.ctx.get(`/api/threads/${thread.thread_id}/events`, { timeout: 90_000 });
  expect(await stream.text()).toContain("event: run_paused");
  await ops.ctx.dispose();
}

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

const row = (page: Page, text: string) => page.getByTestId("decision-row").filter({ hasText: text }).first();

test.describe.configure({ mode: "serial" });

/** The story seeks, signs and runs the water graph on the live stack: load the demo moment back afterwards
 * (as "Load moment" does), so the stack is left as `sgw demo goto` set it and Ask replays its recordings. */
test.afterAll(async () => {
  const moment = process.env.SGW_G1_RESTORE_MOMENT ?? "at-n1";
  const ops = await apiAs("ops_dm_01");
  const csrf = (await ops.ctx.storageState()).cookies.find((c) => c.name === "sgw_csrf")?.value ?? "";
  const res = await ops.ctx.post("/api/demo/goto", {
    data: { bookmark: moment },
    headers: { "X-CSRF-Token": csrf },
    timeout: 120_000,
  });
  await ops.ctx.dispose();
  if (res.status() !== 503) expect(res.ok(), `load ${moment} back: ${res.status()}`).toBeTruthy();
});

test("PS-17 story on the live stack", async ({ page }) => {
  const errors = collectErrors(page);

  await test.step("advisory N: login, the queue loads, stream is live", async () => {
    await seek(ADVISORY_N);
    await login(page, USER.commander, { password: password(USER.commander) });
    await expect(page.getByRole("heading", { name: "Decisions" })).toBeVisible();
    await expect(row(page, CREW_TITLE)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("stream-state")).toContainText("Connected");
    await expect(page.getByTestId("mode-strip")).toContainText("synthetic SGW data");
  });

  await test.step("sign the crew decision as Command; Cmd+K stays shut behind the dialog", async () => {
    await row(page, CREW_TITLE).click();
    const sign = page.getByRole("button", { name: /^Sign as / });
    if (await sign.isEnabled()) {
      await sign.click();
      const dialog = page.getByRole("dialog");
      await page.keyboard.press("ControlOrMeta+k");
      await expect(page.getByRole("dialog")).toHaveCount(1);
      await dialog.getByRole("button", { name: "Sign", exact: true }).click();
      await expect(page.getByText("Signed. Waiting for the other team.")).toBeVisible();
    }
    await expect(page.getByTestId("case-header")).toContainText(/[1-9] of \d/);
  });

  await test.step("advisory N+1: PS-17 joins the queue and the crew decision moves earlier", async () => {
    await seek(ADVISORY_N1);
    await runWaterContinuity("N+1");
    await expect(row(page, PS17_TITLE)).toBeVisible({ timeout: 20_000 });
    await expect(row(page, PS17_TITLE)).toContainText("Before next advisory");
    const rows = page.getByTestId("decision-row");
    const crewIndex = await rows.evaluateAll((els) =>
      els.findIndex((e) => e.textContent?.includes("Pre-position crews at Sandhill")),
    );
    const ps17Index = await rows.evaluateAll((els) =>
      els.findIndex((e) => e.textContent?.includes("Hook up the portable generator")),
    );
    expect(crewIndex).toBeGreaterThanOrEqual(0);
    expect(ps17Index).toBeGreaterThan(crewIndex);
    await row(page, CREW_TITLE).click();
    await expect(page.getByTestId("shift-chip")).toContainText("Earlier by");
    await expect(page.getByTestId("void-banner")).toContainText("no longer counts");
  });

  await test.step("the Brief shows its four numbers", async () => {
    await page.getByRole("link", { name: "Briefing", exact: true }).click();
    await expect(page.getByTestId("status-header")).toBeVisible();
    await expect(page.getByTestId("four-numbers").locator("> div")).toHaveCount(4);
    await expect(page.getByTestId("open-clock").first()).toBeVisible();
  });

  await test.step("Ask AI opens with its empty state (no question is sent on the live stack)", async () => {
    await page.getByRole("link", { name: "Ask AI", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Where should we start?" })).toBeVisible();
    await expect(page.getByRole("button", { name: "New conversation" })).toHaveCount(0);
    await expect(page.getByRole("complementary", { name: "Sources" })).toHaveCount(0);
  });

  await test.step("Health renders its status lines", async () => {
    await page.getByRole("link", { name: "System health", exact: true }).click();
    await expect(page.getByRole("heading", { name: "System health", exact: true })).toBeVisible();
    await expect(page.getByText("Data on time", { exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "Models" }).click();
    await expect(page.getByText(/models? in use/).first()).toBeVisible();
  });

  expect(errors.filter((e) => !/favicon/.test(e))).toEqual([]);
});
