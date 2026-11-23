import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

const SHOTS = process.env.SGW_SHOTS ?? "test-results/shots";
const OBS_KEY = "sgw.mock.obs_up";

const openAdmin = async (page: Page) => {
  await page.getByRole("link", { name: "Admin", exact: true }).click();
  await expect(page).toHaveURL(/\/admin/);
  await expect(page.getByRole("tab", { name: "Users and roles" })).toBeVisible();
};

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

const tab = (page: Page, name: RegExp | string) => page.getByRole("tab", { name });

test("who could do what, who did what and can we prove it: users, policies, integrations, audit and AI configuration", async ({
  page,
}) => {
  const errors = collectErrors(page);
  await login(page, USER.admin);
  await openAdmin(page);

  await expect(page.getByTestId("user-row")).toHaveCount(11);
  await expect(page.getByTestId("right-row").first()).toBeVisible();
  await page.getByTestId("user-row").nth(5).click();
  await expect(page.getByTestId("user-row").nth(5)).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("person-pane")).toBeVisible();
  await page.getByRole("radio", { name: /^By action/ }).click();
  await expect(page.getByTestId("action-row").filter({ hasText: "Issue a boil-water notice" })).toContainText(
    "Water Compliance Officer",
  );

  await tab(page, "Policies").click();
  await expect(page).toHaveURL(/tab=policies/);
  await expect(page.getByTestId("policy-row").first()).toBeVisible();
  await expect(page.getByRole("searchbox", { name: "Search settings" })).toBeVisible();

  await tab(page, "Integrations").click();
  await expect(page.getByTestId("token-row")).toHaveCount(3);
  await expect(page.getByTestId("sub-row").nth(1)).toContainText("Disabled");
  await expect(page.locator("body")).not.toContainText(/whsec_|sgwi_/);

  await tab(page, "Audit log").click();
  await page.getByRole("button", { name: "Check audit log", exact: true }).click();
  await expect(page.getByTestId("verify-result")).toContainText("The audit log passed its check");

  await tab(page, "AI settings").click();
  await expect(page.getByTestId("ai-row").filter({ hasText: "Look things up" })).toContainText(
    "Decision deadline",
  );
  expect(errors).toEqual([]);
});

test("a policy chip link opens the policy and marks its row", async ({ page }) => {
  await login(page, USER.admin);
  await page.goto("/admin?tab=policies&key=policy_break_glass_cosign_hours");
  const row = page.locator('[data-testid="policy-row"][aria-current="true"]');
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("Emergency approval co-sign");
  await expect(row).toContainText("24 hours");
  await expect(row).toBeInViewport();
  await expect(tab(page, "Policies")).toHaveAttribute("aria-selected", "true");
});

test("system metrics shows the platform's own numbers and opens Grafana only when it is up", async ({
  page,
}) => {
  await login(page, USER.admin);
  await page.goto("/admin?tab=metrics");
  await expect(page.getByTestId("metrics")).toContainText("Typical response");
  await expect(page.getByTestId("metrics")).not.toContainText(/uv run|obs up/);
  await expect(page.getByRole("link", { name: /Open Grafana/ })).toHaveCount(0);
  await page.evaluate((k) => sessionStorage.setItem(k, "1"), OBS_KEY);
  await page.reload();
  const link = page.getByRole("link", { name: /Open Grafana/ });
  await expect(link).toHaveAttribute("href", "http://127.0.0.1:3001/");
  await expect(link).toHaveAttribute("target", "_blank");
  await page.evaluate((k) => sessionStorage.removeItem(k), OBS_KEY);
});

test("everyone but the platform team is told Admin is not for them", async ({ page }) => {
  await login(page, USER.commander);
  await expect(page.getByRole("link", { name: "Notifications" }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Admin", exact: true })).toHaveCount(0);
  await page.goto("/admin");
  await expect(page.getByText(/Admin is for the platform team/)).toBeVisible();
  await expect(page.getByRole("tab", { name: "Policies" })).toHaveCount(0);
});

test("the tabs work from the keyboard", async ({ page }) => {
  await login(page, USER.admin);
  await openAdmin(page);
  await tab(page, "Users and roles").focus();
  await page.keyboard.press("ArrowRight");
  await expect(tab(page, "Policies")).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowRight");
  await expect(tab(page, "Integrations")).toHaveAttribute("aria-selected", "true");
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
]) {
  test(`every InfoTip on Admin stays inside the viewport at ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await login(page, USER.admin);
    await openAdmin(page);
    let seen = 0;
    for (const name of ["Users and roles", "Policies", "Integrations", "Audit log", "AI settings"]) {
      await tab(page, name).click();
      const triggers = page.locator('button[aria-label^="What does"]');
      await expect(triggers.first()).toBeVisible();
      const count = await triggers.count();
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
        expect(box.left, `${name} tip ${i} left`).toBeGreaterThanOrEqual(0);
        expect(box.top, `${name} tip ${i} top`).toBeGreaterThanOrEqual(0);
        expect(box.right, `${name} tip ${i} right`).toBeLessThanOrEqual(box.vw);
        expect(box.bottom, `${name} tip ${i} bottom`).toBeLessThanOrEqual(box.vh);
        await page.keyboard.press("Escape");
        await expect(bubble).toHaveCount(0);
        seen++;
      }
    }
    expect(seen).toBeGreaterThanOrEqual(7);
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`axe finds no serious violations on every Admin tab (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
    await login(page, USER.admin);
    await openAdmin(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    for (const name of [
      "Users and roles",
      "Policies",
      "Integrations",
      "Audit log",
      "AI settings",
      "System metrics",
    ]) {
      await tab(page, new RegExp(name)).click();
      const results = await new AxeBuilder({ page }).analyze();
      const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(
        serious.map((v) => `${v.id}: ${v.nodes[0]?.html}`),
        `${name} ${theme}`,
      ).toEqual([]);
    }
  });
}

test("admin: screenshots for the review", async ({ page }) => {
  test.setTimeout(120_000);
  await login(page, USER.admin);
  await openAdmin(page);
  for (const [w, h] of [
    [1440, 900],
    [1920, 1080],
  ] as const) {
    await page.setViewportSize({ width: w, height: h });
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);
      for (const [name, slug] of [
        ["Users and roles", "users"],
        ["Policies", "policies"],
        ["Integrations", "integrations"],
        ["Audit log", "audit"],
        ["AI settings", "ai"],
        ["System metrics", "metrics"],
      ] as const) {
        await tab(page, new RegExp(name)).click();
        await page.waitForTimeout(150);
        await page.screenshot({ path: `${SHOTS}/admin-${slug}-${w}-${theme}.png` });
      }
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "light";
    document.documentElement.style.filter = "grayscale(1)";
  });
  await tab(page, /Integrations/).click();
  await page.screenshot({ path: `${SHOTS}/admin-integrations-1440-grayscale.png` });
});
