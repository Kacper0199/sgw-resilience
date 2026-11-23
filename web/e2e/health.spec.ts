import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { login, switchUser, USER } from "./support/login";

const TABS = ["data", "models", "runs", "safety"] as const;
const TAB_LABEL = { data: "Data", models: "Models", runs: "AI activity", safety: "Stop controls" } as const;

async function openTab(page: Page, tab: (typeof TABS)[number]) {
  await page.goto(`/health?tab=${tab}`);
  await expect(page.getByRole("tab", { name: TAB_LABEL[tab] })).toHaveAttribute("data-state", "active");
  await expect(page.getByTestId("status-line")).toBeVisible();
  await expect(page.getByRole("status", { name: /Loading/ })).toHaveCount(0);
}

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test("the duty manager reads one plain line per tab and opens the detail one click deeper", async ({
  page,
}) => {
  const errors = collectErrors(page);
  await login(page, USER.dutyManager);
  await page.getByRole("link", { name: "System health", exact: true }).click();
  await expect(page).toHaveURL(/\/health$/);

  await expect(page.getByTestId("status-line")).toContainText("Some data needs attention");
  await expect(page.getByTestId("feed-row").last()).toContainText("Late");
  const first = page.getByTestId("asset-row").first();
  await first.getByRole("button", { name: /Data flow for/ }).click();
  await expect(page.getByTestId("lineage-row")).toContainText("Comes from");

  await page.getByRole("tab", { name: "Models" }).click();
  await expect(page).toHaveURL(/tab=models/);
  const outage = page.getByRole("region", { name: /Outage forecast/ });
  await outage.getByRole("button", { name: "About this model" }).click();
  const about = page.getByRole("dialog", { name: "About this model" });
  await expect(about).toContainText("fitted wind-fragility curve");
  await expect(about).toContainText("did not beat it");
  await expect(about).toContainText("under-calls large storms");
  await page.keyboard.press("Escape");
  await expect(outage.getByTestId("model-fact").first()).toContainText("Below target");
  await expect(page.getByTestId("ai-config-hidden")).toBeVisible();

  await page.getByRole("tab", { name: "AI activity" }).click();
  await expect(page.getByTestId("status-line")).toContainText("failed");
  await expect(page.getByTestId("usage-hidden")).toBeVisible();
  const run = page.getByTestId("agent-run-row").nth(1);
  await run.getByRole("button", { name: /Show steps/ }).click();
  await expect(page.getByTestId("trace-step").first()).toBeVisible();
  await run.getByRole("button", { name: /Hide steps/ }).click();
  await expect(page.getByTestId("trace-row")).toHaveCount(0);

  await page.getByRole("tab", { name: "Stop controls" }).click();
  await expect(page.getByTestId("status-line")).toContainText("Normal operation");
  expect(errors).toEqual([]);
});

test("tabs move with the arrow keys and keep the URL", async ({ page }) => {
  await login(page, USER.dutyManager);
  await openTab(page, "data");
  await page.getByRole("tab", { name: "Data" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/tab=models/);
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/tab=sensors/);
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/tab=runs/);
});

test("the sensor checks sit in System health with the measured catch rate", async ({ page }) => {
  await login(page, USER.waterLead);
  await page.goto("/health?tab=sensors");
  await expect(page.getByTestId("fault-row")).toHaveCount(6);
  await expect(page.getByTestId("recall-statement")).toHaveText(
    "Caught 82 of 115 test faults (71%). Below the 80% target.",
  );
});

test("an administrator sees the model each AI step uses, and executives see the cost", async ({ page }) => {
  await login(page, USER.admin);
  await openTab(page, "models");
  await expect(page.getByTestId("ai-node-row").first()).toBeVisible();
  await expect(page.getByTestId("ai-node-summary")).toContainText("Sonnet");
  await expect(page.getByTestId("ai-node-summary")).toContainText("Haiku");
  await openTab(page, "runs");
  await expect(page.getByTestId("usage-total")).toBeVisible();
});

test("the stop switch needs two teams to restore, and the same team cannot sign twice", async ({ page }) => {
  const errors = collectErrors(page);
  await login(page, USER.commander);
  await openTab(page, "safety");

  await page.getByRole("button", { name: "Raise stop level" }).click();
  const raise = page.getByRole("dialog");
  await raise.getByLabel("New stop level").selectOption("K2");
  await raise.getByLabel("Reason").fill("Rehearsal of the stop switch");
  await raise.getByRole("button", { name: "Raise stop level" }).click();
  await raise.getByLabel("Enter your password to continue").fill("demo");
  await raise.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByTestId("status-line")).toContainText("AI stopped");
  await expect(page.getByTestId("mode-row").filter({ hasText: "Deterministic only" })).toHaveAttribute(
    "aria-current",
    "true",
  );

  await page.getByRole("button", { name: "Resume", exact: true }).click();
  const sign = page.getByRole("dialog");
  await sign.getByLabel("Reason").fill("Checked and clear");
  await sign.getByRole("button", { name: "Sign to resume" }).click();
  await expect(page.getByTestId("pending-restore")).toContainText("waiting for a second team to sign");
  await expect(page.getByRole("button", { name: /Sign as/ })).toBeDisabled();

  await switchUser(page, USER.waterCompliance);
  await page.getByRole("link", { name: "System health", exact: true }).click();
  await page.getByRole("tab", { name: "Stop controls" }).click();
  await expect(page.getByTestId("pending-restore")).toBeVisible();
  await page.getByRole("button", { name: /Sign as/ }).click();
  const second = page.getByRole("dialog");
  await second.getByLabel("Reason").fill("Second check done");
  await second.getByRole("button", { name: "Sign to resume" }).click();
  await expect(page.getByTestId("status-line")).toContainText("Normal operation");
  const stepUpRefusal = "Failed to load resource: the server responded with a status of 403 (Forbidden)";
  expect(errors).toEqual([stepUpRefusal]);
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
]) {
  test(`every InfoTip on Health and Readiness stays inside the viewport at ${viewport.width}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await login(page, USER.dutyManager);
    const pages = [...TABS.map((t) => `/health?tab=${t}`), "/readiness"];
    let seen = 0;
    for (const url of pages) {
      await page.goto(url);
      await expect(
        page.getByTestId(url.startsWith("/health") ? "status-line" : "readiness-summary"),
      ).toBeVisible();
      await expect(page.getByRole("status", { name: /Loading/ })).toHaveCount(0);
      const triggers = page.locator('button[aria-label^="What does"], button[aria-label^="Info:"]');
      const count = await triggers.count();
      seen += count;
      for (let i = 0; i < count; i++) {
        const trigger = triggers.nth(i);
        await trigger.scrollIntoViewIfNeeded();
        await trigger.click();
        const bubble = page.locator('[data-testid^="infotip-"]');
        await expect(bubble).toBeVisible();
        const box = await bubble.evaluate((el) => {
          const r = el.getBoundingClientRect();
          return {
            left: r.left,
            top: r.top,
            right: r.right,
            bottom: r.bottom,
            vw: innerWidth,
            vh: innerHeight,
          };
        });
        expect(box.left, `${url} tip ${i} left`).toBeGreaterThanOrEqual(0);
        expect(box.top, `${url} tip ${i} top`).toBeGreaterThanOrEqual(0);
        expect(box.right, `${url} tip ${i} right`).toBeLessThanOrEqual(box.vw);
        expect(box.bottom, `${url} tip ${i} bottom`).toBeLessThanOrEqual(box.vh);
        await page.keyboard.press("Escape");
        await expect(bubble).toHaveCount(0);
      }
    }
    expect(seen).toBeGreaterThanOrEqual(8);
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`axe finds no serious violations on Health and Readiness (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
    await login(page, USER.admin);
    for (const url of [...TABS.map((t) => `/health?tab=${t}`), "/readiness"]) {
      await page.goto(url);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(
        page.getByTestId(url.startsWith("/health") ? "status-line" : "readiness-summary"),
      ).toBeVisible();
      await expect(page.getByRole("status", { name: /Loading/ })).toHaveCount(0);
      if (url.endsWith("runs"))
        await page
          .getByRole("button", { name: /How request .* was made/ })
          .first()
          .click();
      if (url.endsWith("runs")) {
        const sheet = page.getByTestId("trace-sheet");
        await expect(sheet.getByTestId("trace-totals")).toBeVisible();
        await sheet.evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));
      }
      if (url.endsWith("safety")) await page.getByRole("button", { name: /What's on now/ }).click();
      const results = await new AxeBuilder({ page }).analyze();
      expect(
        results.violations.filter((v) => v.impact === "serious" || v.impact === "critical"),
        url,
      ).toEqual([]);
    }
  });
}

test("in grayscale every status carries a word or a shape, never colour alone", async ({ page }) => {
  await login(page, USER.dutyManager);
  await openTab(page, "data");
  await page.addStyleTag({ content: "html { filter: grayscale(1); }" });
  await expect(page.getByTestId("feed-row").last()).toContainText("Late");
  await expect(page.getByTestId("feed-row").first()).toContainText("On time");
  await expect(page.getByTestId("status-line").locator("svg")).toBeVisible();
  await openTab(page, "models");
  await expect(page.getByTestId("model-fact").first()).toContainText(/Below target|Met/);
});
