import { expect, type Page, test } from "@playwright/test";
import { login, USER } from "./support/login";

const SIZES = [
  { width: 1288, height: 742 },
  { width: 1512, height: 900 },
] as const;

const VIEWS = [
  { view: "heat", chart: "heat-chart", rows: "heat-unit-row", count: 5, action: "heat-action" },
  {
    view: "wildfire",
    chart: "fire-chart",
    rows: "wildfire-circuit-row",
    count: 10,
    action: "wildfire-action",
  },
] as const;

/** Elements with overflow auto/scroll whose content is taller or wider than the box; allowed regions excepted. */
async function overflowing(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    for (const el of [document.documentElement, ...Array.from(document.body.querySelectorAll("*"))]) {
      const style = getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden") continue;
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      const id = el.getAttribute("data-testid") ?? el.getAttribute("aria-label") ?? el.id;
      if (["auto", "scroll"].includes(style.overflowX) && el.scrollWidth - el.clientWidth > 1)
        out.push(`x ${el.tagName.toLowerCase()}[${id}] ${el.scrollWidth}/${el.clientWidth}`);
      if (el.closest("[data-scroll-region]")) continue;
      if (["auto", "scroll"].includes(style.overflowY) && el.scrollHeight - el.clientHeight > 1)
        out.push(`y ${el.tagName.toLowerCase()}[${id}] ${el.scrollHeight}/${el.clientHeight}`);
    }
    return out;
  });
}

/** The scroll regions of the pane template must not need to scroll either: the view fits the screen. */
async function regionOverflow(page: Page): Promise<string[]> {
  return page
    .locator("main [data-scroll-region]")
    .evaluateAll((els) =>
      els
        .filter((el) => el.scrollHeight - el.clientHeight > 1)
        .map((el) => `${el.getAttribute("data-scroll-region")} ${el.scrollHeight}/${el.clientHeight}`),
    );
}

test("deep links open each hazard view with one chart, one table and one read-only action", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, USER.executive);
  for (const v of VIEWS) {
    await page.goto(`/readiness?view=${v.view}`);
    await expect(page.getByTestId(v.chart)).toBeVisible();
    await expect(page.getByTestId(v.chart).locator("svg").first()).toBeVisible();
    await expect(page.getByTestId(v.rows)).toHaveCount(v.count);
    const action = page.getByTestId(v.action);
    await expect(action.getByTestId("action-title")).toBeVisible();
    await expect(action.getByRole("button", { name: /^(Sign|Approve)/ })).toHaveCount(0);
    await expect(page.locator("[data-origin=real]")).toHaveCount(1);
    await expect(page.locator("[data-origin=synthetic]")).toHaveCount(1);
    await page.getByTestId("hazard-info").click();
    await expect(page.getByTestId("hazard-sources")).toContainText(
      v.view === "heat" ? "data/fixtures/heat/" : "data/fixtures/tablerock/",
    );
    await page.keyboard.press("Escape");
  }
  await page.getByRole("tab", { name: "Pre-season" }).click();
  await expect(page).toHaveURL(/\/readiness$/);
  await expect(page.getByTestId("readiness-summary")).toBeVisible();
  expect(errors).toEqual([]);
});

test("the scenario menu opens a hazard view without moving the replay clock", async ({ page }) => {
  await login(page, USER.dutyManager);
  await page.goto("/");
  const clock = page.getByTestId("scenario-clock");
  await expect(clock).toHaveText(/ET/);
  await page.waitForTimeout(500);
  const before = await clock.textContent();
  const writes: string[] = [];
  page.on("request", (r) => r.method() !== "GET" && writes.push(new URL(r.url()).pathname));
  for (const [link, view, tab] of [
    [/^Heat/, "heat", "Heat wave"],
    [/^Wildfire/, "wildfire", "Wildfire weather"],
  ] as const) {
    await page.getByTestId("mode-strip").click();
    await page.getByTestId("other-scenarios").getByRole("link", { name: link }).click();
    await expect(page).toHaveURL(new RegExp(`/readiness\\?view=${view}`));
    await expect(page.getByRole("tab", { name: tab, selected: true })).toBeVisible();
    await expect(page.getByTestId("jump-dialog")).toHaveCount(0);
    await expect(clock).toHaveText(before ?? "");
  }
  expect(writes.filter((p) => /scenario|clock|demo/.test(p))).toEqual([]);
});

for (const size of SIZES) {
  for (const theme of ["light", "dark"] as const) {
    test(`hazard views fit ${size.width}x${size.height} in ${theme} without scrollbars`, async ({ page }) => {
      await page.setViewportSize(size);
      await page.addInitScript((t) => localStorage.setItem("sgw.theme", t), theme);
      await login(page, USER.dutyManager);
      const failures: string[] = [];
      for (const v of VIEWS) {
        await page.goto(`/readiness?view=${v.view}`);
        await page.getByTestId(v.chart).waitFor();
        await page.waitForTimeout(400);
        failures.push(...(await overflowing(page)).map((f) => `${v.view} ${f}`));
        failures.push(...(await regionOverflow(page)).map((f) => `${v.view} region ${f}`));
      }
      await page.getByTestId("mode-strip").click();
      await page.getByTestId("other-scenarios").waitFor();
      failures.push(...(await overflowing(page)).map((f) => `menu ${f}`));
      expect(failures).toEqual([]);
    });
  }
}
