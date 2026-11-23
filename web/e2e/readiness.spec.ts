import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login, USER } from "./support/login";

test("readiness opens with key numbers, then not-ready checks, no-record checks and folded ready checks", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, USER.dutyManager);
  await page.getByRole("link", { name: "Readiness", exact: true }).click();
  await expect(page).toHaveURL(/\/readiness$/);

  const summary = page.getByTestId("readiness-summary");
  await expect(summary).toContainText("Pre-season review, 6 May 2024");
  await expect(summary).toContainText("ready");
  const strip = page.getByRole("main");
  await expect(strip.getByText("overdue").first()).toBeVisible();
  const rows = page.getByTestId("readiness-row");
  await expect(rows.first()).toContainText("Overdue");
  await expect(rows.first()).toContainText("Operations");
  await expect(rows.filter({ hasText: "No record" }).first()).toBeVisible();
  await expect(rows.filter({ hasText: /^Ready/ })).toHaveCount(0);
  await page.getByRole("button", { name: /^Ready/ }).click();
  await expect(rows.filter({ hasText: /^Ready/ }).first()).toBeVisible();

  await page.getByRole("radio", { name: "Water" }).click();
  await expect(page).toHaveURL(/domain=water/);
  await expect(rows.filter({ hasText: "Power" })).toHaveCount(0);
  await expect(rows.first()).toContainText("Water");
  expect(errors).toEqual([]);
});

test("selecting a row opens its detail and the link to the decision", async ({ page }) => {
  await login(page, USER.dutyManager);
  await page.goto("/readiness");
  const rows = page.getByTestId("readiness-row");
  await rows.nth(1).click();
  await expect(page).toHaveURL(/item=/);
  const detail = page.getByTestId("readiness-detail");
  await expect(detail).toContainText("What is missing");
  await expect(detail.getByRole("button", { name: "Record result" })).toHaveCount(0);
});

test("the list holds at 1024 without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await login(page, USER.dutyManager);
  await page.goto("/readiness");
  await expect(page.getByTestId("readiness-row").first()).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const rowOverflow = await page
    .getByTestId("readiness-row")
    .evaluateAll((rows) => rows.filter((r) => r.scrollWidth > r.clientWidth).length);
  expect(rowOverflow).toBe(0);
});

test("axe finds no serious violations with the utility filter on keyboard focus", async ({ page }) => {
  await login(page, USER.dutyManager);
  await page.goto("/readiness");
  await page.getByRole("radio", { name: "All" }).focus();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
});
