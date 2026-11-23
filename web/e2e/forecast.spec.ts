import { mkdirSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

const SHOTS = process.env.SGW_SHOTS;

function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

const setTheme = (page: Page, theme: "light" | "dark") =>
  page.evaluate((t) => {
    document.documentElement.dataset.theme = t;
  }, theme);

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

test("counties: nested fans with a legend and units", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page, USER.commander);
  await page.goto("/forecast");
  await expect(page.getByRole("heading", { name: "Forecast", exact: true })).toBeVisible();
  await expect(page.getByTestId("fan-legend")).toContainText("Median");
  const chart = page.getByTestId("fan-chart");
  await expect(chart.locator("svg")).toBeVisible();
  await expect(chart).toContainText("Customers without power at the peak");
  await expect(page.getByRole("table", { name: "County ranges in customers" }).getByRole("row")).toHaveCount(
    13,
  );
  expect(errors).toEqual([]);
});

test("plan change: the latest advisory moves the PS-17 share past the act-now line", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page, USER.commander);
  await page.goto("/forecast?tab=plan&at=2024-09-26T15%3A00%3A00Z");
  const plan = page.getByTestId("plan-change");
  await expect(plan).toContainText("What changed since the previous advisory");
  const generator = plan.getByTestId("plan-action").filter({ hasText: "portable generator" });
  await expect(generator).toContainText("13 of 40 scenarios");
  await expect(generator).toContainText("37 of 40 scenarios");
  await expect(generator.getByTestId("crossed")).toContainText(
    /Above the act-now share \(32 of 40\)|Needed in 37 of 40 scenarios/,
  );
  await expect(plan.getByTestId("delta").first()).toContainText("+");
  expect(errors).toEqual([]);
});

test("what if: three scenarios against the baseline", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page, USER.commander);
  await page.goto("/forecast?view=whatif");
  const rows = page.getByTestId("whatif-row");
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(1)).toContainText("Storm track 40 km further east");
  await expect(rows.nth(2)).toContainText("Winds 10% stronger");
  await expect(rows.nth(3)).toContainText("Mutual-aid request 12 h later");
  await page.getByRole("button", { name: "About these what-ifs" }).click();
  await expect(page.getByRole("dialog")).toContainText("Nothing here changes the plan");
  expect(errors).toEqual([]);
});

test("backtest: the leave-one-storm-out table comes first, with both baselines and the worst miss", async ({
  page,
}) => {
  const errors = watchConsole(page);
  await login(page, USER.commander);
  await page.goto("/forecast?tab=backtest");
  const table = page.getByTestId("backtest-table");
  await expect(table).toBeVisible();
  const rows = page.getByTestId("backtest-row");
  await expect(rows).toHaveCount(4);
  const helene = rows.filter({ hasText: "Helene" });
  await expect(helene).toContainText("29%");
  await page.getByRole("button", { name: "More measures" }).click();
  await expect(page.getByTestId("backtest-detail")).toContainText("184,698");
  await expect(table).toContainText("Standard damage curve");
  await expect(table).toContainText("Wind rule");
  await expect(page.getByTestId("coverage-caveat")).toContainText("Helene: 29%");
  const tableTop = (await table.boundingBox())?.y ?? 0;
  const summaryTop = (await page.getByTestId("backtest-summary").first().boundingBox())?.y ?? 0;
  expect(tableTop).toBeLessThan(summaryTop);
  expect(errors).toEqual([]);
});

test("backtest: the 24-storm report reads in the same table", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page, USER.commander);
  await page.goto("/forecast?tab=backtest&report=outage_loso_v2");
  await expect(page.getByTestId("backtest-row")).toHaveCount(24);
  await expect(page.getByTestId("backtest-table")).toContainText("Damage curve fitted to past storms");
  const under = page
    .getByTestId("backtest-summary")
    .filter({ hasText: "Storms where the forecast total fell below what happened" });
  await expect(under).toContainText("18");
  await expect(under).toContainText("Below target");
  expect(errors).toEqual([]);
});

test("forecast: no serious accessibility violations in light and dark", async ({ page }) => {
  await login(page, USER.commander);
  for (const tab of ["counties", "counties&view=whatif", "plan", "backtest"]) {
    await page.goto(`/forecast?tab=${tab}`);
    await expect(page.getByRole("tabpanel")).toBeVisible();
    await page.waitForTimeout(400);
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await page.waitForTimeout(400);
      const result = await new AxeBuilder({ page }).analyze();
      const serious = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(serious.map((v) => `${tab} ${theme} ${v.id}: ${v.nodes[0]?.html}`)).toEqual([]);
    }
  }
});

test("forecast: screenshots for the review", async ({ page }) => {
  test.setTimeout(120_000);
  await login(page, USER.commander);
  for (const [w, h] of [
    [1440, 900],
    [1920, 1080],
  ] as const) {
    await page.setViewportSize({ width: w, height: h });
    for (const tab of ["counties", "counties&view=whatif", "plan", "backtest"]) {
      for (const theme of ["light", "dark"] as const) {
        await page.goto(`/forecast?tab=${tab}&at=2024-09-26T15%3A00%3A00Z`);
        await expect(page.getByRole("tabpanel")).toBeVisible();
        await setTheme(page, theme);
        await page.waitForTimeout(500);
        await shot(page, `forecast-${tab}-${w}-${theme}`);
      }
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/forecast?tab=counties&at=2024-09-26T15%3A00%3A00Z");
  await expect(page.getByTestId("fan-chart").locator("svg")).toBeVisible();
  await page.evaluate(() => {
    document.documentElement.style.filter = "grayscale(1)";
  });
  await page.waitForTimeout(300);
  await shot(page, "forecast-counties-1440-grayscale");
});
