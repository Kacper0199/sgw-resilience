import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

const SHOTS = process.env.SGW_SHOTS ?? "test-results/shots";

const openBrief = async (page: Page) => {
  await page.getByRole("link", { name: "Briefing", exact: true }).click();
  await expect(page).toHaveURL(/\/brief/);
  await expect(page.getByTestId("four-numbers")).toBeVisible();
};

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test("a reader gets the status word, four numbers, open clocks and one sentence per function", async ({
  page,
}) => {
  const errors = collectErrors(page);
  await login(page, USER.executive);
  await openBrief(page);
  await expect(page.getByTestId("status-header")).toContainText("Warning");
  await expect(page.getByTestId("status-header")).toContainText("Latest advisory");
  await expect(page.getByTestId("four-numbers").locator("> div")).toHaveCount(4);
  await expect(page.getByTestId("open-clock")).toHaveCount(2);
  await expect(page.getByTestId("function-line")).toHaveCount(4);
  await page.getByRole("button", { name: "About these numbers" }).click();
  await expect(page.getByTestId("caveat")).toContainText("Forecasts are estimates");
  await expect(page.getByTestId("brief-footer")).toContainText(
    "Exercise with synthetic data, not for operational use",
  );
  expect(errors).toEqual([]);
});

test("Forecast shows the model's expectation with its 80% range and the choice survives a reload", async ({
  page,
}) => {
  await login(page, USER.executive);
  await openBrief(page);
  await page.getByRole("radio", { name: "Forecast", exact: true }).click();
  await expect(page).toHaveURL(/show=forecast/);
  await expect(page.getByTestId("number-customers_out")).toContainText("Counts ");
  await page.reload();
  await expect(page.getByRole("radio", { name: "Forecast", exact: true })).toBeChecked();
  await page.getByRole("radio", { name: "Now", exact: true }).click();
  await expect(page.getByTestId("number-customers_out")).not.toContainText("Counts ");
});

test("an open clock leads to its decision", async ({ page }) => {
  await login(page, USER.commander);
  await openBrief(page);
  await page.getByTestId("open-clock").first().getByRole("link").first().click();
  await expect(page).toHaveURL(/\/\?d=PRP-PS17-FDR2207-PRIO/);
});

test("the Incident Commander drafts the report from its stages and promotes it", async ({ page }) => {
  const errors = collectErrors(page);
  await login(page, USER.commander);
  await openBrief(page);
  await expect(page.getByTestId("sitrep-current")).toBeVisible();
  await page.getByRole("button", { name: /Draft a report/ }).click();
  await expect(page.getByTestId("sitrep-progress")).toContainText("Collect the numbers from the platform");
  const draft = page.getByTestId("sitrep-draft");
  await expect(draft).toBeVisible({ timeout: 8000 });
  await expect(draft).toContainText("E1.Customers without power");
  await page.getByRole("button", { name: "Confirm report", exact: true }).click();
  await expect(page.getByTestId("sitrep-draft")).toHaveCount(0);
  await expect(page.getByTestId("sitrep-current")).toContainText("confirmed by Incident Commander");
  expect(errors).toEqual([]);
});

test("a function that cannot promote is told so in place", async ({ page }) => {
  await login(page, USER.waterLead);
  await openBrief(page);
  await page.getByRole("button", { name: /Draft a report/ }).click();
  await expect(page.getByTestId("sitrep-draft")).toBeVisible({ timeout: 8000 });
  await expect(page.getByRole("button", { name: "Confirm report", exact: true })).toBeDisabled();
  await expect(page.getByText("Only the Incident Commander can confirm a draft.")).toBeVisible();
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
  { width: 390, height: 844 },
]) {
  test(`the Brief fits at ${viewport.width} px without sideways scrolling`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("sgw.sidebar", "collapsed"));
    await page.setViewportSize(viewport);
    await login(page, USER.executive);
    await openBrief(page);
    const overflow = await page.evaluate(() => {
      const m = document.querySelector("main");
      return m ? m.scrollWidth - m.clientWidth : 0;
    });
    expect(overflow).toBeLessThanOrEqual(0);
    await expect(page.getByTestId("number-crews_working")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/brief-${viewport.width}-light.png`, fullPage: true });
  });

  test(`every InfoTip on the Brief stays inside the viewport at ${viewport.width}`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("sgw.sidebar", "collapsed"));
    await page.setViewportSize(viewport);
    await login(page, USER.executive);
    await openBrief(page);
    const triggers = page.locator('main button[aria-label^="What does"]:visible');
    const count = await triggers.count();
    expect(count).toBeGreaterThanOrEqual(4);
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
      expect(box.left, `tip ${i} left`).toBeGreaterThanOrEqual(0);
      expect(box.top, `tip ${i} top`).toBeGreaterThanOrEqual(0);
      expect(box.right, `tip ${i} right`).toBeLessThanOrEqual(box.vw);
      expect(box.bottom, `tip ${i} bottom`).toBeLessThanOrEqual(box.vh);
      await page.keyboard.press("Escape");
      await expect(bubble).toHaveCount(0);
    }
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`axe finds no serious violations on the Brief (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
    await login(page, USER.commander);
    await openBrief(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
    await page.getByRole("radio", { name: "Forecast", exact: true }).click();
    const forecast = await new AxeBuilder({ page }).analyze();
    expect(forecast.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });
}

test("the Brief reads in grayscale: severity has a shape and a word", async ({ page }) => {
  await login(page, USER.executive);
  await openBrief(page);
  await page.addStyleTag({ content: "html { filter: grayscale(1); }" });
  await expect(page.getByTestId("status-header")).toContainText("Warning");
  await page.screenshot({ path: `${SHOTS}/brief-1440-gray.png`, fullPage: true });
});

for (const theme of ["light", "dark"] as const) {
  for (const width of [1440, 1920]) {
    test(`Briefing screens at ${width} (${theme})`, async ({ page }) => {
      await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
      await page.setViewportSize({ width, height: width === 1920 ? 1080 : 900 });
      await login(page, USER.commander);
      await openBrief(page);
      await page.screenshot({ path: `${SHOTS}/brief-top-${width}-${theme}.png` });
      await page.evaluate(() => document.querySelector("main")?.scrollTo(0, 99999));
      await expect(page.getByRole("link", { name: "Situation report" })).toHaveAttribute(
        "aria-current",
        "location",
      );
      await page.screenshot({ path: `${SHOTS}/brief-bottom-${width}-${theme}.png` });
    });
  }
}

test("Briefing on a phone: report column, two-by-two numbers, deadlines as rows", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("sgw.sidebar", "collapsed"));
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, USER.executive);
  await openBrief(page);
  await expect(page.getByRole("navigation", { name: "On this page" })).toBeHidden();
  await expect(
    page.getByTestId("open-clock").first().getByRole("link", { name: "View decision" }).first(),
  ).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/brief-top-390-light.png` });
  await page.evaluate(() => document.querySelector("main")?.scrollTo(0, 600));
  await page.screenshot({ path: `${SHOTS}/brief-mid-390-light.png` });
});
